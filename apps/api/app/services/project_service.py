"""Project and stage services."""

from __future__ import annotations

import logging
import base64
import mimetypes
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import HTTPException, status
from pymongo.errors import PyMongoError

from src.apps.api.app.domain.models import Conversation, ConversationMessage, EvidenceItem, FileArtifact, Project, ReportArtifact, Stage, StageResult, utcnow
from src.apps.api.app.integrations.file_storage import LocalFileStorage
from src.packages.reqeval.data.document_processor import DocumentProcessor, generate_document_summary
from src.apps.api.app.repositories.store import (
    add_conversation_message,
    count_file_artifacts_for_projects,
    get_file_artifact,
    get_conversation as repo_get_conversation,
    get_project as repo_get_project,
    get_report as repo_get_report,
    get_stage as repo_get_stage,
    get_latest_stage_result,
    list_file_artifacts,
    list_autoresearch_records as repo_list_autoresearch_records,
    list_autoresearch_records_for_stages,
    list_conversations as repo_list_conversations,
    list_conversations_for_stages,
    list_conversation_action_proposals,
    list_evidence_items,
    list_projects as repo_list_projects,
    list_run_events_by_conversation,
    list_run_events_for_conversations,
    list_stage_results as repo_list_stage_results,
    list_stages as repo_list_stages,
    list_stages_for_projects,
    save_conversation,
    save_evidence_item,
    save_file_artifact,
    save_project,
    save_report,
    save_stage_result,
    save_stage,
    update_conversation_status,
)
from src.apps.api.app.services.log_service import create_execution_log, create_version_log, list_execution_logs, list_version_logs
from src.apps.api.app.services.settings_service import ensure_default_settings
from src.apps.api.app.services.stage_result_service import build_stage_result_diff

DEFAULT_STAGES: tuple[tuple[str, str, str], ...] = (
    ("stage-1", "阶段一：场景解构与风险定级", "识别场景边界、流程节点、风险等级和 HITL。"),
    ("stage-2", "阶段二：价值建模与目标 SLA", "把风险结论转成价值、成本和目标 SLA。"),
    ("stage-3", "阶段三：任务拆解与微型探针", "设计原子任务、样本台账和 Actual SLA。"),
    ("stage-4", "阶段四：三维对齐与报告", "汇总证据、生成建议和报告。"),
)
logger = logging.getLogger(__name__)

def _file_storage() -> LocalFileStorage:
    return LocalFileStorage()


def create_project(*, name: str, goal: str) -> Project:
    project_id = f"project-{uuid4().hex[:8]}"
    project = Project(id=project_id, name=name, goal=goal)
    stages: list[Stage] = []
    for stage_slug, stage_name, objective in DEFAULT_STAGES:
        stage = Stage(
            id=f"{project_id}-{stage_slug}",
            project_id=project_id,
            name=stage_name,
            objective=objective,
        )
        save_stage(stage)
        stages.append(stage)
    project.stages = stages
    save_project(project)
    _file_storage().ensure_project_layout(project_id)
    ensure_default_settings(project_id)
    create_execution_log(
        project_id=project_id,
        action="project.created",
        resource_type="project",
        resource_id=project_id,
        details={"name": name},
    )
    create_version_log(
        project_id=project_id,
        resource_type="project",
        resource_id=project_id,
        change_type="created",
        summary="Project created with default stage layout.",
    )
    return project


def _list_active_projects() -> list[Project]:
    try:
        return [project for project in repo_list_projects() if project.status != "deleted"]
    except PyMongoError as exc:
        logger.warning(
            "MongoDB project list read failed; returning empty project list. error=%s",
            exc,
        )
        return []


def list_projects() -> list[Project]:
    return _list_active_projects()


def get_workspace_tree() -> list[dict[str, object]]:
    projects = _list_active_projects()
    project_ids = [project.id for project in projects]
    stages = list_stages_for_projects(project_ids)
    stage_ids = [stage.id for stage in stages]
    conversations = list_conversations_for_stages(stage_ids)
    conversation_ids = [conversation.id for conversation in conversations]
    run_events = list_run_events_for_conversations(conversation_ids)
    autoresearch_records = list_autoresearch_records_for_stages(stage_ids)

    stages_by_project: dict[str, list[Stage]] = {}
    for stage in stages:
        stages_by_project.setdefault(stage.project_id, []).append(stage)

    events_by_conversation: dict[str, list] = {}
    for event in run_events:
        if event.conversation_id:
            events_by_conversation.setdefault(event.conversation_id, []).append(event)

    conversations_by_stage: dict[str, list[Conversation]] = {}
    for conversation in conversations:
        conversations_by_stage.setdefault(conversation.stage_id, []).append(
            _hydrate_conversation_messages(conversation, events_by_conversation.get(conversation.id, []))
        )

    pending_by_stage: dict[str, int] = {}
    for record in autoresearch_records:
        if record.status == "pending":
            pending_by_stage[record.stage_id] = pending_by_stage.get(record.stage_id, 0) + 1

    file_counts_by_project = count_file_artifacts_for_projects(project_ids)

    items: list[dict[str, object]] = []
    for project in projects:
        stage_nodes: list[dict[str, object]] = []
        pending_count = 0
        for stage in stages_by_project.get(project.id, []):
            pending_confirmations = pending_by_stage.get(stage.id, 0)
            pending_count += pending_confirmations
            stage_nodes.append(
                {
                    **stage.__dict__,
                    "pending_confirmations": pending_confirmations,
                    "conversations": conversations_by_stage.get(stage.id, []),
                }
            )
        items.append(
            {
                **project.__dict__,
                "stages": stage_nodes,
                "pending_count": pending_count,
                "file_count": file_counts_by_project.get(project.id, 0),
            }
        )
    return items


def get_project(project_id: str) -> Project:
    project = repo_get_project(project_id)
    if project is None or project.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project.updated_at = utcnow()
    project.stages = repo_list_stages(project_id)
    save_project(project)
    return project


def soft_delete_project(project_id: str) -> None:
    project = repo_get_project(project_id)
    if project is None or project.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project.status = "deleted"
    project.updated_at = utcnow()
    save_project(project)
    create_execution_log(
        project_id=project_id,
        action="project.deleted",
        resource_type="project",
        resource_id=project_id,
        details={"name": project.name},
    )
    create_version_log(
        project_id=project_id,
        resource_type="project",
        resource_id=project_id,
        change_type="deleted",
        summary="Project removed from active workspace.",
    )


def update_project(project_id: str, name: str) -> Project:
    """Rename a project. Loads the persisted project, validates the new name is
    non-empty, persists, and records execution/version logs for the audit trail."""
    if not name or not name.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Project name must not be empty")
    project = repo_get_project(project_id)
    if project is None or project.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    old_name = project.name
    project.name = name.strip()
    project.updated_at = utcnow()
    save_project(project)
    create_execution_log(
        project_id=project_id,
        action="project.renamed",
        resource_type="project",
        resource_id=project_id,
        details={"old_name": old_name, "new_name": project.name},
    )
    create_version_log(
        project_id=project_id,
        resource_type="project",
        resource_id=project_id,
        change_type="updated",
        summary=f"Project renamed from \"{old_name}\" to \"{project.name}\".",
    )
    return project


def get_stage(stage_id: str) -> Stage:
    stage = repo_get_stage(stage_id)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    return stage


def list_stages(project_id: str) -> list[Stage]:
    _ = get_project(project_id)
    return repo_list_stages(project_id)


def list_stage_results(stage_id: str) -> list[StageResult]:
    _ = get_stage(stage_id)
    return repo_list_stage_results(stage_id)


def build_stage_lock_checks(stage_id: str) -> dict[str, object]:
    stage = get_stage(stage_id)
    stage_result = get_latest_stage_result(stage_id)
    pending_records = [item.id for item in repo_list_autoresearch_records(stage_id) if item.status == "pending"]
    evidence_bound = True
    if stage_result is not None and stage_result.input_file_ids:
        evidence_bound = bool(stage_result.evidence_item_ids)

    # Base checks for all stages
    checks = [
        {
            "key": "stage_result_exists",
            "label": "存在阶段结果草稿",
            "passed": stage_result is not None,
        },
        {
            "key": "evidence_bound",
            "label": "有输入材料时必须完成证据绑定",
            "passed": evidence_bound,
        },
        {
            "key": "no_pending_autoresearch",
            "label": "不存在待处理 autoResearch",
            "passed": not pending_records,
        },
        {
            "key": "status_lockable",
            "label": "阶段状态允许锁定",
            "passed": stage.status != "failed",
        },
    ]

    # Stage 1-specific checks
    if stage_id.endswith("stage-1") and stage_result is not None:
        scenario_summary = (stage_result.result_payload or {}).get("scenario_summary", {})
        quality_scores = (stage_result.result_payload or {}).get("stage1_validation", {}).get("quality", {})
        confirmation_ids = stage_result.confirmation_ids or []
        risk_level = scenario_summary.get("risk_level", "")
        hitl_level = scenario_summary.get("hitl_level", "")

        # 1. scenario_summary exists (hard blocker)
        checks.append({
            "key": "s1_scenario_summary_exists",
            "label": "阶段一场景摘要已生成",
            "passed": bool(scenario_summary),
        })

        # 2. evidence_refs non-empty (advisory — evidence may be genuinely empty)
        checks.append({
            "key": "s1_evidence_refs_nonempty",
            "label": "场景摘要包含证据引用",
            "passed": bool(scenario_summary.get("evidence_refs")),
            "advisory": True,
        })

        # 3. risk_level valid enum (hard blocker)
        from src.apps.api.app.services.stage1_contract import RISK_LEVELS
        checks.append({
            "key": "s1_risk_level_valid",
            "label": "风险等级为有效枚举值（L1|L2|L3）",
            "passed": risk_level in RISK_LEVELS,
        })

        # 4. hitl_level valid enum (hard blocker)
        from src.apps.api.app.services.stage1_contract import HITL_LEVELS
        checks.append({
            "key": "s1_hitl_level_valid",
            "label": "HITL 等级为有效枚举值",
            "passed": hitl_level in HITL_LEVELS,
        })

        # 5. L3 → HITL is strict or mandatory (hard blocker)
        if risk_level == "L3":
            checks.append({
                "key": "s1_l3_hitl_strict_or_mandatory",
                "label": "L3 风险等级必须 strict 或 mandatory HITL",
                "passed": hitl_level in {"strict", "mandatory"},
            })

        # 6. L3 → non-empty prohibited_conditions (hard blocker)
        if risk_level == "L3":
            checks.append({
                "key": "s1_l3_prohibited_conditions",
                "label": "L3 风险等级必须包含禁止条件",
                "passed": bool(scenario_summary.get("prohibited_conditions")),
            })

        # 7. L3 → non-empty fatal_errors (hard blocker)
        if risk_level == "L3":
            checks.append({
                "key": "s1_l3_fatal_errors",
                "label": "L3 风险等级必须包含致命错误场景",
                "passed": bool(scenario_summary.get("fatal_errors")),
            })

        # 8. No pending AutoResearch (already in base checks, but explicit for stage-1)
        # (already covered by no_pending_autoresearch above)

        # 9. L2/L3 → at least one confirmation_id (hard blocker)
        if risk_level in {"L2", "L3"}:
            checks.append({
                "key": "s1_l2_l3_confirmation_required",
                "label": "L2/L3 风险等级需要至少一条人工确认",
                "passed": bool(confirmation_ids),
            })

        # 10. Quality score thresholds (advisory — inform but do not block)
        quality_thresholds = {
            "completeness_score": (0.70, "完整性 ≥ 0.70"),
            "evidence_coverage_score": (0.70, "证据覆盖度 ≥ 0.70"),
            "risk_consistency_score": (0.90, "风险一致性 ≥ 0.90"),
            "hitl_alignment_score": (0.90, "HITL 对齐度 ≥ 0.90"),
        }
        for score_name, (threshold, label) in quality_thresholds.items():
            score_val = quality_scores.get(score_name, 0.0)
            checks.append({
                "key": f"s1_quality_{score_name}",
                "label": f"阶段一质量：{label}",
                "passed": score_val >= threshold,
                "advisory": True,
            })

    # "ready" is True only when all non-advisory checks pass.
    # Advisory checks still report their passed/fail status but do not block locking.
    blocking_checks = [item for item in checks if not item.get("advisory", False)]
    return {"stage_id": stage_id, "checks": checks, "ready": all(item["passed"] for item in blocking_checks)}


def list_conversations(stage_id: str) -> list[Conversation]:
    _ = get_stage(stage_id)
    items = repo_list_conversations(stage_id)
    visible = [item for item in items if item.status != "deleted"]
    return [_hydrate_conversation_messages(item) for item in visible]


def get_conversation(conversation_id: str) -> Conversation:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None or conversation.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return _hydrate_conversation_messages(conversation)


def archive_conversation(conversation_id: str) -> Conversation:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None or conversation.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.status == "archived":
        return conversation
    archived_at = utcnow()
    # Update only status fields atomically; the full-document replace in
    # save_conversation would clobber a concurrent $push message append.
    update_conversation_status(
        conversation_id,
        status="archived",
        archived_at=archived_at,
    )
    conversation.status = "archived"
    conversation.archived_at = archived_at
    conversation.updated_at = archived_at
    create_execution_log(
        project_id=conversation.project_id,
        action="conversation.archived",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": conversation.stage_id, "title": conversation.title},
    )
    return _hydrate_conversation_messages(conversation)


def restore_conversation(conversation_id: str) -> Conversation:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None or conversation.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.status == "active":
        return conversation
    # Update only status fields atomically; the full-document replace in
    # save_conversation would clobber a concurrent $push message append.
    update_conversation_status(
        conversation_id,
        status="active",
    )
    conversation.status = "active"
    conversation.archived_at = None
    conversation.updated_at = utcnow()
    create_execution_log(
        project_id=conversation.project_id,
        action="conversation.restored",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": conversation.stage_id, "title": conversation.title},
    )
    return _hydrate_conversation_messages(conversation)


def soft_delete_conversation(conversation_id: str) -> None:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None:
        return
    if conversation.status == "deleted":
        return
    # Update only status fields atomically; the full-document replace in
    # save_conversation would clobber a concurrent $push message append.
    update_conversation_status(
        conversation_id,
        status="deleted",
    )
    conversation.status = "deleted"
    conversation.updated_at = utcnow()
    create_execution_log(
        project_id=conversation.project_id,
        action="conversation.deleted",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": conversation.stage_id, "title": conversation.title},
    )


def _hydrate_conversation_messages(
    conversation: Conversation,
    run_events: Optional[list] = None,
) -> Conversation:
    if not conversation.project_id:
        # Backfill project_id from stage for legacy records.
        stage = repo_get_stage(conversation.stage_id)
        if stage is not None:
            conversation.project_id = stage.project_id
    messages: list[ConversationMessage] = list(conversation.messages)
    seen = {(item.role, item.content, item.source_event_id) for item in messages}
    for event in run_events if run_events is not None else list_run_events_by_conversation(conversation.id):
        message = _run_event_to_conversation_message(event)
        if message is None or (message.role, message.content, message.source_event_id) in seen:
            continue
        messages.append(message)
        seen.add((message.role, message.content, message.source_event_id))
    conversation.messages = messages
    _hydrate_conversation_action_metadata(conversation)
    return conversation


def _hydrate_conversation_action_metadata(conversation: Conversation) -> None:
    """Refresh displayed proposal state without storing sensitive payloads in messages."""
    if not any(message.action_proposals for message in conversation.messages):
        return
    try:
        proposals_by_id = {
            proposal.id: proposal
            for proposal in list_conversation_action_proposals(conversation.id)
        }
    except PyMongoError:
        logger.warning("Conversation action proposal lookup failed for %s", conversation.id)
        return
    for message in conversation.messages:
        if not message.action_proposals:
            continue
        refreshed: list[dict] = []
        for summary in message.action_proposals:
            # Keep the conversation document and response deliberately
            # presentation-only; proposal payloads can include internal
            # execution inputs and must remain in the proposal record.
            proposal_id = summary.get("id")
            item = {
                key: summary[key]
                for key in ("id", "action_type", "title", "requires_confirmation", "status", "run_id")
                if key in summary
            }
            proposal = proposals_by_id.get(proposal_id)
            if proposal is not None:
                item["status"] = proposal.status
                item["run_id"] = proposal.run_id
            refreshed.append(item)
        message.action_proposals = refreshed


def _action_proposal_summary(item: dict) -> dict:
    """Return the display-safe subset of a controlled action proposal."""
    return {
        key: item[key]
        for key in ("id", "action_type", "title", "requires_confirmation", "status", "run_id")
        if key in item
    }


def _run_event_to_conversation_message(event) -> Optional[ConversationMessage]:
    event_type = getattr(event, "type", None)
    process_event_types = {
        "run.tool_started",
        "run.tool_completed",
        "run.tool_failed",
        "run.skill_started",
        "run.skill_completed",
        "run.skill_failed",
        "run.harness_planned",
        "run.harness_decision",
        "run.harness_fallback",
    }
    if event_type in process_event_types:
        payload = event.payload or {}
        node_name = payload.get("tool_name") or payload.get("skill_name") or payload.get("skill_id")
        if not isinstance(node_name, str) or not node_name.strip():
            node_name = "LangGraph Harness" if event_type.startswith("run.harness") else "tool"
        failed = event_type.endswith("_failed") or event_type == "run.harness_fallback" or payload.get("status") == "failed"
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            if failed:
                summary = "执行失败"
            elif event_type.endswith("_started"):
                summary = "正在执行"
            else:
                summary = "执行完成"
        raw_output = payload.get("raw_output")
        output = raw_output if isinstance(raw_output, dict) else {}
        evidence_refs = payload.get("evidence_refs")
        references = [item for item in evidence_refs if isinstance(item, str) and item] if isinstance(evidence_refs, list) else []
        return ConversationMessage(
            role="assistant",
            content=summary.strip(),
            created_at=getattr(event, "created_at", None) or utcnow(),
            source_event_id=getattr(event, "id", None),
            run_id=getattr(event, "run_id", None),
            process_only=True,
            tool_calls=[
                {
                    "tool_name": node_name.strip(),
                    "status": "failed" if failed else ("running" if event_type.endswith("_started") else "completed"),
                    "reason": summary.strip(),
                    "source": "stage_run",
                    "payload": {
                        "success": not failed,
                        "summary": summary.strip(),
                        "output": output,
                        "evidence_refs": references,
                    },
                }
            ],
        )
    if event_type not in {"run.step", "run.suggestion", "run.waiting_user", "run.completed", "run.failed"}:
        return None
    payload = event.payload or {}
    content = payload.get("summary") or payload.get("description") or payload.get("reason")
    if content is None and event_type == "run.failed":
        content = payload.get("reason")
    if not isinstance(content, str) or not content.strip():
        return None
    return ConversationMessage(
        role="assistant",
        content=content.strip(),
        created_at=getattr(event, "created_at", None) or utcnow(),
        source_event_id=getattr(event, "id", None),
        run_id=getattr(event, "run_id", None),
    )


def create_conversation(stage_id: str, title: str, initial_message: Optional[str]) -> Conversation:
    stage = get_stage(stage_id)
    conversation = Conversation(
        id=f"conversation-{uuid4().hex[:8]}",
        stage_id=stage_id,
        project_id=stage.project_id,
        title=title,
    )
    if initial_message:
        conversation.messages.append(
            ConversationMessage(role="user", content=initial_message)
        )
    save_conversation(conversation)
    stage = get_stage(stage_id)
    create_execution_log(
        project_id=stage.project_id,
        action="conversation.created",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": stage_id, "title": title},
    )
    return conversation


def append_conversation_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    run_id: Optional[str] = None,
    source_event_id: Optional[str] = None,
    action_proposals: Optional[list[dict]] = None,
    harness_warnings: Optional[list[dict]] = None,
    tool_calls: Optional[list[dict]] = None,
) -> ConversationMessage:
    """Append a message to an existing conversation and persist it.

    Returns the newly created :class:`ConversationMessage`.
    Raises ``HTTPException(404)`` if the conversation does not exist, or
    ``HTTPException(409)`` if it is not active.
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot append messages to a {conversation.status} conversation",
        )
    message = ConversationMessage(
        role=role,
        content=content,
        source_event_id=source_event_id,
        run_id=run_id,
        action_proposals=[_action_proposal_summary(item) for item in action_proposals or []],
        harness_warnings=list(harness_warnings or []),
        tool_calls=list(tool_calls or []),
    )
    conversation.messages.append(message)
    conversation.updated_at = utcnow()
    # Use the atomic $push store function for reliability
    add_conversation_message(conversation_id, message)
    return message


def create_file(
    project_id: str,
    filename: str,
    content_type: str,
    content: Optional[str],
    content_base64: Optional[str] = None,
) -> FileArtifact:
    _ = get_project(project_id)
    artifact_id = f"file-{uuid4().hex[:8]}"
    storage_path = _file_storage().save_input_file(project_id, artifact_id, filename, content, content_base64)
    size_bytes = storage_path.stat().st_size
    artifact = FileArtifact(
        id=artifact_id,
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        storage_path=str(storage_path),
        size_bytes=size_bytes,
    )
    save_file_artifact(artifact)
    create_execution_log(
        project_id=project_id,
        action="file.uploaded",
        resource_type="file",
        resource_id=artifact.id,
        details={"filename": filename, "storage_path": artifact.storage_path, "content_type": content_type},
    )
    return artifact


def list_files(project_id: Optional[str] = None) -> list[FileArtifact]:
    return list_file_artifacts(project_id)


PREVIEW_TEXT_LIMIT = 200_000
PREVIEW_BINARY_LIMIT = 8 * 1024 * 1024
TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log"}
DOCUMENT_TEXT_PREVIEW_SUFFIXES = {".doc", ".docx", ".xls", ".xlsx"}
IMAGE_PREVIEW_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic"}
PDF_PREVIEW_SUFFIXES = {".pdf"}


def _guess_content_type(path: Path, fallback: str) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if fallback and fallback != "application/octet-stream":
        return fallback
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    if path.suffix.lower() == ".heic":
        return "image/heic"
    return fallback or "application/octet-stream"


def _extract_file_text(path: Path) -> str:
    try:
        return DocumentProcessor.process_file(path)
    except ValueError as exc:
        if path.suffix.lower() in {".txt", ".md", ".markdown"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        try:
            return DocumentProcessor.parse_text(path)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ImportError as exc:
        if path.suffix.lower() in {".txt", ".md", ".markdown"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        try:
            return DocumentProcessor.parse_text(path)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def get_file_preview(file_id: str) -> dict[str, object]:
    artifact = get_file_artifact(file_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not artifact.storage_path:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File storage path is missing")
    path = Path(artifact.storage_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file not found")

    suffix = path.suffix.lower()
    content_type = _guess_content_type(path, artifact.content_type)

    if suffix in IMAGE_PREVIEW_SUFFIXES or suffix in PDF_PREVIEW_SUFFIXES or content_type.startswith("image/") or content_type == "application/pdf":
        size_bytes = path.stat().st_size
        if size_bytes > PREVIEW_BINARY_LIMIT:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large to preview inline")
        preview_type = "image" if suffix in IMAGE_PREVIEW_SUFFIXES or content_type.startswith("image/") else "pdf"
        return {
            "id": artifact.id,
            "project_id": artifact.project_id,
            "filename": artifact.filename,
            "content_type": content_type,
            "preview_type": preview_type,
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
            "encoding": "base64",
            "size_bytes": size_bytes,
            "truncated": False,
        }

    if suffix in TEXT_PREVIEW_SUFFIXES or content_type.startswith("text/") or suffix in DOCUMENT_TEXT_PREVIEW_SUFFIXES:
        text = _extract_file_text(path)
        truncated = len(text) > PREVIEW_TEXT_LIMIT
        if truncated:
            text = text[:PREVIEW_TEXT_LIMIT]
        return {
            "id": artifact.id,
            "project_id": artifact.project_id,
            "filename": artifact.filename,
            "content_type": content_type,
            "preview_type": "text",
            "content": text,
            "encoding": "utf-8",
            "size_bytes": path.stat().st_size,
            "truncated": truncated,
        }

    raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="File type is not supported for preview")


def parse_file(file_id: str) -> FileArtifact:
    artifact = get_file_artifact(file_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not artifact.storage_path:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File storage path is missing")
    storage_path = Path(artifact.storage_path)
    if not storage_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file not found")
    extracted_text = _extract_file_text(storage_path).strip()
    if not extracted_text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No parseable text found in file")
    summary = generate_document_summary(extracted_text, max_length=500)
    artifact.status = "parsed"
    evidence_id = f"evidence-{uuid4().hex[:8]}"
    attachment_path = _file_storage().save_evidence_attachment(
        artifact.project_id,
        evidence_id,
        artifact.filename,
        summary,
    )
    evidence = EvidenceItem(
        id=evidence_id,
        project_id=artifact.project_id,
        name=f"{artifact.filename} 解析摘要",
        source_type="file",
        source_file_id=artifact.id,
        attachment_path=str(attachment_path),
        snippet=summary,
        status="parsed",
    )
    _file_storage().save_parsed_summary(
        artifact.project_id,
        artifact.id,
        artifact.filename,
        summary,
    )
    save_file_artifact(artifact)
    save_evidence_item(evidence)
    create_execution_log(
        project_id=artifact.project_id,
        action="file.parsed",
        resource_type="file",
        resource_id=artifact.id,
        details={
            "evidence_id": evidence.id,
            "attachment_path": evidence.attachment_path,
            "text_length": len(extracted_text),
            "summary_length": len(summary),
        },
    )
    return artifact


def list_evidence(project_id: Optional[str] = None) -> list[EvidenceItem]:
    return list_evidence_items(project_id)


def create_report(
    project_id: str,
    title: str,
    *,
    stage_result_ids: Optional[list[str]] = None,
    evidence_item_ids: Optional[list[str]] = None,
    enforce_export_gate: bool = True,
    approval_check_passed: bool = True,
    report_status: str = "report_ready",
) -> ReportArtifact:
    _ = get_project(project_id)
    stages = repo_list_stages(project_id)
    stage_results_by_stage = {stage.id: repo_list_stage_results(stage.id) for stage in stages}
    if enforce_export_gate:
        if not stages or any(not results for results in stage_results_by_stage.values()):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="All stages must have at least one stage result before report export")
        if any(results[-1].status != "locked" for results in stage_results_by_stage.values()):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="All stages must be locked before report export")
        if any(item.status == "pending" for stage in stages for item in repo_list_autoresearch_records(stage.id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending autoResearch suggestions must be cleared before report export")

    report_id = f"report-{uuid4().hex[:8]}"
    selected_stage_result_ids = stage_result_ids or []
    selected_evidence_item_ids = evidence_item_ids or []
    if not selected_stage_result_ids:
        selected_stage_result_ids = [item.id for stage in stages for item in stage_results_by_stage[stage.id]]
    if not selected_evidence_item_ids:
        selected_evidence_item_ids = [item.id for item in list_evidence_items(project_id)]
    stage_results = [item for stage in stages for item in stage_results_by_stage[stage.id] if item.id in selected_stage_result_ids]
    evidence_items = [item for item in list_evidence_items(project_id) if item.id in selected_evidence_item_ids]
    recommendation = "建议暂缓（补充论证）"
    if stage_results:
        recommendation = "建议立项" if len(stage_results) >= 1 and len(evidence_items) >= 1 else recommendation
    path = _file_storage().save_report_stub(project_id, report_id, title)
    decision_card_path = _file_storage().save_decision_card(project_id, report_id, title, recommendation)
    evidence_directory_path = _file_storage().save_evidence_directory(project_id, report_id, [item.name for item in evidence_items])
    bundle_export_path = _file_storage().save_export_bundle(
        project_id,
        report_id,
        {
            "report_path": str(path),
            "decision_card_path": str(decision_card_path),
            "evidence_directory_path": str(evidence_directory_path),
            "stage_result_ids": selected_stage_result_ids,
            "evidence_item_ids": selected_evidence_item_ids,
        },
    )
    report = ReportArtifact(
        id=report_id,
        project_id=project_id,
        title=title,
        approval_check_passed=approval_check_passed,
        export_path=str(path),
        decision_card_path=str(decision_card_path),
        evidence_directory_path=str(evidence_directory_path),
        bundle_export_path=str(bundle_export_path),
        stage_result_ids=selected_stage_result_ids,
        evidence_item_ids=selected_evidence_item_ids,
        status=report_status,
    )
    save_report(report)
    create_execution_log(
        project_id=project_id,
        action="report.generated",
        resource_type="report",
        resource_id=report.id,
        details={
            "title": title,
            "approval_check_passed": report.approval_check_passed,
            "export_path": report.export_path,
            "decision_card_path": report.decision_card_path,
            "evidence_directory_path": report.evidence_directory_path,
            "bundle_export_path": report.bundle_export_path,
            "stage_result_ids": report.stage_result_ids,
            "evidence_item_ids": report.evidence_item_ids,
        },
    )
    return report


def get_storage_path(file_id: str) -> Optional[Path]:
    artifact = get_file_artifact(file_id)
    if artifact is None or artifact.storage_path is None:
        return None
    return Path(artifact.storage_path)


def get_report(report_id: str) -> ReportArtifact:
    report = repo_get_report(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


def get_report_content(report_id: str) -> tuple[ReportArtifact, str]:
    report = get_report(report_id)
    if not report.export_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file not found")
    path = Path(report.export_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file not found")
    return report, path.read_text(encoding="utf-8")


def lock_stage(stage_id: str) -> tuple[Stage, str]:
    stage = get_stage(stage_id)
    stage_result = get_latest_stage_result(stage_id)
    if stage_result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage result not found")
    if stage.status == "locked" and stage_result.status == "locked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage already locked")
    pending_records = [item.id for item in repo_list_autoresearch_records(stage_id) if item.status == "pending"]
    if pending_records:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pending autoResearch suggestions must be processed before lock",
        )
    lock_checks = build_stage_lock_checks(stage_id)
    if not lock_checks["ready"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage lock checks not passed")
    stage.status = "locked"
    previous_state = StageResult(
        id=stage_result.id,
        project_id=stage_result.project_id,
        stage_id=stage_result.stage_id,
        version_id=stage_result.version_id,
        base_version_id=stage_result.base_version_id,
        run_id=stage_result.run_id,
        status=stage_result.status,
        input_file_ids=list(stage_result.input_file_ids),
        evidence_item_ids=list(stage_result.evidence_item_ids),
        model_config=dict(stage_result.model_config),
        skill_versions=dict(stage_result.skill_versions),
        autoresearch_record_ids=list(stage_result.autoresearch_record_ids),
        confirmation_ids=list(stage_result.confirmation_ids),
        result_payload=dict(stage_result.result_payload),
        summary=stage_result.summary,
        created_at=stage_result.created_at,
        updated_at=stage_result.updated_at,
        locked_at=stage_result.locked_at,
    )
    stage_result.status = "locked"
    stage_result.locked_at = utcnow()
    stage_result.updated_at = stage_result.locked_at
    save_stage_result(stage_result)
    save_stage(stage)
    diff_summary = build_stage_result_diff(stage_result, previous_state, trigger="stage.locked")
    create_execution_log(
        project_id=stage.project_id,
        action="stage.locked",
        resource_type="stage",
        resource_id=stage.id,
        run_id=stage_result.run_id,
        details={"stage_name": stage.name, "stage_result_id": stage_result.id, "version_id": stage_result.version_id},
    )
    version_log = create_version_log(
        project_id=stage.project_id,
        resource_type="stage",
        resource_id=stage.id,
        change_type="locked",
        summary=f"Stage {stage.name} locked.",
        run_id=stage_result.run_id,
        details={
            "status": "locked",
            "stage_result_id": stage_result.id,
            "version_id": stage_result.version_id,
            "diff_summary": diff_summary,
        },
    )
    return stage, version_log.id


def get_execution_logs(project_id: Optional[str] = None):
    return list_execution_logs(project_id)


def get_version_logs(project_id: Optional[str] = None):
    return list_version_logs(project_id)
