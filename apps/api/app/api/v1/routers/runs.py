"""Run router with SSE and HITL resume endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from src.apps.api.app.api.v1.schemas.runs import CreateRunRequest, ResumeRunRequest, RunResponse
from src.apps.api.app.services.run_service import (
    create_run_sync,
    get_run,
    stream_sse,
    start_run_background,
    _append_event,
    _set_run_status,
    _push_event_to_subscribers,
    _close_run_queues,
)
from src.apps.api.app.repositories.store import save_run

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

    # Resume the harness graph with human input
    from src.apps.api.app.agents.harness.runner import resume_skill_harness
    from src.apps.api.app.services.run_service import _fail_run

    try:
        resume_result = await asyncio.to_thread(
            resume_skill_harness,
            thread_id=f"thread-{run_id}",
            human_input=request.human_input or {},
        )
        harness_state = dict(resume_result.state)
        decision = harness_state.get("decision", {})

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

        _set_run_status(run, "completed")
        _append_event(run, "run.completed", {
            "summary": decision.get("summary", "Run resumed and completed."),
            "stage_result_id": "",
        })
        # Push completed event
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
