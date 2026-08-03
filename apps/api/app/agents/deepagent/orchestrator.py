"""Minimal DeepAgent orchestrator for the MVP."""

from __future__ import annotations

from src.apps.api.app.agents.deepagent.models import AgentPlan, RunContext
from src.apps.api.app.agents.skills.registry import get_skill_for_stage
from src.apps.api.app.services.project_service import get_stage, list_stages


def resolve_stage(context: RunContext) -> AgentPlan:
    if context.stage_id is not None:
        stage = get_stage(context.stage_id)
        skill = get_skill_for_stage(stage.id)
        return AgentPlan(
            stage_id=stage.id,
            stage_name=stage.name,
            reasoning="Stage was provided explicitly by the request.",
            skill_name=skill.name,
            tool_names=list(skill.allowed_tools),
            subagent_names=list(skill.allowed_subagents),
        )

    stages = list_stages(context.project_id)
    goal = context.goal.lower()
    stage = stages[0]
    reasoning = "Defaulted to stage 1 because no explicit stage was provided."
    if "价值" in context.goal or "sla" in goal:
        stage = stages[1]
        reasoning = "Matched value or SLA keywords to stage 2."
    elif "探针" in context.goal or "样本" in context.goal:
        stage = stages[2]
        reasoning = "Matched probe or sample keywords to stage 3."
    elif "报告" in context.goal or "证据" in context.goal:
        stage = stages[3]
        reasoning = "Matched report or evidence keywords to stage 4."

    skill = get_skill_for_stage(stage.id)
    return AgentPlan(
        stage_id=stage.id,
        stage_name=stage.name,
        reasoning=reasoning,
        skill_name=skill.name,
        tool_names=list(skill.allowed_tools),
        subagent_names=list(skill.allowed_subagents),
    )
