"""Read-only context tools for conversation harness runtimes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from src.apps.api.app.agents.conversation_harness.contracts import (
    ConversationHarnessRequest,
    ConversationToolResult,
)


class ConversationContextToolAdapter:
    def __init__(self, request: ConversationHarnessRequest) -> None:
        self.request = request
        self.tool_calls: list[dict[str, Any]] = []
        self._tools: dict[str, Callable[[], dict[str, Any]]] = {
            "read_project_context": lambda: deepcopy(self.request.project_context),
            "read_stage_context": lambda: deepcopy(self.request.stage_context),
            "read_latest_stage_result": self._read_latest_stage_result,
            "list_evidence_summaries": lambda: {"items": deepcopy(self.request.evidence_summaries)},
            "list_recent_run_events": lambda: {"items": deepcopy(self.request.recent_run_events)},
            "list_available_skills": lambda: {"items": deepcopy(self.request.available_skills)},
        }

    def call(self, tool_name: str, reason: str = "") -> ConversationToolResult:
        call_record: dict[str, Any] = {"tool_name": tool_name, "reason": reason, "payload": {}}
        self.tool_calls.append(call_record)
        tool = self._tools.get(tool_name)
        if tool is None:
            result = ConversationToolResult(
                tool_name=tool_name,
                success=False,
                output={},
                summary="Unknown context tool.",
                failure={"code": "unknown_tool", "message": f"Unknown context tool: {tool_name}"},
            )
        else:
            try:
                output = tool()
            except Exception as exc:  # defensive: read-only tools should not fail, but trace if they do
                result = ConversationToolResult(
                    tool_name=tool_name,
                    success=False,
                    output={},
                    summary="Context tool raised an error.",
                    failure={"code": "tool_error", "message": str(exc)},
                )
            else:
                result = ConversationToolResult(
                    tool_name=tool_name,
                    success=True,
                    output=output,
                    summary=f"Read {tool_name}.",
                )
        # backfill the trace so audits can tell success from failure and see the payload
        call_record["payload"] = result.to_dict()
        return result

    def _read_latest_stage_result(self) -> dict[str, Any]:
        return deepcopy(self.request.latest_stage_result or {})
