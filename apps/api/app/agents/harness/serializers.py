"""Serialization helpers for harness state and events."""

from __future__ import annotations

from typing import Any

from src.apps.api.app.agents.harness.state import GRAPH_VERSION, HarnessState
from src.apps.api.app.core.harness_constants import DEFAULT_AGENT_HARNESS_VERSION


def serialize_trace_event(event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"event": event, "payload": dict(payload or {})}


def append_trace(state: HarnessState, event: str, payload: dict[str, Any] | None = None) -> HarnessState:
    traces = list(state.get("traces", []))
    traces.append(serialize_trace_event(event, payload))
    return {**state, "traces": traces}


def serialize_harness_payload(state: HarnessState) -> dict[str, Any]:
    return {
        "harness_version": state.get("harness_version", DEFAULT_AGENT_HARNESS_VERSION),
        "graph_version": state.get("graph_version", GRAPH_VERSION),
        "plan": dict(state.get("plan", {})),
        "decision": dict(state.get("decision", {})),
        "llm_status": dict(state.get("llm_status", {})),
        "traces": list(state.get("traces", [])),
    }
