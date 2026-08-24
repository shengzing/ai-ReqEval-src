"""Vision parsing services."""

from __future__ import annotations

from pathlib import Path
import json
from uuid import uuid4
from typing import Any, Optional

from fastapi import HTTPException, status

from src.apps.api.app.domain.models import EvidenceItem, VisionParseResult
from src.apps.api.app.services.project_service import assess_file_relevance, get_project
from src.apps.api.app.integrations.file_storage import LocalFileStorage
from src.apps.api.app.integrations.vision_llm import VisionLLMClient
from src.apps.api.app.repositories.store import get_file_artifact, save_evidence_item, save_file_artifact
from src.apps.api.app.services.log_service import create_execution_log


def parse_file_with_vision(
    *,
    file_id: str,
    prompt: str,
    target_schema: dict[str, str],
    project_context: Optional[dict[str, Any]] = None,
) -> VisionParseResult:
    artifact = get_file_artifact(file_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if artifact.storage_path is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File storage path not found")

    client = VisionLLMClient()
    result = client.parse_file(
        file_path=Path(artifact.storage_path),
        file_id=file_id,
        project_id=artifact.project_id,
        prompt=prompt,
        target_schema=target_schema,
        project_context=project_context or {},
        content_type=artifact.content_type,
    )
    artifact.status = "parsed"
    combined_vision_text = "\n".join(
        str(fragment.get("snippet", ""))
        for fragment in result.evidence_fragments
        if isinstance(fragment, dict)
    )
    relevance = assess_file_relevance(
        project=get_project(artifact.project_id),
        filename=artifact.filename,
        extracted_text=combined_vision_text,
    )
    artifact.relevance_status = str(relevance["status"])
    artifact.relevance_score = float(relevance["score"])
    artifact.relevance_reasons = list(relevance["reasons"])
    # HCR-P1-03：vision 路径补 rule_version + input_hash + source，
    # 与 parse_file 主路径对齐，避免 vision 解析的 evidence 丢失溯源。
    artifact.relevance_rule_version = str(relevance["rule_version"])
    artifact.relevance_input_hash = str(relevance["input_hash"])
    artifact.relevance_source = "machine"
    save_file_artifact(artifact)
    for fragment in result.evidence_fragments:
        evidence = EvidenceItem(
            id="evidence-{0}".format(uuid4().hex[:8]),
            project_id=artifact.project_id,
            name="{0} 视觉证据".format(artifact.filename),
            source_type="vision",
            source_file_id=artifact.id,
            snippet=fragment.get("snippet"),
            status="parsed",
            relevance_status=artifact.relevance_status,
            relevance_score=artifact.relevance_score,
            relevance_reasons=list(artifact.relevance_reasons),
            relevance_rule_version=artifact.relevance_rule_version,
            relevance_input_hash=artifact.relevance_input_hash,
            relevance_source=artifact.relevance_source,
        )
        save_evidence_item(evidence)
    LocalFileStorage().save_vision_parse_result(
        artifact.project_id,
        artifact.id,
        {
            "file_id": artifact.id,
            "model": result.model,
            "structured_fields": result.structured_fields,
            "evidence_fragments": result.evidence_fragments,
            "uncertainties": result.uncertainties,
            "to_confirm": result.to_confirm,
        },
    )
    create_execution_log(
        project_id=artifact.project_id,
        action="file.vision_parsed",
        resource_type="file",
        resource_id=artifact.id,
        details={
            "structured_field_count": len(result.structured_fields),
            "evidence_fragment_count": len(result.evidence_fragments),
            "to_confirm_count": len(result.to_confirm),
            "relevance_status": artifact.relevance_status,
            "relevance_score": artifact.relevance_score,
            # HCR-P1-03：与 parse_file 对齐，补溯源两字段。
            "relevance_rule_version": artifact.relevance_rule_version,
            "relevance_input_hash": artifact.relevance_input_hash,
        },
    )
    return result


def load_project_vision_results(project_id: str) -> list[dict[str, Any]]:
    parsed_dir = LocalFileStorage().project_parsed_dir(project_id)
    if not parsed_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(parsed_dir.glob("*.vision.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["path"] = str(path)
        items.append(payload)
    return items
