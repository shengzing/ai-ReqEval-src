"""Tool adapter for harness providers."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
import inspect
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException

from src.apps.api.app.agents.harness.contracts import (
    HarnessRequest,
    HarnessToolCall,
    HarnessToolResult,
)
from src.apps.api.app.agents.harness.adapters.permission_adapter import PermissionAdapter
from src.apps.api.app.agents.tools.registry import ToolResult
from src.apps.api.app.security.sanitization import redact_value
from src.apps.api.app.services.tool_service import invoke_tool


ToolInvoker = Callable[..., ToolResult]


class ToolAdapter:
    """Unified tool executor for every harness provider (HCR-P1-01).

    ``invoke`` is the single chokepoint through which Honeycomb, LangGraph, and
    Deep Agents (plus their fallback paths) execute a tool. It applies, in order:
    payload redaction, a unified audit envelope (``invocation_id`` /
    ``provider`` / ``skill_name`` / ``tool_name`` / ``outcome`` /
    ``duration_ms`` / ``evidence_refs`` / ``permission_decision``), the
    enabled-tools gate, the request-level permission policy, an optional
    timeout, and outcome normalization (``completed`` /
    ``skipped_missing_input`` / ``failed`` / ``denied`` / ``timeout``).

    Sub-agents are deliberately NOT executed here. They carry their own
    audit schema (``SubagentAuditRecord`` in ``contracts.py``) because their
    failure shape (``adoption_status`` / ``review_status``) is not isomorphic to
    a tool's. Standardizing sub-agent results into
    ``StageResult.result_payload.harness`` is tracked by HCR-P2-01.
    """
    def __init__(
        self,
        tool_invoker: ToolInvoker | None = None,
        permission_adapter: PermissionAdapter | None = None,
    ) -> None:
        self._tool_invoker = tool_invoker or invoke_tool
        self._permission_adapter = permission_adapter or PermissionAdapter()

    def list_enabled(self, request: HarnessRequest) -> list[str]:
        return list(request.enabled_tools)

    def invoke(
        self,
        request: HarnessRequest,
        call: HarnessToolCall,
        *,
        llm_client: object | None = None,
        permission_adapter: PermissionAdapter | None = None,
        provider: str = "",
    ) -> HarnessToolResult:
        """Execute one tool through the shared permission and audit boundary.

        ``permission_adapter`` is intentionally supplied per invocation: a
        request-level policy must take precedence over the policy that may be
        embedded in an injected adapter.  This keeps Honeycomb, LangGraph,
        Deep Agents, and fallback paths subject to the same policy.
        """
        started_at = perf_counter()
        safe_payload = redact_value(dict(call.payload))
        audit_base = {
            "invocation_id": str(call.payload.get("invocation_id") or f"tool-{uuid4().hex[:12]}"),
            "provider": provider or str(call.payload.get("provider") or "unknown"),
            "skill_name": request.skill_name,
            "tool_name": call.tool_name,
            "reason": call.reason,
            "payload": safe_payload,
        }

        def audit(*, outcome: str, permission: str, evidence_refs: list[str] | None = None) -> dict:
            return {
                **audit_base,
                "outcome": outcome,
                "permission": permission,
                "permission_decision": permission,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                "evidence_refs": list(evidence_refs or []),
            }

        # Preserve the public error contract for an explicitly disabled tool;
        # the subsequent permission gate covers allowlist violations.
        if call.tool_name not in request.enabled_tools:
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary="Tool is not enabled for this harness request.",
                status="failed",
                failure={
                    "code": "tool_not_enabled",
                    "detail": "Tool is not enabled for this harness request.",
                    "payload": safe_payload,
                },
                audit=audit(outcome="denied", permission="tool_not_in_enabled_tools"),
            )
        effective_permission_adapter = permission_adapter or self._permission_adapter
        permission = effective_permission_adapter.check(request, call)
        if not permission.allowed:
            denied = effective_permission_adapter.build_denied_result(call, permission)
            denied["payload"] = safe_payload
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary=denied["detail"],
                status="failed",
                failure=denied,
                audit=audit(outcome="denied", permission=permission.reason),
            )
        timeout_raw = request.options.get("tool_timeout_seconds")
        try:
            timeout_s = float(timeout_raw) if timeout_raw is not None else None
        except (TypeError, ValueError):
            timeout_s = None
        timeout_enabled = timeout_s is not None and timeout_s > 0
        try:
            kwargs: dict[str, object] = {
                "tool_name": call.tool_name,
                "goal": request.goal,
                "stage_name": request.stage_name,
                "evidence_items": request.evidence_items,
                "vision_results": request.vision_results,
                "previous_stage_result": request.previous_stage_result,
            }
            parameters = inspect.signature(self._tool_invoker).parameters
            accepts_kwargs = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
            if llm_client is not None and ("llm_client" in parameters or accepts_kwargs):
                kwargs["llm_client"] = llm_client
            if timeout_enabled:
                # Run the invoker in a throwaway pool so a hung tool cannot
                # block the Run.  Python threads cannot be force-killed, so on
                # timeout the background call leaks until it returns on its
                # own — acceptable for research-evaluation workloads in
                # exchange for not hanging the harness.  ``shutdown(wait=False,
                # cancel_futures=True)`` returns immediately without joining.
                pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = pool.submit(self._tool_invoker, **kwargs)
                try:
                    result = future.result(timeout=timeout_s)
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
            else:
                result = self._tool_invoker(**kwargs)
        except concurrent.futures.TimeoutError:
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary=f"Tool timed out after {timeout_s}s",
                status="failed",
                failure={
                    "code": "tool_timeout",
                    "timeout_seconds": timeout_s,
                    "detail": f"Tool timed out after {timeout_s}s",
                    "payload": safe_payload,
                },
                audit=audit(outcome="timeout", permission=permission.reason),
            )
        except HTTPException as exc:
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary=str(exc.detail),
                status="failed",
                failure={
                    "code": "tool_http_error",
                    "status_code": exc.status_code,
                    "detail": exc.detail,
                    "payload": safe_payload,
                },
                audit=audit(outcome="failed", permission=permission.reason),
            )
        except Exception as exc:
            return HarnessToolResult(
                tool_name=call.tool_name,
                success=False,
                summary=str(exc),
                status="failed",
                failure={
                    "code": "tool_error",
                    "detail": str(exc),
                    "payload": safe_payload,
                },
                audit=audit(outcome="failed", permission=permission.reason),
            )

        result_status = str(getattr(result, "status", "completed"))
        completed = result_status == "completed"
        return HarnessToolResult(
            tool_name=call.tool_name,
            success=completed,
            status=result_status,
            name=result.name,
            summary=result.summary,
            raw_output=dict(result.raw_output),
            evidence_refs=list(result.evidence_refs),
            warnings=list(result.warnings),
            audit=audit(
                outcome="completed" if completed else result_status,
                permission=permission.reason,
                evidence_refs=list(result.evidence_refs),
            ),
        )
