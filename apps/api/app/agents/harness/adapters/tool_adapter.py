"""Tool adapter for harness providers."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException

from src.apps.api.app.agents.harness.contracts import (
    HarnessRequest,
    HarnessToolCall,
    HarnessToolResult,
)
from src.apps.api.app.agents.tools.registry import ToolResult
from src.apps.api.app.services.tool_service import invoke_tool


ToolInvoker = Callable[..., ToolResult]


class ToolAdapter:
    def __init__(self, tool_invoker: ToolInvoker | None = None) -> None:
        self._tool_invoker = tool_invoker or invoke_tool

    def list_enabled(self, request: HarnessRequest) -> list[str]:
        return list(request.enabled_tools)

    def invoke(self, request: HarnessRequest, call: HarnessToolCall) -> HarnessToolResult:
        if call.tool_name not in request.enabled_tools:
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary="Tool is not enabled for this harness request.",
                failure={
                    "code": "tool_not_enabled",
                    "detail": "Tool is not enabled for this harness request.",
                    "payload": dict(call.payload),
                },
                audit={"reason": call.reason, "payload": dict(call.payload)},
            )

        try:
            result = self._tool_invoker(
                tool_name=call.tool_name,
                goal=request.goal,
                stage_name=request.stage_name,
                evidence_items=request.evidence_items,
                vision_results=request.vision_results,
                previous_stage_result=request.previous_stage_result,
            )
        except HTTPException as exc:
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary=str(exc.detail),
                failure={
                    "code": "tool_http_error",
                    "status_code": exc.status_code,
                    "detail": exc.detail,
                    "payload": dict(call.payload),
                },
                audit={"reason": call.reason, "payload": dict(call.payload)},
            )
        except Exception as exc:
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary=str(exc),
                failure={
                    "code": "tool_error",
                    "detail": str(exc),
                    "payload": dict(call.payload),
                },
                audit={"reason": call.reason, "payload": dict(call.payload)},
            )

        return HarnessToolResult(
            tool_name=call.tool_name,
            success=True,
            name=result.name,
            summary=result.summary,
            raw_output=dict(result.raw_output),
            evidence_refs=list(result.evidence_refs),
            warnings=list(result.warnings),
            audit={"reason": call.reason, "payload": dict(call.payload)},
        )
