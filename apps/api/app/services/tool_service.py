"""Fixed tool invocation services."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status

from src.apps.api.app.agents.tools.registry import TOOL_HANDLERS, ToolResult


def invoke_tool(
    *,
    tool_name: str,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
    llm_client: Any = None,
) -> ToolResult:
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    # Not every tool handler accepts llm_client (only document_parse and
    # risk_identify currently opt in). Filter by the handler's signature so
    # we don't break other tools.
    import inspect

    handler_params = inspect.signature(handler).parameters
    kwargs: dict[str, Any] = {
        "goal": goal,
        "stage_name": stage_name,
        "evidence_items": evidence_items,
        "vision_results": vision_results,
        "previous_stage_result": previous_stage_result,
    }
    if "llm_client" in handler_params:
        kwargs["llm_client"] = llm_client
    return handler(**kwargs)


def list_tool_names() -> list[str]:
    return sorted(TOOL_HANDLERS.keys())
