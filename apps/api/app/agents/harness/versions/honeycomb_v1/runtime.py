"""Minimal Honeycomb v1 runtime (P1 完整版).

P0 skeleton 升级为 P1 完整版轻量执行器：
- plan 改用 allowed_tools ∩ enabled_tools 交集（与 langgraph-v1 _safe_enabled_tools 一致）
- LLM 配置时走 LLM 规划（可选），未配置/失败/空交集 → fallback plan
- 每次工具调用前 PermissionAdapter 校验，deny 时不执行工具、返回 permission_denied failure
- 4 个 hook 事件触发点：before_harness / before_tool / after_tool / after_harness

不接 synthesize/validate/3d_alignment/refine/autoresearch（保留为 langgraph 专属差异）。
"""

from __future__ import annotations

from typing import Any

from src.apps.api.app.agents.harness.adapters.hook_adapter import HookAdapter
from src.apps.api.app.agents.harness.adapters.llm_adapter import LLMAdapter
from src.apps.api.app.agents.harness.adapters.permission_adapter import PermissionAdapter
from src.apps.api.app.agents.harness.adapters.tool_adapter import ToolAdapter
from src.apps.api.app.agents.harness.contracts import (
    build_skipped_subagent_audits,
    HarnessRequest,
    HarnessResult,
    HarnessToolCall,
    HarnessToolResult,
)


GRAPH_VERSION = "honeycomb-harness-v1"

# mirror of graph.DEFAULT_PLANNER_PROMPT; kept local to avoid coupling honeycomb → langgraph
DEFAULT_PLANNER_PROMPT = (
    "You are an internal requirement-evaluation harness planner. "
    "Return JSON with tool_names and reasoning. Only choose from enabled_tools."
)


class HoneycombV1Runtime:
    def __init__(
        self,
        *,
        tool_adapter: ToolAdapter | None = None,
        permission_adapter: PermissionAdapter | None = None,
        hook_adapter: HookAdapter | None = None,
        llm_adapter: LLMAdapter | None = None,
    ) -> None:
        self._tool_adapter = tool_adapter or ToolAdapter()
        self._permission_adapter = permission_adapter or PermissionAdapter()
        self._hook_adapter = hook_adapter or HookAdapter()
        self._llm_adapter = llm_adapter

    # ------------------------------------------------------------------
    # LLM 规划 / fallback（镜像 langgraph plan_tools，graph.py:99-140）
    # ------------------------------------------------------------------

    def _plan_tools(
        self,
        request: HarnessRequest,
        safe_enabled: list[str],
        llm_adapter: LLMAdapter,
        traces: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        llm_status = llm_adapter.status()
        if llm_adapter.is_configured():
            try:
                system_prompt = request.prompt_templates.get("prompt-planner", DEFAULT_PLANNER_PROMPT)
                payload = llm_adapter.complete_json(
                    system_prompt=system_prompt,
                    user_payload={
                        "skill": request.skill_name,
                        "stage_name": request.stage_name,
                        "goal": request.goal,
                        "enabled_tools": safe_enabled,
                        "config_version_id": request.config_version_id,
                    },
                )
                requested = list(payload.get("tool_names", []))
                planned = [t for t in requested if t in safe_enabled]
                if planned:
                    plan = {
                        "tool_names": planned,
                        "reasoning": str(payload.get("reasoning", "LLM selected enabled tools.")),
                        "source": "honeycomb-llm",
                    }
                    traces.append(
                        {
                            "event": "honeycomb.planned",
                            "payload": {"tool_names": planned, "source": "honeycomb-llm"},
                        }
                    )
                    return plan, traces, llm_status
            except Exception as exc:  # noqa: BLE001 — LLM 失败必须降级为 fallback plan
                llm_status = llm_adapter.status(mode="error_fallback", message=str(exc))
                traces.append(
                    {"event": "honeycomb.plan_failed", "payload": {"error": str(exc)}}
                )
        # Fallback：plan = safe_enabled（交集后的顺序）
        plan = {
            "tool_names": safe_enabled,
            "reasoning": "Execute enabled tools in settings order.",
            "source": "honeycomb-fallback",
        }
        traces.append(
            {
                "event": "honeycomb.planned",
                "payload": {"tool_names": safe_enabled, "source": "honeycomb-fallback"},
            }
        )
        return plan, traces, llm_status

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def _resolve_llm_adapter(self, request: HarnessRequest) -> LLMAdapter:
        if self._llm_adapter is not None:
            return self._llm_adapter
        llm_client = request.options.get("llm_client")
        if llm_client is not None:
            return LLMAdapter(llm_client=llm_client)
        return LLMAdapter()

    def run(self, request: HarnessRequest) -> HarnessResult:
        traces: list[dict[str, Any]] = [
            {
                "event": "honeycomb.started",
                "payload": {"skill_name": request.skill_name, "stage_id": request.stage_id},
            }
        ]

        # before_harness hook（trimmed payload，不传整个 request）
        traces.extend(
            self._hook_adapter.trigger(
                "before_harness",
                {"skill_name": request.skill_name, "stage_id": request.stage_id, "run_id": request.run_id},
            )
        )

        # 交集 plan（与 langgraph _safe_enabled_tools 一致；空 allowed_tools 时不强制过滤）
        if request.allowed_tools:
            safe_enabled = [t for t in request.enabled_tools if t in request.allowed_tools]
        else:
            safe_enabled = list(request.enabled_tools)

        llm_adapter = self._resolve_llm_adapter(request)
        plan, traces, llm_status = self._plan_tools(request, safe_enabled, llm_adapter, traces)

        tool_results: dict[str, dict[str, Any]] = {}
        tool_result_items: list[dict[str, Any]] = []
        tool_failures: list[dict[str, Any]] = []
        tool_skips: list[dict[str, Any]] = []

        for tool_name in plan["tool_names"]:
            # before_tool hook（permission check 之前，观察所有尝试含被拒）
            traces.extend(
                self._hook_adapter.trigger(
                    "before_tool",
                    {"tool_name": tool_name, "reason": "honeycomb.plan"},
                )
            )
            traces.append({"event": "tool.started", "payload": {"tool_name": tool_name}})

            call = HarnessToolCall(tool_name=tool_name, reason="honeycomb.plan")
            # ToolAdapter is the one permission-enforcing execution boundary
            # for every provider.  Honeycomb keeps its own adapter only for
            # compatibility with injected policies by attaching it to this
            # request-local executor at construction time.
            result = self._tool_adapter.invoke(
                request,
                call,
                llm_client=llm_adapter.client,
                permission_adapter=self._permission_adapter,
                provider="honeycomb-v1",
            )

            if result.success:
                item = result.to_result_item()
                tool_result_items.append(item)
                tool_results[tool_name] = dict(item["raw_output"])
                traces.append(
                    {
                        "event": "tool.completed",
                        "payload": {"tool_name": tool_name, "summary": result.summary},
                    }
                )
            elif result.status == "skipped_missing_input":
                tool_skips.append(result.to_skip_item())
                traces.append(
                    {
                        "event": "tool.skipped",
                        "payload": {
                            "tool_name": tool_name,
                            "reason": result.status,
                            "audit": result.audit,
                        },
                    }
                )
            else:
                failure = result.to_failure_item()
                tool_failures.append(failure)
                traces.append(
                    {
                        "event": "tool.completed",
                        "payload": {
                            "tool_name": tool_name,
                            "status": "failed",
                            "detail": failure["detail"],
                            "code": result.failure.get("code") if result.failure else None,
                        },
                    }
                )

            # after_tool hook
            traces.extend(
                self._hook_adapter.trigger(
                    "after_tool",
                    {"tool_name": tool_name, "success": result.success, "summary": result.summary},
                )
            )

        no_completed_tools = bool(tool_skips) and not bool(tool_results)
        decision = {
            "should_continue": not tool_failures and not no_completed_tools,
            "requires_human": bool(tool_failures),
            "summary": (
                "Honeycomb executed enabled tools."
                if not tool_failures and not no_completed_tools
                else "Honeycomb skipped all tools because required input is unavailable."
                if no_completed_tools
                else "Honeycomb completed with tool failures."
            ),
            "confidence": 0.8 if not tool_failures and not no_completed_tools else 0.0 if no_completed_tools else 0.4,
            "source": "honeycomb-fallback" if tool_failures else plan["source"],
            "notes": [item["detail"] for item in tool_failures],
        }
        traces.append({"event": "honeycomb.decision", "payload": decision})

        # Honeycomb v1 intentionally does not dispatch generic subagents.
        # Keep that capability decision explicit so an enabled subagent cannot
        # look as if it silently disappeared from the audit chain.
        subagent_audits = build_skipped_subagent_audits(
            request,
            provider="honeycomb-v1",
            reason="Honeycomb v1 当前仅执行项目工具，尚未实现通用子代理派发。",
        )
        if subagent_audits:
            traces.append(
                {
                    "event": "subagents.skipped",
                    "payload": {
                        "provider": "honeycomb-v1",
                        "count": len(subagent_audits),
                        "reason": "provider_subagent_unsupported",
                    },
                }
            )

        # after_harness hook
        traces.extend(
            self._hook_adapter.trigger(
                "after_harness",
                {
                    "decision_should_continue": decision["should_continue"],
                    "tool_count": len(plan["tool_names"]),
                    "failure_count": len(tool_failures),
                },
            )
        )

        return HarnessResult(
            harness_version="honeycomb-v1",
            graph_version=GRAPH_VERSION,
            plan=plan,
            decision=decision,
            tool_results=tool_results,
            tool_result_items=tool_result_items,
            tool_failures=tool_failures,
            tool_skips=tool_skips,
            synthesized_payload={"source": "skipped_missing_input", "formal_result": False} if no_completed_tools else {"source": "tool_results"},
            validation_issues=[],
            quality_scores={},
            subagent_results=[],
            subagent_audits=subagent_audits,
            autoresearch_record_ids=[],
            traces=traces,
            effects=[],
            raw={"llm_status": llm_status},
        )
