"""Minimal DeepAgent orchestrator for the MVP."""

from __future__ import annotations

from src.apps.api.app.agents.deepagent.models import AgentPlan, RunContext
from src.apps.api.app.agents.skills.registry import get_skill_by_name, get_skill_for_stage
from src.apps.api.app.services.project_service import get_stage, list_stages
from src.apps.api.app.services.settings_service import settings_snapshot


def _configured_skill_names(
    context: RunContext, stage_id: str
) -> tuple[str, list[str], str]:
    """Resolve the stage Skill route from the Run's frozen settings snapshot.

    HCR-P1-02 错误语义：

    - **无主 Skill / 禁用主 Skill**：snapshot 含该 stage 的 profile 但
      ``primary_skill`` 为空或不在 ``enabled_skills`` 中 → raise ``ValueError``。
    - **snapshot 无 profile（静态回退）**：保留 ``get_skill_for_stage`` 回退
      （阶段 harness 负责空启动场景），但返回 ``routing_source="static_fallback"``
      使回退路径可审计、可复现；正常 snapshot 路径返回 ``"snapshot"``。
    - **多 Skill 并行/串行**：本层只返回 ``(primary, active_skills)``，**仅
      primary_skill 被派发**；``enabled_skills`` 里的次级 Skill 仅经显式
      ``requested_skill_name`` 可达（见 ``resolve_stage``）。并行/串行多 Skill
      派发是阶段 harness 的职责（见 CLAUDE.md 编排流程），不在本路由层实现。
    """
    snapshot = settings_snapshot(
        context.project_id,
        stage_id,
        config_version_id=context.config_version_id,
    )
    profiles = [
        item for item in snapshot.get("stage_skill_profiles", [])
        if item.get("stage_id") == stage_id
    ]
    if not profiles:
        fallback = get_skill_for_stage(stage_id)
        return fallback.name, [fallback.name], "static_fallback"
    profile = profiles[0]
    primary_skill = str(profile.get("primary_skill") or "")
    active_skills = list(profile.get("enabled_skills") or [primary_skill])
    if not primary_skill or primary_skill not in active_skills:
        raise ValueError(
            f"Stage {stage_id} has no enabled primary Skill in settings snapshot "
            f"{snapshot.get('config_version_id', '')}."
        )
    return primary_skill, active_skills, "snapshot"


def resolve_stage(context: RunContext) -> AgentPlan:
    if context.stage_id is not None:
        stage = get_stage(context.stage_id)
        primary_skill_name, active_skill_names, routing_source = _configured_skill_names(context, stage.id)
        try:
            skill = get_skill_by_name(primary_skill_name)
        except KeyError as exc:
            raise ValueError(f"Unknown primary skill configured for stage {stage.id}: {primary_skill_name}") from exc
        if context.requested_skill_name:
            try:
                requested_skill = get_skill_by_name(context.requested_skill_name)
            except KeyError as exc:
                raise ValueError(f"Unknown requested skill: {context.requested_skill_name}") from exc
            if requested_skill.name not in active_skill_names or not stage.id.endswith(requested_skill.stage_suffix):
                raise ValueError(
                    f"Requested skill {context.requested_skill_name} is not enabled for stage {stage.id}"
                )
            skill = requested_skill
        return AgentPlan(
            stage_id=stage.id,
            stage_name=stage.name,
            reasoning="Stage was provided explicitly by the request.",
            skill_name=skill.name,
            tool_names=list(skill.allowed_tools),
            subagent_names=list(skill.allowed_subagents),
            config_version_id=context.config_version_id,
            primary_skill=primary_skill_name,
            enabled_skills=list(active_skill_names),
            routing_source=routing_source,
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

    primary_skill_name, _active_skill_names, routing_source = _configured_skill_names(context, stage.id)
    try:
        skill = get_skill_by_name(primary_skill_name)
    except KeyError as exc:
        raise ValueError(f"Unknown primary skill configured for stage {stage.id}: {primary_skill_name}") from exc
    return AgentPlan(
        stage_id=stage.id,
        stage_name=stage.name,
        reasoning=reasoning,
        skill_name=skill.name,
        tool_names=list(skill.allowed_tools),
        subagent_names=list(skill.allowed_subagents),
        config_version_id=context.config_version_id,
        primary_skill=primary_skill_name,
        enabled_skills=list(_active_skill_names),
        routing_source=routing_source,
    )


def list_skills_for_stage(stage_id: str):
    """Keep an explicit stage allowlist when a conversation requests a Skill."""
    from src.apps.api.app.agents.skills.registry import list_skills

    return list_skills(stage_id)
