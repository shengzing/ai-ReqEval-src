"""Tool execution node helpers for the LangGraph harness."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from src.apps.api.app.agents.harness.serializers import append_trace
from src.apps.api.app.agents.harness.state import HarnessState
from src.apps.api.app.agents.tools.registry import ToolResult
from src.apps.api.app.services.tool_service import invoke_tool


ToolInvoker = Callable[..., ToolResult]


def tool_result_to_item(result: ToolResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "summary": result.summary,
        "raw_output": result.raw_output,
        "evidence_refs": list(result.evidence_refs),
        "warnings": list(result.warnings),
    }


def run_tool_node(
    state: HarnessState,
    tool_name: str,
    *,
    tool_invoker: ToolInvoker | None = None,
    fail_fast: bool = False,
    llm_client: Any = None,
) -> HarnessState:
    invoker = tool_invoker or invoke_tool
    planned_tools = list(state.get("plan", {}).get("tool_names", []))
    if tool_name not in planned_tools:
        state = append_trace(state, "tool.skipped", {"tool_name": tool_name, "reason": "not_in_plan"})
        return state

    state = append_trace(state, "tool.started", {"tool_name": tool_name})
    try:
        prior_stage_result = dict(state.get("previous_stage_result") or {})
        prior_stage_result.update(dict(state.get("tool_results", {})))
        result = invoker(
            tool_name=tool_name,
            goal=state.get("goal", ""),
            stage_name=state.get("stage_name", ""),
            evidence_items=state.get("evidence_items", []),
            vision_results=state.get("vision_results", []),
            previous_stage_result=prior_stage_result,
            llm_client=llm_client,
        )
    except HTTPException as exc:
        failures = list(state.get("tool_failures", []))
        failures.append({"tool_name": tool_name, "detail": str(exc.detail)})
        state = {**state, "tool_failures": failures}
        state = append_trace(state, "tool.failed", {"tool_name": tool_name, "detail": exc.detail})
        if fail_fast:
            return {**state, "decision": {"should_continue": False, "source": "tool_failure"}}
        return state
    except Exception as exc:
        failures = list(state.get("tool_failures", []))
        failures.append({"tool_name": tool_name, "detail": str(exc)})
        state = {**state, "tool_failures": failures}
        state = append_trace(state, "tool.failed", {"tool_name": tool_name, "detail": str(exc)})
        if fail_fast:
            return {**state, "decision": {"should_continue": False, "source": "tool_failure"}}
        return state

    tool_results = dict(state.get("tool_results", {}))
    tool_results[tool_name] = result.raw_output
    tool_result_items = list(state.get("tool_result_items", []))
    tool_result_items.append(tool_result_to_item(result))
    state = {
        **state,
        "tool_results": tool_results,
        "tool_result_items": tool_result_items,
    }
    return append_trace(
        state,
        "tool.completed",
        {
            "tool_name": tool_name,
            "summary": result.summary,
            "evidence_ref_count": len(result.evidence_refs),
        },
    )
