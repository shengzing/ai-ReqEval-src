"""Run router with SSE and HITL resume endpoints."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from src.apps.api.app.api.v1.schemas.projects import VersionLogResponse, VisionResultSummaryResponse
from src.apps.api.app.api.v1.schemas.runs import CreateRunRequest, ResumeRunRequest, RunResponse, StageCompletionSnapshotResponse
from src.apps.api.app.services.project_service import (
    build_stage_completion_snapshot,
    delete_run_messages,
)
from src.apps.api.app.services.run_service import (
    _apply_skill_outcome,
    create_run_sync,
    get_run,
    stream_sse,
    start_run_background,
    _append_event,
    _set_run_status,
    _push_event_to_subscribers,
    _close_run_queues,
)
from src.apps.api.app.repositories.store import get_latest_stage_result, save_run, save_stage_result

router = APIRouter()


@router.post("/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def post_run(request: CreateRunRequest) -> RunResponse:
    """Create a new Run.

    Uses the async path: returns immediately with status ``running``,
    then the skill executes in the background while SSE pushes events
    to the frontend in real-time.
    """
    run = create_run_sync(
        project_id=request.project_id,
        goal=request.goal,
        stage_id=request.stage_id,
        conversation_id=request.conversation_id,
    )
    start_run_background(run)
    return RunResponse.model_validate(run, from_attributes=True)


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run_detail(run_id: str) -> RunResponse:
    run = get_run(run_id)
    return RunResponse.model_validate(run, from_attributes=True)


@router.get("/stages/{stage_id}/completion-snapshot", response_model=StageCompletionSnapshotResponse)
def get_stage_completion_snapshot(stage_id: str, run_id: str) -> StageCompletionSnapshotResponse:
    snapshot = build_stage_completion_snapshot(stage_id=stage_id, run_id=run_id)
    version_log = snapshot.get("version_log")
    vision_results = snapshot.get("vision_results", [])
    return StageCompletionSnapshotResponse(
        run=RunResponse.model_validate(snapshot["run"], from_attributes=True).model_dump(),
        stage=snapshot["stage"].__dict__,
        latest_result=(snapshot["latest_result"].__dict__ if snapshot["latest_result"] else None),
        lock_check=snapshot["lock_check"],
        files=[item.__dict__ for item in snapshot["files"]],
        evidence=[item.__dict__ for item in snapshot["evidence"]],
        suggestions=[item.__dict__ for item in snapshot["suggestions"]],
        conversation=(snapshot["conversation"].__dict__ if snapshot["conversation"] else None),
        workspace=snapshot["workspace"],
        version_log=(VersionLogResponse.model_validate(version_log, from_attributes=True).model_dump() if version_log else None),
        vision_results=[VisionResultSummaryResponse.model_validate(item).model_dump() for item in vision_results],
    )


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str) -> StreamingResponse:
    return StreamingResponse(stream_sse(run_id), media_type="text/event-stream")


@router.post("/runs/{run_id}/resume", response_model=RunResponse)
async def resume_run(run_id: str, request: ResumeRunRequest) -> RunResponse:
    """Resume a paused run after human review.

    The run must be in ``waiting_user`` or ``waiting_human`` status.
    The human input is forwarded to the LangGraph graph which continues
    from the ``maybe_interrupt`` node.
    """
    run = get_run(run_id)
    if run.status not in ("waiting_user", "waiting_human"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is not waiting for user input (status={run.status})",
        )

    # Resume only a checkpoint that was actually persisted on this Run.  The
    # old route derived a different id and offered resume for ordinary waiting
    # events, which made the UI claim resumability that did not exist.
    from src.apps.api.app.agents.harness.runner import has_hitl_checkpoint, resume_skill_harness
    from src.apps.api.app.services.run_service import _fail_run

    if run.harness_checkpoint_status != "paused" or not run.harness_thread_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is waiting but has no resumable Harness checkpoint; provide inputs or start a new Run.",
        )
    if not has_hitl_checkpoint(run.harness_thread_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Harness checkpoint is no longer available in this process; start a new Run.",
        )

    # ── Resume consistency gate ─────────────────────────────────────────
    # A paused Run can only be resumed by the project that owns it, for the
    # stage it paused on, against the settings version it pinned at create
    # time, and (optionally) by the resumer it was handed to. These are
    # plain-equality checks, NOT real auth — the project has no identity
    # system; wire real auth before trusting allowed_resumer for decisions.
    if request.project_id is not None and request.project_id != run.project_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume rejected: project_id does not match the paused Run.",
        )
    if request.stage_id is not None and run.stage_id and request.stage_id != run.stage_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume rejected: stage_id does not match the paused Run.",
        )
    # Settings drift during a pause is a hard block: resuming against a newer
    # config version would silently execute with different prompts/models.
    from src.apps.api.app.services.settings_service import get_latest_published_settings
    try:
        latest_published = get_latest_published_settings(run.project_id)
        latest_version_id = latest_published.version_id if latest_published else None
    except Exception:
        latest_version_id = None
    if (
        latest_version_id
        and run.config_version_id
        and latest_version_id != run.config_version_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume rejected: project settings changed during pause; start a new Run against the current config.",
        )
    # allowed_resumer is optional on both sides. If the Run pinned a resumer,
    # the request must either carry no resumer (legacy/anonymous caller —
    # allowed for backward compat) or an exact string match.
    if run.allowed_resumer and request.allowed_resumer and request.allowed_resumer != run.allowed_resumer:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume rejected: allowed_resumer does not match the paused Run.",
        )

    try:
        # Clear the stale ``waiting_user`` placeholder before resuming so the
        # terminal outcome replaces it instead of stacking on top of it.
        if run.conversation_id:
            try:
                delete_run_messages(run.conversation_id, run.id)
            except Exception:  # noqa: BLE001 — message cleanup must not abort resume
                pass

        resume_result = await asyncio.to_thread(
            resume_skill_harness,
            thread_id=run.harness_thread_id,
            human_input=request.human_input or {},
        )
        harness_state = dict(resume_result.state)
        decision = harness_state.get("decision", {})

        # Resume is the only legal route out of a waiting HITL state.
        _set_run_status(run, "running")
        _append_event(run, "run.resumed", {
            "human_input": request.human_input or {},
            "should_continue": decision.get("should_continue", True),
        })
        # Push to SSE subscribers
        last_events = run.events[-2:]
        for event in last_events:
            _push_event_to_subscribers(run.id, {
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            })

        run.harness_checkpoint_status = "resumed"
        if bool(decision.get("requires_human", False)):
            # The checkpoint was already consumed by resume_skill_harness
            # (runner.discard_hitl_checkpoint). Re-entering ``waiting_user``
            # here would advertise a Resume endpoint with no backing
            # checkpoint, violating HCR-P0-04 — so this case fails instead of
            # delegating to ``_apply_skill_outcome`` (which would set
            # ``waiting_user``).
            _fail_run(
                run,
                reason="Harness still requires review after its checkpoint was consumed",
                context={"run_id": run_id, "decision": decision},
            )
        else:
            # Resume success path: apply the resume-only StageResult side
            # effects (confirmation id, valid_result, human_confirmation),
            # then delegate the *terminal* Run transition to the single
            # arbiter ``_apply_skill_outcome``. This makes ``tool_failures``
            # surfaced by the resumed harness state block completion exactly
            # as it does on the sync/async paths, instead of the old
            # unconditional ``completed`` write.
            stage_result = get_latest_stage_result(run.stage_id) if run.stage_id else None
            confirmation_id = None
            if stage_result is not None and stage_result.run_id == run.id:
                confirmation_id = f"hitl-confirmation-{uuid4().hex[:8]}"
                stage_result.confirmation_ids = list(stage_result.confirmation_ids) + [confirmation_id]
                stage_result.valid_result = True
                stage_result.invalid_reason = None
                stage_result.updated_at = run.created_at
                stage_result.result_payload["human_confirmation"] = {
                    "id": confirmation_id,
                    "run_id": run.id,
                    "approved": True,
                    "input": request.human_input or {},
                    "decision": decision,
                }
                harness_payload = stage_result.result_payload.get("harness")
                if isinstance(harness_payload, dict):
                    harness_payload["decision"] = dict(decision)
                save_stage_result(stage_result)

            plan = SimpleNamespace(
                stage_id=run.stage_id,
                skill_name=run.skill_name or run.primary_skill or run.requested_skill_name or "",
            )
            skill_result = {
                "decision": decision,
                "tool_failures": list(harness_state.get("tool_failures", [])),
                "tool_results": list(harness_state.get("tool_result_items", [])),
                "execution_status": "completed",
                "summary": decision.get("summary", "Run resumed and completed."),
            }
            _apply_skill_outcome(
                run,
                plan,
                skill_result=skill_result,
                stage_result_id=(stage_result.id if stage_result is not None else ""),
                skill_summary=skill_result["summary"],
                extra_completed_payload=(
                    {"confirmation_id": confirmation_id}
                    if confirmation_id is not None
                    else None
                ),
            )
        last_event = run.events[-1]
        _push_event_to_subscribers(run.id, {
            "type": last_event.type,
            "payload": last_event.payload,
            "created_at": last_event.created_at.isoformat(),
        })
        _close_run_queues(run.id)
        save_run(run)
    except Exception as exc:
        _fail_run(run, reason=str(exc), context={"run_id": run_id})
        save_run(run)
        _close_run_queues(run.id)

    return RunResponse.model_validate(run, from_attributes=True)
