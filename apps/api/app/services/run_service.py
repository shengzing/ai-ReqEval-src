"""Run lifecycle services."""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import uuid4
from typing import Optional

from fastapi import HTTPException, status

from src.apps.api.app.agents.deepagent.models import RunContext
from src.apps.api.app.agents.deepagent.orchestrator import resolve_stage
from src.apps.api.app.domain.models import Run, RunEvent, StageResult, utcnow
from src.apps.api.app.repositories.store import (
    get_latest_stage_result,
    get_run as repo_get_run,
    list_run_events as repo_list_run_events,
    save_run,
    save_run_event,
    save_stage_result,
)
from src.apps.api.app.services.log_service import create_execution_log, create_version_log
from src.apps.api.app.services.project_service import (
    delete_run_messages,
    get_conversation,
    get_project,
    get_stage,
    upsert_run_outcome_message,
)
from src.apps.api.app.services.settings_service import (
    get_effective_settings_for_run,
    get_latest_published_settings,
    settings_snapshot,
)
from src.apps.api.app.services.stage_result_service import build_stage_result_diff
from src.apps.api.app.security.sanitization import redact_value

# ---------------------------------------------------------------------------
# Per-run event queues for real-time SSE push
# ---------------------------------------------------------------------------
# Each run_id maps to a list of subscriber queues.  Background execution
# pushes RunEvent dicts into every subscriber queue; SSE endpoints consume
# from their own queue.  A sentinel None marks end-of-stream.
# ---------------------------------------------------------------------------
_run_queues: dict[str, list[asyncio.Queue]] = {}

# Sentinel value pushed to queues to signal end-of-stream
_SSE_SENTINEL = None


# Lifecycle transitions are deliberately narrow.  In particular, a Run that
# has paused for inputs or human review may not be silently overwritten as
# ``completed`` by a finally block or a duplicate event producer.
_RUN_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "created": {"queued", "waiting_inputs", "failed"},
    "queued": {"running", "waiting_inputs", "failed"},
    "running": {"waiting_inputs", "waiting_user", "waiting_human", "completed", "failed"},
    "waiting_inputs": {"running", "failed"},
    "waiting_user": {"running", "failed"},
    "waiting_human": {"running", "failed"},
    "completed": set(),
    "failed": set(),
}


def _get_or_create_queues(run_id: str) -> list[asyncio.Queue]:
    """Return the subscriber queue list for *run_id*, creating if needed."""
    if run_id not in _run_queues:
        _run_queues[run_id] = []
    return _run_queues[run_id]


def subscribe_to_run(run_id: str) -> asyncio.Queue:
    """Create a new subscriber queue for *run_id* and return it."""
    queues = _get_or_create_queues(run_id)
    q: asyncio.Queue = asyncio.Queue()
    queues.append(q)
    return q


def unsubscribe_from_run(run_id: str, queue: asyncio.Queue) -> None:
    """Remove a subscriber queue.  Cleans up the run entry if empty."""
    queues = _run_queues.get(run_id, [])
    if queue in queues:
        queues.remove(queue)
    if not queues and run_id in _run_queues:
        del _run_queues[run_id]


def _push_event_to_subscribers(run_id: str, event_payload: dict) -> None:
    """Push a serialised event dict to every subscriber queue (fire-and-forget)."""
    for q in _run_queues.get(run_id, []):
        # Use put_nowait so we never block the background task on a slow consumer
        try:
            q.put_nowait(event_payload)
        except asyncio.QueueFull:
            pass  # drop rather than block


def _close_run_queues(run_id: str) -> None:
    """Push the sentinel to every subscriber and clean up."""
    for q in _run_queues.pop(run_id, []):
        try:
            q.put_nowait(_SSE_SENTINEL)
        except asyncio.QueueFull:
            pass


def _build_event(
    *,
    run: Run,
    event_type: str,
    payload: dict[str, object],
) -> RunEvent:
    return RunEvent(
        id=f"runevt-{uuid4().hex[:8]}",
        run_id=run.id,
        project_id=run.project_id,
        stage_id=run.stage_id,
        conversation_id=run.conversation_id,
        type=event_type,
        payload=redact_value(payload),
    )


def _persist_event(run: Run, event: RunEvent) -> None:
    run.events.append(event)
    save_run_event(event)


def _append_event(run: Run, event_type: str, payload: dict[str, object]) -> None:
    _persist_event(run, _build_event(run=run, event_type=event_type, payload=payload))
    # Surface the HITL gate as a visible assistant message in the Run's own
    # conversation, so a button-triggered Run reads as a self-contained thread
    # (execution timeline → completion note) without a user bubble.
    if event_type == "run.waiting_user":
        _write_run_message(run, "阶段执行已暂停，等待人工确认。请在下方选择“确认并继续”或“拒绝并停止”。")


def _write_run_message(run: Run, content: str) -> None:
    """Best-effort: persist a visible assistant message into the Run's conversation.

    Message writes must never break the Run lifecycle — a deleted/missing
    conversation or a storage error is logged and swallowed. The upsert keeps
    exactly one message per ``run_id``.
    """
    if not run.conversation_id or not run.id or not content:
        return
    try:
        upsert_run_outcome_message(
            run.conversation_id,
            run_id=run.id,
            content=content,
        )
    except Exception as exc:  # noqa: BLE001 — audit surface, not a Run contract
        logging.getLogger(__name__).warning(
            "Failed to write run message for run %s: %s", run.id, exc
        )


def _set_run_status(run: Run, status_value: str, *, waiting_reason: str | None = None) -> None:
    if status_value != run.status:
        allowed_targets = _RUN_STATUS_TRANSITIONS.get(run.status)
        if allowed_targets is None or status_value not in allowed_targets:
            raise RuntimeError(
                "Invalid Run status transition: {0} -> {1}".format(run.status, status_value)
            )
    run.status = status_value
    run.waiting_reason = waiting_reason if status_value.startswith("waiting_") else None
    save_run(run)


def mark_run_waiting_inputs(run: Run, *, reason: str) -> None:
    """Persist the input gate outcome without pretending the skill completed."""
    _set_run_status(run, "waiting_inputs", waiting_reason=reason)


def _refresh_run_after_skill(run: Run) -> Run:
    """Reload fields that the synchronous Skill worker persisted.

    ``invoke_skill`` intentionally reloads the Run from the repository before
    it appends audit events or pauses for input.  The caller, however, still
    owns the older in-memory object created before the worker thread started.
    Reusing that stale object would replace the newly persisted
    ``waiting_inputs`` state with ``running``.  Always continue lifecycle
    arbitration from the repository copy after the Skill returns.
    """
    persisted = repo_get_run(run.id)
    return persisted if persisted is not None else run


def _fail_run(run: Run, *, reason: str, context: dict[str, object]) -> None:
    run.failure_reason = reason
    run.failure_context = context
    _set_run_status(run, "failed")
    _append_event(
        run,
        "run.failed",
        {
            "reason": reason,
            "context": context,
            "skill_name": run.skill_name,
            "config_version_id": run.config_version_id,
        },
    )
    _write_run_message(run, "阶段执行失败，请查看执行过程。")
    create_execution_log(
        project_id=run.project_id,
        action="run.failed",
        resource_type="run",
        resource_id=run.id,
        run_id=run.id,
        details={"reason": reason, "context": context},
    )


def append_run_event(run: Run, event_type: str, payload: dict[str, object]) -> None:
    """Append a run event to the Run and push it to SSE subscriber queues."""
    event = _build_event(run=run, event_type=event_type, payload=payload)
    _persist_event(run, event)
    save_run(run)
    # Push to real-time SSE subscribers
    sse_payload = {
        "type": event.type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }
    _push_event_to_subscribers(run.id, sse_payload)


def _create_stage_result(run: Run) -> StageResult:
    latest = get_latest_stage_result(run.stage_id) if run.stage_id else None
    snapshot = settings_snapshot(
        run.project_id,
        run.stage_id,
        config_version_id=run.config_version_id,
    )
    stage_result = StageResult(
        id=f"stage-result-{uuid4().hex[:8]}",
        project_id=run.project_id,
        stage_id=run.stage_id or "",
        version_id=f"sv-{uuid4().hex[:8]}",
        base_version_id=latest.version_id if latest else None,
        run_id=run.id,
        result_payload={
            "goal": run.goal,
            "conversation_id": run.conversation_id,
            "event_types": [event.type for event in run.events],
            "config_version_id": run.config_version_id,
        },
        summary="Draft stage result created from run execution.",
        valid_result=False,
        invalid_reason="awaiting_skill_execution",
        model_config=snapshot["model_config"],
        skill_versions=snapshot["skill_versions"],
        skill_name=run.skill_name,
        config_version_id=run.config_version_id,
    )
    save_stage_result(stage_result)
    diff_summary = build_stage_result_diff(stage_result, latest, trigger="run.created")
    create_version_log(
        project_id=run.project_id,
        resource_type="stage_result",
        resource_id=stage_result.id,
        change_type="created",
        summary="Draft stage result created.",
        run_id=run.id,
        details={
            "stage_id": run.stage_id,
            "version_id": stage_result.version_id,
            "base_version_id": stage_result.base_version_id,
            "diff_summary": diff_summary,
            "config_version_id": run.config_version_id,
        },
    )
    return stage_result

def create_run_sync(
    *,
    project_id: str,
    goal: str,
    stage_id: Optional[str],
    conversation_id: Optional[str],
    config_version_id: Optional[str] = None,
    requested_skill_name: Optional[str] = None,
) -> Run:
    """Create a Run and persist its initial lifecycle events.

    The caller must schedule :func:`start_run_background` after this returns.
    Keeping creation and scheduling explicit lets both the normal Run route
    and a confirmed conversation proposal use the same execution path.

    ``config_version_id`` pins the Run to a specific published settings version
    (used by conversation action proposal confirm to keep audit consistency).
    When None, falls back to the latest published settings.
    """
    _ = get_project(project_id)
    if stage_id is not None:
        stage = get_stage(stage_id)
        if stage.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage does not belong to project")
    else:
        stage = None

    if conversation_id is not None:
        conversation = get_conversation(conversation_id)
        if stage is None:
            stage_id = conversation.stage_id
            stage = get_stage(stage_id)
            if stage.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation does not belong to project")
        elif conversation.stage_id != stage.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation does not belong to stage")

    settings = get_effective_settings_for_run(
        project_id, stage_id=stage_id, config_version_id=config_version_id,
    )

    if stage is not None and stage.status == "locked" and not settings.run_policy.allow_locked_stage_rerun:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run policy disallows new Runs on locked stages",
        )

    context = RunContext(
        run_id="",  # placeholder – will be set after run creation
        project_id=project_id,
        goal=goal,
        stage_id=stage_id,
        conversation_id=conversation_id,
        requested_skill_name=requested_skill_name,
        config_version_id=settings.version_id,
    )
    plan = resolve_stage(context)

    resolved_stage = get_stage(plan.stage_id)
    if resolved_stage.status == "locked" and not settings.run_policy.allow_locked_stage_rerun:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run policy disallows new Runs on locked stages",
        )

    run = Run(
        id=f"run-{uuid4().hex[:8]}",
        project_id=project_id,
        stage_id=plan.stage_id,
        conversation_id=conversation_id,
        goal=goal,
        status="created",
        config_version_id=settings.version_id,
        skill_name=plan.skill_name,
        primary_skill=getattr(plan, "primary_skill", None),
        enabled_skills=list(getattr(plan, "enabled_skills", None) or []) or None,
        requested_skill_name=requested_skill_name,
        routing_source=getattr(plan, "routing_source", None),
    )
    save_run(run)
    create_execution_log(
        project_id=project_id,
        action="run.config_snapshot",
        resource_type="run",
        resource_id=run.id,
        run_id=run.id,
        details={"config_version_id": settings.version_id, "config_hash": settings.config_hash},
    )

    # Emit initial events synchronously
    _append_event(run, "run.created", {"run_id": run.id, "project_id": project_id})
    _set_run_status(run, "queued")
    _append_event(
        run,
        "run.queued",
        {
            "stage_id": plan.stage_id,
            "skill_name": plan.skill_name,
            "config_version_id": run.config_version_id,
        },
    )
    _set_run_status(run, "running")
    _append_event(run, "run.running", {"goal": goal, "stage_id": plan.stage_id})
    _append_event(
        run,
        "run.step",
        {
            "summary": "DeepAgent selected the execution stage.",
            "reasoning": plan.reasoning,
            "stage_name": plan.stage_name,
        },
    )
    # Push initial events to SSE subscribers
    for event in run.events:
        _push_event_to_subscribers(run.id, {
            "type": event.type,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        })

    return run


def start_run_background(run: Run) -> asyncio.Task:
    """Schedule a newly-created Run on the current API event loop.

    ``create_run_sync`` deliberately has no event-loop dependency, so it can
    also be used by synchronous services and tests. API routes call this
    helper exactly once after successful persistence.
    """
    context = RunContext(
        run_id=run.id,
        project_id=run.project_id,
        goal=run.goal,
        stage_id=run.stage_id,
        conversation_id=run.conversation_id,
        requested_skill_name=run.skill_name,
        config_version_id=run.config_version_id,
    )
    plan = resolve_stage(context)
    return asyncio.get_running_loop().create_task(_execute_run_background(run, plan))


async def _execute_run_background(run: Run, plan) -> None:
    """Background coroutine: invokes the real skill and transitions the run to completion."""
    try:
        # Run the synchronous invoke_skill in a thread to avoid blocking the event loop
        from src.apps.api.app.services.skill_service import invoke_skill

        skill_result = await asyncio.to_thread(
            invoke_skill,
            skill_name=plan.skill_name,
            project_id=run.project_id,
            stage_id=plan.stage_id,
            run_id=run.id,
            goal=run.goal,
        )

        run = _refresh_run_after_skill(run)
        stage_result_id = skill_result.get("stage_result_id", "")
        skill_summary = skill_result.get("summary", "Skill invocation completed.")
        _apply_skill_outcome(
            run,
            plan,
            skill_result=skill_result,
            stage_result_id=stage_result_id,
            skill_summary=skill_summary,
        )
    except HTTPException as exc:
        # Propagate HTTP errors as run failures
        _fail_run(
            run,
            reason=exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            context={"goal": run.goal, "stage_id": run.stage_id},
        )
        save_run(run)
        # Push failure event
        for event in run.events[-1:]:
            _push_event_to_subscribers(run.id, {
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            })
    except Exception as exc:
        _fail_run(
            run,
            reason=str(exc),
            context={"goal": run.goal, "stage_id": run.stage_id, "conversation_id": run.conversation_id},
        )
        save_run(run)
        for event in run.events[-1:]:
            _push_event_to_subscribers(run.id, {
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            })
    finally:
        # Signal SSE subscribers that the stream is complete
        _close_run_queues(run.id)


# Backward-compatible sync create_run (used by non-async callers / old tests)
def create_run(
    *,
    project_id: str,
    goal: str,
    stage_id: Optional[str],
    conversation_id: Optional[str],
    config_version_id: Optional[str] = None,
    requested_skill_name: Optional[str] = None,
) -> Run:
    """Synchronous create_run: creates the Run and executes the skill inline.

    This preserves backward compatibility with existing callers and tests
    that do not use the async path. ``config_version_id`` pins the Run to a
    specific published settings version when provided.
    """
    _ = get_project(project_id)
    if stage_id is not None:
        stage = get_stage(stage_id)
        if stage.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage does not belong to project")
    else:
        stage = None

    if conversation_id is not None:
        conversation = get_conversation(conversation_id)
        if stage is None:
            stage_id = conversation.stage_id
            stage = get_stage(stage_id)
            if stage.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation does not belong to project")
        elif conversation.stage_id != stage.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation does not belong to stage")

    settings = get_effective_settings_for_run(
        project_id, stage_id=stage_id, config_version_id=config_version_id,
    )

    if stage is not None and stage.status == "locked" and not settings.run_policy.allow_locked_stage_rerun:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run policy disallows new Runs on locked stages",
        )

    context = RunContext(
        run_id="",
        project_id=project_id,
        goal=goal,
        stage_id=stage_id,
        conversation_id=conversation_id,
        requested_skill_name=requested_skill_name,
        config_version_id=settings.version_id,
    )
    plan = resolve_stage(context)
    resolved_stage = get_stage(plan.stage_id)
    if resolved_stage.status == "locked" and not settings.run_policy.allow_locked_stage_rerun:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run policy disallows new Runs on locked stages",
        )
    run = Run(
        id=f"run-{uuid4().hex[:8]}",
        project_id=project_id,
        stage_id=plan.stage_id,
        conversation_id=conversation_id,
        goal=goal,
        status="created",
        config_version_id=settings.version_id,
        skill_name=plan.skill_name,
        primary_skill=getattr(plan, "primary_skill", None),
        enabled_skills=list(getattr(plan, "enabled_skills", None) or []) or None,
        requested_skill_name=requested_skill_name,
        routing_source=getattr(plan, "routing_source", None),
    )
    save_run(run)
    create_execution_log(
        project_id=project_id,
        action="run.config_snapshot",
        resource_type="run",
        resource_id=run.id,
        run_id=run.id,
        details={"config_version_id": settings.version_id, "config_hash": settings.config_hash},
    )
    try:
        _append_event(run, "run.created", {"run_id": run.id, "project_id": project_id})
        _set_run_status(run, "queued")
        _append_event(
            run,
            "run.queued",
            {
                "stage_id": plan.stage_id,
                "skill_name": plan.skill_name,
                "config_version_id": run.config_version_id,
            },
        )
        _set_run_status(run, "running")
        _append_event(run, "run.running", {"goal": goal, "stage_id": plan.stage_id})
        _append_event(
            run,
            "run.step",
            {
                "summary": "DeepAgent selected the execution stage.",
                "reasoning": plan.reasoning,
                "stage_name": plan.stage_name,
            },
        )

        # Delegate to real skill execution (harness + tools)
        # Lazy import to avoid circular dependency (skill_service imports from run_service)
        from src.apps.api.app.services.skill_service import invoke_skill

        skill_result = invoke_skill(
            skill_name=plan.skill_name,
            project_id=project_id,
            stage_id=plan.stage_id,
            run_id=run.id,
            goal=goal,
        )

        run = _refresh_run_after_skill(run)
        stage_result_id = skill_result.get("stage_result_id", "")
        skill_summary = skill_result.get("summary", "Skill invocation completed.")
        _apply_skill_outcome(
            run,
            plan,
            skill_result=skill_result,
            stage_result_id=stage_result_id,
            skill_summary=skill_summary,
        )
    except HTTPException:
        # Re-raise HTTP exceptions from invoke_skill (e.g. precondition failures)
        raise
    except Exception as exc:
        _fail_run(
            run,
            reason=str(exc),
            context={"goal": goal, "stage_id": run.stage_id, "conversation_id": conversation_id},
        )
        save_run(run)
    return run


def _apply_skill_outcome(
    run: Run,
    plan,
    *,
    skill_result: dict,
    stage_result_id: str,
    skill_summary: str,
    extra_completed_payload: dict[str, object] | None = None,
) -> None:
    """Apply exactly one terminal or waiting outcome from a skill result.

    ``invoke_skill`` is the source of tool execution; this function is the
    sole source of Run lifecycle completion.  Keeping the policy here avoids
    a provider event saying "waiting" while a later unconditional write says
    "completed".

    ``extra_completed_payload`` lets a caller that already produced a
    confirmation (the HITL resume route) attach its id to the
    ``run.completed`` event without re-implementing the terminal policy.
    It is merged on top of the standard completed payload; existing callers
    leave it as ``None`` so their behaviour is unchanged.
    """
    execution_status = str(skill_result.get("execution_status", ""))
    decision = dict(skill_result.get("decision") or {})
    tool_failures = list(skill_result.get("tool_failures") or [])
    tool_results = list(skill_result.get("tool_results") or [])
    has_failures = bool(tool_failures) or any(
        isinstance(item, dict) and item.get("status") == "failed"
        for item in tool_results
    )

    if execution_status == "waiting_inputs":
        # The Skill normally records the detailed gate event before returning.
        # Keep this branch as the lifecycle arbiter for providers that only
        # return a waiting outcome, while never overwriting a persisted wait
        # with the caller's older ``running`` object.
        if run.status != "waiting_inputs":
            waiting_reason = str(
                skill_result.get("waiting_reason")
                or next(
                    (
                        item.get("code")
                        for item in skill_result.get("warnings", [])
                        if isinstance(item, dict) and item.get("code")
                    ),
                    "missing_input",
                )
            )
            mark_run_waiting_inputs(run, reason=waiting_reason)
        _write_run_message(
            run,
            "阶段执行暂停：缺少可用输入材料，请在“阶段输入”中补充并确认相关材料后重新运行。",
        )
        save_run(run)
        return

    if has_failures or execution_status == "failed":
        _fail_run(
            run,
            reason="Tool execution failed" if has_failures else "Skill execution was not accepted",
            context={
                "stage_id": plan.stage_id,
                "stage_result_id": stage_result_id,
                "tool_failures": tool_failures,
            },
        )
        return

    if bool(decision.get("requires_human", False)):
        reason = str(decision.get("summary") or "Harness requires human review before completion.")
        _set_run_status(run, "waiting_user", waiting_reason=reason)
        _append_event(
            run,
            "run.waiting_user",
            {
                "reason": reason,
                "stage_result_id": stage_result_id,
                "decision": decision,
            },
        )
        # The visible placeholder is written by _append_event's waiting_user hook.
        save_run(run)
        return

    if decision and not bool(decision.get("should_continue", False)):
        _fail_run(
            run,
            reason="Harness decision did not allow completion",
            context={"stage_id": plan.stage_id, "stage_result_id": stage_result_id, "decision": decision},
        )
        return

    _set_run_status(run, "completed")
    completed_payload = {
        "summary": skill_summary,
        "stage_result_id": stage_result_id,
        "decision": decision,
    }
    if extra_completed_payload:
        completed_payload = {**completed_payload, **dict(extra_completed_payload)}
    # Persist the visible completion note before emitting the terminal event,
    # so a client fetching the completion snapshot right after the event always
    # sees the message.
    _write_run_message(run, "阶段执行完成。{0}".format(skill_summary))
    _append_event(run, "run.completed", completed_payload)
    save_run(run)
    create_execution_log(
        project_id=run.project_id,
        action="run.completed",
        resource_type="run",
        resource_id=run.id,
        run_id=run.id,
        details={
            "stage_id": plan.stage_id,
            "goal": run.goal,
            "stage_result_id": stage_result_id,
            "skill_name": plan.skill_name,
        },
    )


def get_run(run_id: str) -> Run:
    run = repo_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    # Self-heal Runs written by the former stale-object race: the append-only
    # event stream is authoritative when it already contains a waiting-input
    # outcome but the Run document still says created/queued/running.
    if run.status in {"created", "queued", "running"}:
        waiting_event = next(
            (
                event
                for event in reversed(repo_list_run_events(run.id))
                if event.type == "run.waiting_inputs"
            ),
            None,
        )
        if waiting_event is not None:
            reason = str((waiting_event.payload or {}).get("reason") or "missing_input")
            mark_run_waiting_inputs(run, reason=reason)
    if run.harness_checkpoint_status == "paused" and run.harness_thread_id:
        # The durable SqliteSaver survives restarts, so a missing checkpoint
        # here means the run was already resumed (or never paused on disk), not
        # merely "lost to a process restart". Reconcile the persisted marker so
        # clients are never offered a fake Resume action.
        from src.apps.api.app.agents.harness.runner import has_hitl_checkpoint

        if not has_hitl_checkpoint(run.harness_thread_id):
            run.harness_checkpoint_status = "unavailable"
            run.waiting_reason = (
                "Harness checkpoint is no longer available; the run was already resumed or started fresh."
            )
            save_run(run)
    return run


def encode_sse(run_id: str) -> str:
    _ = get_run(run_id)
    events = repo_list_run_events(run_id)
    frames: list[str] = []
    for event in events:
        payload = {
            "type": event.type,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }
        frames.append(f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n")
    return "\n".join(frames) + "\n"


async def stream_sse(run_id: str):
    """Stream SSE events for a run.

    If a subscriber queue exists (created by ``create_run_sync``),
    events are consumed in real-time.  Otherwise, fall back to
    replaying persisted events from MongoDB.
    """
    run = get_run(run_id)

    # Try real-time queue first
    queue = None
    if run_id in _run_queues:
        queue = subscribe_to_run(run_id)

    if queue is not None:
        # Real-time path: replay any events that arrived before subscription,
        # then consume from the queue.
        existing_events = repo_list_run_events(run_id)
        seen_ids: set[str] = set()
        for event in existing_events:
            seen_ids.add(event.id)
            payload = {
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
            yield f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)

        # Consume from the queue until sentinel
        while True:
            item = await queue.get()
            if item is _SSE_SENTINEL:
                break
            # Dedup against already-yielded events
            event_type = item.get("type", "")
            yield f"event: {event_type}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)

        # Cleanup
        unsubscribe_from_run(run_id, queue)

        # Yield any events that may have arrived after queue closed
        final_events = repo_list_run_events(run_id)
        for event in final_events:
            if event.id not in seen_ids:
                seen_ids.add(event.id)
                payload = {
                    "type": event.type,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
                yield f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
    else:
        # Fallback: replay persisted events (old sync path)
        events = repo_list_run_events(run_id)
        for event in events:
            payload = {
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
            yield f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)
