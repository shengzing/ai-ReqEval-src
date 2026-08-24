"""Service boundary for invoking stage conversation harness providers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from hashlib import sha256

from fastapi import HTTPException, status

from src.apps.api.app.agents.conversation_harness.context_builder import (
    ConversationContextBuilder,
)
from src.apps.api.app.agents.conversation_harness.contracts import (
    ConversationHarnessResult,
    normalize_action_proposals,
    normalize_citations,
)
from src.apps.api.app.agents.conversation_harness.registry import (
    get_conversation_harness_provider,
)
from src.apps.api.app.domain.models import ConversationMessage, utcnow
from src.apps.api.app.services import conversation_action_service, log_service, project_service


logger = logging.getLogger(__name__)


def _jsonable(value) -> str:
    """Normalize a value for audit storage so stray datetimes/objects never
    break the execution-log write or the /execution-logs JSON endpoint."""
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _audit_context_summary(request) -> dict:
    """Record reproducibility metadata without retaining prompt content or secrets."""
    history = request.message_history
    return {
        "project_id": request.project_id,
        "stage_id": request.stage_id,
        "conversation_id": request.conversation_id,
        "config_version_id": request.config_version_id,
        "config_hash": ((request.options.get("settings_snapshot") or {}).get("config_hash")),
        "message_history": {
            "count": len(history),
            "digest": sha256(
                json.dumps(history, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "latest_stage_result": {
            "id": (request.latest_stage_result or {}).get("id"),
            "version_id": (request.latest_stage_result or {}).get("version_id"),
        },
        "evidence_ids": [
            item.get("id") for item in request.evidence_summaries if isinstance(item, dict) and item.get("id")
        ],
        "run_event_ids": [
            item.get("id") for item in request.recent_run_events if isinstance(item, dict) and item.get("id")
        ],
        "available_skill_names": [
            item.get("name") for item in request.available_skills if isinstance(item, dict) and item.get("name")
        ],
        "context_limits": {
            "message_count": len(history),
            "evidence_count": len(request.evidence_summaries),
            "run_event_count": len(request.recent_run_events),
        },
    }


@dataclass
class ConversationHarnessInvocation:
    result: ConversationHarnessResult
    assistant_message: ConversationMessage
    action_proposal_ids: list[str] = field(default_factory=list)


def invoke_conversation_harness(
    conversation_id: str,
    user_message: str,
    config_version_id: str | None = None,
) -> ConversationHarnessInvocation:
    logger.info(
        "[conversation_harness] invoke_conversation_harness: START conversation_id=%s user_message_preview=%r",
        conversation_id, user_message[:80],
    )
    request = ConversationContextBuilder().build(
        conversation_id,
        user_message,
        config_version_id=config_version_id,
    )
    version = request.options.get("conversation_harness_version") or None
    logger.info(
        "[conversation_harness] invoke_conversation_harness: resolved conversation_harness_version=%s project_id=%s stage_id=%s",
        version, request.project_id, request.stage_id,
    )
    provider = get_conversation_harness_provider(version)

    try:
        result = provider.run(request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Conversation harness provider failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation harness failed",
        ) from exc

    logger.info(
        "[conversation_harness] invoke_conversation_harness: provider.run DONE version=%s "
        "intent=%s warnings=%s raw=%s assistant_message_preview=%r",
        result.conversation_harness_version, result.intent,
        result.warnings, result.raw, result.assistant_message[:120],
    )
    # Providers may be independently versioned, so enforce the public
    # context/action boundary again at the service persistence boundary.
    result.citations, citation_warnings = normalize_citations(request, result.citations)
    result.action_proposals, proposal_warnings = normalize_action_proposals(
        request, result.action_proposals
    )
    result.warnings.extend(citation_warnings + proposal_warnings)

    action_records: list = []
    if result.action_proposals:
        try:
            action_records = conversation_action_service.save_action_proposals(
                project_id=request.project_id,
                stage_id=request.stage_id,
                conversation_id=conversation_id,
                conversation_harness_version=result.conversation_harness_version,
                proposals=result.action_proposals,
            )
        except Exception:
            # Do not persist a reply that advertises actions the user cannot
            # subsequently confirm.
            logger.exception("Failed to persist conversation action proposals.")
            raise

    try:
        assistant_message = project_service.append_conversation_message(
            conversation_id=conversation_id,
            role="assistant",
            content=result.assistant_message,
            action_proposals=[
                {
                    "id": record.id,
                    "action_type": record.action_type,
                    "title": record.title,
                    "requires_confirmation": record.requires_confirmation,
                    "status": record.status,
                }
                for record in action_records
            ],
            citations=list(result.citations),
            harness_warnings=list(result.warnings),
            tool_calls=list(result.tool_calls),
        )
    except Exception:
        # A proposal without a linked assistant message cannot be discovered
        # in the conversation UI. Mark the records rejected before surfacing
        # the error so users never confirm an orphaned action later.
        for record in action_records:
            record.status = "rejected"
            record.updated_at = utcnow()
            conversation_action_service.store.save_conversation_action_proposal(record)
        raise

    log_service.create_execution_log(
        project_id=request.project_id,
        action="conversation_harness.invoked",
        resource_type="conversation",
        resource_id=conversation_id,
        details=_jsonable({
            "stage_id": request.stage_id,
            "conversation_harness_version": result.conversation_harness_version,
            "runtime_version": result.runtime_version,
            "config_version_id": request.config_version_id,
            "intent": result.intent,
            "citations": result.citations,
            "tool_calls": result.tool_calls,
            "action_proposals": result.action_proposals,
            "action_proposal_ids": [record.id for record in action_records],
            "traces": result.traces,
            "effects": result.effects,
            "raw": result.raw,
            "warnings": result.warnings,
            "context_summary": _audit_context_summary(request),
        }),
    )
    return ConversationHarnessInvocation(
        result=result,
        assistant_message=assistant_message,
        action_proposal_ids=[record.id for record in action_records],
    )
