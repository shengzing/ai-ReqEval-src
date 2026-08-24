"""Provider wrapper for the existing LangGraph harness."""

from __future__ import annotations

from typing import Any

from src.apps.api.app.agents.harness.contracts import (
    HarnessRequest,
    HarnessResult,
    harness_result_from_legacy_state,
)
from src.apps.api.app.agents.harness.runner import HarnessConfig, run_skill_harness
from src.apps.api.app.agents.skills.registry import SkillDefinition


class LangGraphV1HarnessProvider:
    version = "langgraph-v1"

    def __init__(
        self,
        *,
        tool_invoker: Any | None = None,
        config: HarnessConfig | None = None,
    ) -> None:
        self._tool_invoker = tool_invoker
        self._config = config

    def run(self, request: HarnessRequest) -> HarnessResult:
        llm_client = request.options.get("llm_client")
        tool_invoker = request.options.get("tool_invoker") or self._tool_invoker
        skill = SkillDefinition(
            name=request.skill_name,
            stage_suffix="",
            description=request.skill_description,
            allowed_tools=list(request.allowed_tools),
            allowed_subagents=list(request.allowed_subagents),
        )
        config = self._config
        enable_hitl = bool(request.options.get("enable_hitl", False))
        if enable_hitl and config is None:
            config = HarnessConfig(enable_hitl=True)
        result = run_skill_harness(
            skill=skill,
            goal=request.goal,
            stage_name=request.stage_name,
            enabled_tools=list(request.enabled_tools),
            enabled_subagents=list(request.enabled_subagents),
            evidence_items=list(request.evidence_items),
            vision_results=list(request.vision_results),
            previous_stage_result=request.previous_stage_result,
            llm_client=llm_client,
            tool_invoker=tool_invoker,
            config=config,
            auto_run_condition=str(request.options.get("auto_run_condition", "")) or None,
            context={
                "project_id": request.project_id,
                "stage_id": request.stage_id,
                "run_id": request.run_id,
                "config_version_id": request.config_version_id,
                "skill_version": request.skill_version,
                "primary_skill": request.primary_skill,
                "enabled_skills": list(request.enabled_skills),
                "enabled_subagents": list(request.enabled_subagents),
                "thread_id": request.options.get("harness_thread_id") or f"thread-{request.run_id}",
                "permission_adapter": request.options.get("permission_adapter"),
                "tool_adapter": request.options.get("tool_adapter"),
            },
        )
        checkpoint: dict[str, Any] = {}
        if isinstance(result, tuple):
            execution_result, thread_id = result
            state = dict(execution_result.state)
            checkpoint = {
                "thread_id": thread_id,
                "status": "paused",
                "provider": self.version,
            }
        else:
            state = dict(result.state)
        state["harness_version"] = self.version
        state["checkpoint"] = checkpoint
        return harness_result_from_legacy_state(state, harness_version=self.version)
