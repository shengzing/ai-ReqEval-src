"""Run lifecycle services."""

from __future__ import annotations

import asyncio
import json
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
from src.apps.api.app.services.project_service import get_conversation, get_project, get_stage
from src.apps.api.app.services.settings_service import (
    get_effective_settings_for_run,
    get_latest_published_settings,
    settings_snapshot,
)
from src.apps.api.app.services.stage_result_service import build_stage_result_diff

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
        payload=payload,
    )


def _persist_event(run: Run, event: RunEvent) -> None:
    run.events.append(event)
    save_run_event(event)


def _append_event(run: Run, event_type: str, payload: dict[str, object]) -> None:
    _persist_event(run, _build_event(run=run, event_type=event_type, payload=payload))


def _set_run_status(run: Run, status_value: str) -> None:
    run.status = status_value
    save_run(run)


def _fail_run(run: Run, *, reason: str, context: dict[str, object]) -> None:
    run.failure_reason = reason
    run.failure_context = context
    _set_run_status(run, "failed")
    _append_event(
        run,
        "run.failed",
        {"reason": reason, "context": context},
    )
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
        model_config=snapshot["model_config"],
        skill_versions=snapshot["skill_versions"],
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

def create_run_sync(*, project_id: str, goal: str, stage_id: Optional[str], conversation_id: Optional[str], config_version_id: Optional[str] = None) -> Run:
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
    _append_event(run, "run.queued", {"stage_id": plan.stage_id, "skill_name": plan.skill_name})
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

        stage_result_id = skill_result.get("stage_result_id", "")
        skill_summary = skill_result.get("summary", "Skill invocation completed.")
        # tool_results from invoke_skill is a list of tool result items, not failures
        # Check harness decision from skill_result for failures
        tool_results_list = skill_result.get("tool_results", [])

        _append_event(
            run,
            "run.skill_completed",
            {
                "skill_name": plan.skill_name,
                "summary": skill_summary,
                "stage_result_id": stage_result_id,
                "source": "skill.invoke",
            },
        )
        # Push the skill_completed event
        for event in run.events[-1:]:
            _push_event_to_subscribers(run.id, {
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            })

        # Determine if tool failures occurred by checking the skill_result
        has_failures = any(
            isinstance(item, dict) and item.get("status") == "failed"
            for item in tool_results_list
        )

        if has_failures:
            _set_run_status(run, "waiting_user")
            _append_event(
                run,
                "run.suggestion",
                {
                    "title": "工具执行存在问题，需人工确认",
                    "description": "部分工具执行失败，请确认是否继续。",
                    "stage_result_id": stage_result_id,
                },
            )
            _append_event(
                run,
                "run.waiting_user",
                {
                    "reason": "Tool failures detected; human review required.",
                    "stage_result_id": stage_result_id,
                },
            )
        else:
            _append_event(
                run,
                "run.suggestion",
                {
                    "title": "确认当前阶段输入",
                    "description": "补齐关键输入后可继续推进下一步。",
                    "stage_result_id": stage_result_id,
                },
            )
            _append_event(
                run,
                "run.waiting_user",
                {
                    "reason": "Stage result requires user confirmation before lock.",
                    "stage_result_id": stage_result_id,
                },
            )

        # Push suggestion/waiting events
        for event in run.events[-2:]:
            _push_event_to_subscribers(run.id, {
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            })

        _set_run_status(run, "completed")
        _append_event(
            run,
            "run.completed",
            {
                "summary": skill_summary,
                "stage_result_id": stage_result_id,
            },
        )
        # Push completed event
        last_event = run.events[-1]
        _push_event_to_subscribers(run.id, {
            "type": last_event.type,
            "payload": last_event.payload,
            "created_at": last_event.created_at.isoformat(),
        })

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
def create_run(*, project_id: str, goal: str, stage_id: Optional[str], conversation_id: Optional[str], config_version_id: Optional[str] = None) -> Run:
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

    run = Run(
        id=f"run-{uuid4().hex[:8]}",
        project_id=project_id,
        stage_id=stage_id,
        conversation_id=conversation_id,
        goal=goal,
        status="created",
        config_version_id=settings.version_id,
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

    context = RunContext(
        run_id=run.id,
        project_id=project_id,
        goal=goal,
        stage_id=stage_id,
        conversation_id=conversation_id,
    )
    plan = resolve_stage(context)
    run.stage_id = plan.stage_id
    resolved_stage = get_stage(plan.stage_id)
    if resolved_stage.status == "locked" and not settings.run_policy.allow_locked_stage_rerun:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run policy disallows new Runs on locked stages",
        )
    try:
        _append_event(run, "run.created", {"run_id": run.id, "project_id": project_id})
        _set_run_status(run, "queued")
        _append_event(run, "run.queued", {"stage_id": plan.stage_id, "skill_name": plan.skill_name})
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

        stage_result_id = skill_result.get("stage_result_id", "")
        skill_summary = skill_result.get("summary", "Skill invocation completed.")
        tool_results_list = skill_result.get("tool_results", [])

        _append_event(
            run,
            "run.skill_completed",
            {
                "skill_name": plan.skill_name,
                "summary": skill_summary,
                "stage_result_id": stage_result_id,
                "source": "skill.invoke",
            },
        )

        # Transition based on harness decision
        stage_result = get_latest_stage_result(plan.stage_id) if plan.stage_id else None

        has_failures = any(
            isinstance(item, dict) and item.get("status") == "failed"
            for item in tool_results_list
        )
        if has_failures:
            # Harness reported tool failures → wait for user
            _set_run_status(run, "waiting_user")
            _append_event(
                run,
                "run.suggestion",
                {
                    "title": "工具执行存在问题，需人工确认",
                    "description": "部分工具执行失败，请确认是否继续。",
                    "stage_result_id": stage_result_id,
                },
            )
            _append_event(
                run,
                "run.waiting_user",
                {
                    "reason": "Tool failures detected; human review required.",
                    "stage_result_id": stage_result_id,
                },
            )
        else:
            _set_run_status(run, "waiting_user")
            _append_event(
                run,
                "run.suggestion",
                {
                    "title": "确认当前阶段输入",
                    "description": "补齐关键输入后可继续推进下一步。",
                    "stage_result_id": stage_result_id,
                },
            )
            _append_event(
                run,
                "run.waiting_user",
                {
                    "reason": "Stage result requires user confirmation before lock.",
                    "stage_result_id": stage_result_id,
                },
            )

        _set_run_status(run, "completed")
        _append_event(
            run,
            "run.completed",
            {
                "summary": skill_summary,
                "stage_result_id": stage_result_id,
            },
        )
        save_run(run)
        create_execution_log(
            project_id=project_id,
            action="run.created",
            resource_type="run",
            resource_id=run.id,
            run_id=run.id,
            details={
                "stage_id": plan.stage_id,
                "conversation_id": conversation_id,
                "goal": goal,
                "stage_result_id": stage_result_id,
                "skill_name": plan.skill_name,
            },
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


def get_run(run_id: str) -> Run:
    run = repo_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
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
