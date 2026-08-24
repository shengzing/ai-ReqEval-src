"""Controlled confirmation flow for conversation harness action proposals."""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException, status

from src.apps.api.app.domain.models import (
    ConversationActionProposalRecord,
    ConversationHumanConfirmation,
    Run,
    utcnow,
)
from src.apps.api.app.repositories import store
from src.apps.api.app.services import log_service, run_service


def save_action_proposals(
    *,
    project_id: str,
    stage_id: str,
    conversation_id: str,
    conversation_harness_version: str,
    proposals: list[dict[str, Any]],
) -> list[ConversationActionProposalRecord]:
    records: list[ConversationActionProposalRecord] = []
    for proposal in proposals:
        record = ConversationActionProposalRecord(
            id=f"cap-{uuid4().hex}",
            project_id=project_id,
            stage_id=stage_id,
            conversation_id=conversation_id,
            conversation_harness_version=conversation_harness_version,
            action_type=proposal["action_type"],
            title=proposal.get("title") or proposal["action_type"],
            payload=dict(proposal.get("payload", {})),
            requires_confirmation=proposal.get("requires_confirmation", True),
        )
        store.save_conversation_action_proposal(record)
        log_service.create_execution_log(
            project_id=project_id,
            action="conversation_action_proposal.created",
            resource_type="conversation_action_proposal",
            resource_id=record.id,
            details={
                "conversation_id": conversation_id,
                "stage_id": stage_id,
                "conversation_harness_version": conversation_harness_version,
                "action_type": record.action_type,
                "status": record.status,
            },
        )
        records.append(record)
    return records


def confirm_action_proposal(
    proposal_id: str, *, conversation_id: Optional[str] = None
) -> tuple[ConversationActionProposalRecord, Run | None]:
    proposal = _get_pending_proposal(proposal_id)
    if conversation_id is not None and proposal.conversation_id != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action proposal does not belong to this conversation",
        )
    if proposal.action_type not in {
        "propose_create_run",
        "propose_invoke_skill",
        "propose_request_human_confirmation",
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported action proposal: {proposal.action_type}",
        )
    # Atomically claim the proposal so a double-submit (or a concurrent
    # confirm after read-modify-save) cannot create two Runs. The
    # matched_count==0 branch surfaces as 409 to the client.
    claimed = store.claim_conversation_action_proposal(proposal_id)
    if not claimed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation action proposal is no longer pending",
        )
    try:
        run: Run | None = None
        if proposal.action_type in {"propose_create_run", "propose_invoke_skill"}:
            run_kwargs = {
                "project_id": proposal.project_id,
                "stage_id": proposal.stage_id,
                "conversation_id": proposal.conversation_id,
                "goal": str(proposal.payload.get("goal") or proposal.title),
                "config_version_id": proposal.payload.get("config_version_id"),
            }
            if proposal.action_type == "propose_invoke_skill":
                run_kwargs["requested_skill_name"] = proposal.payload.get("skill_name")
            run = run_service.create_run_sync(
                **run_kwargs,
            )
        else:
            question = str(proposal.payload.get("question") or "").strip()
            if not question:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Human confirmation proposal is missing a question",
                )
            confirmation = ConversationHumanConfirmation(
                id=f"chc-{uuid4().hex}",
                project_id=proposal.project_id,
                stage_id=proposal.stage_id,
                conversation_id=proposal.conversation_id,
                proposal_id=proposal.id,
                question=question,
            )
            store.save_conversation_human_confirmation(confirmation)
            proposal.confirmation_id = confirmation.id
    except Exception:
        # The outer action failed; release the claim so the proposal can be
        # retried instead of being stuck in the accepting state.
        store.release_conversation_action_proposal(proposal_id)
        raise
    proposal.status = "accepted"
    proposal.run_id = run.id if run else None
    proposal.updated_at = utcnow()
    store.save_conversation_action_proposal(proposal)
    log_service.create_execution_log(
        project_id=proposal.project_id,
        action="conversation_action_proposal.accepted",
        resource_type="conversation_action_proposal",
        resource_id=proposal.id,
        run_id=run.id if run else None,
        details={
            "conversation_id": proposal.conversation_id,
            "stage_id": proposal.stage_id,
            "action_type": proposal.action_type,
            "confirmation_id": proposal.confirmation_id,
        },
    )
    return proposal, run


def reject_action_proposal(proposal_id: str, *, conversation_id: Optional[str] = None) -> ConversationActionProposalRecord:
    proposal = _get_pending_proposal(proposal_id)
    if conversation_id is not None and proposal.conversation_id != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action proposal does not belong to this conversation",
        )
    proposal.status = "rejected"
    proposal.updated_at = utcnow()
    store.save_conversation_action_proposal(proposal)
    log_service.create_execution_log(
        project_id=proposal.project_id,
        action="conversation_action_proposal.rejected",
        resource_type="conversation_action_proposal",
        resource_id=proposal.id,
        details={
            "conversation_id": proposal.conversation_id,
            "stage_id": proposal.stage_id,
            "action_type": proposal.action_type,
        },
    )
    return proposal


def _get_pending_proposal(proposal_id: str) -> ConversationActionProposalRecord:
    proposal = store.get_conversation_action_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation action proposal not found",
        )
    if proposal.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conversation action proposal is {proposal.status}",
        )
    return proposal
