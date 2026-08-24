"""Tool execution node helpers for the LangGraph harness."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from src.apps.api.app.agents.harness.serializers import append_trace
from src.apps.api.app.agents.harness.state import HarnessState
from src.apps.api.app.agents.harness.adapters.tool_adapter import ToolAdapter
from src.apps.api.app.agents.harness.adapters.permission_adapter import PermissionAdapter
from src.apps.api.app.agents.harness.contracts import HarnessRequest, HarnessToolCall
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
        "status": result.status,
        "audit": dict(result.audit),
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
        request = HarnessRequest(
            project_id=str(state.get("project_id", "")),
            stage_id=str(state.get("stage_id", "")),
            run_id=str(state.get("run_id", "")),
            goal=str(state.get("goal", "")),
            stage_name=str(state.get("stage_name", "")),
            skill_name=str(state.get("skill_name", "")),
            allowed_tools=list(state.get("allowed_tools", [])),
            enabled_tools=list(state.get("enabled_tools", [])),
            primary_skill=str(state.get("primary_skill", "")),
            enabled_skills=list(state.get("enabled_skills", [])),
            evidence_items=list(state.get("evidence_items", [])),
            vision_results=list(state.get("vision_results", [])),
            previous_stage_result=prior_stage_result,
        )
        injected_adapter = state.get("tool_adapter")
        adapter = injected_adapter if isinstance(injected_adapter, ToolAdapter) else ToolAdapter(tool_invoker=invoker)
        injected_permission_adapter = state.get("permission_adapter")
        adapted = adapter.invoke(
            request,
            HarnessToolCall(tool_name=tool_name, reason="langgraph.plan"),
            llm_client=llm_client,
            permission_adapter=(
                injected_permission_adapter
                if isinstance(injected_permission_adapter, PermissionAdapter)
                else None
            ),
            provider="langgraph-v1",
        )
        if adapted.status == "skipped_missing_input":
            skips = list(state.get("tool_skips", []))
            skips.append(adapted.to_skip_item())
            return append_trace(
                {**state, "tool_skips": skips},
                "tool.skipped",
                {"tool_name": tool_name, "reason": adapted.status, "audit": adapted.audit},
            )
        if not adapted.success:
            failures = list(state.get("tool_failures", []))
            failures.append(adapted.to_failure_item())
            state = {**state, "tool_failures": failures}
            return append_trace(
                state,
                "tool.failed",
                {"tool_name": tool_name, "detail": adapted.summary, "audit": adapted.audit},
            )
        result = ToolResult(
            name=adapted.name or tool_name,
            summary=adapted.summary,
            raw_output=adapted.raw_output,
            evidence_refs=adapted.evidence_refs,
            warnings=adapted.warnings,
            status=adapted.status,
            audit=adapted.audit,
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
            "audit": adapted.audit,
        },
    )
