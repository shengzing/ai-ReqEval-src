"""DeepAgent planning models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RunContext:
    run_id: str
    project_id: str
    goal: str
    stage_id: Optional[str]
    conversation_id: Optional[str]
    requested_skill_name: Optional[str] = None
    # Runs are pinned to a published settings snapshot before planning.  The
    # planner must use that same snapshot instead of consulting only the
    # static Skill registry, otherwise a disabled Skill can still be selected.
    config_version_id: Optional[str] = None


@dataclass
class AgentPlan:
    stage_id: str
    stage_name: str
    reasoning: str
    skill_name: str
    tool_names: list[str] = field(default_factory=list)
    subagent_names: list[str] = field(default_factory=list)
    # HCR-P1-02 配置溯源：从冻结 settings snapshot 解析出的路由上下文。
    # config_version_id 是 Run 锁定的发布设置版本；primary_skill /
    # enabled_skills 来自 snapshot 的 stage_skill_profiles；routing_source
    # 标记经 snapshot 解析（"snapshot"）还是静态回退（"static_fallback"）。
    # 这些字段只用于审计/复现展示，不参与派发决策。
    config_version_id: Optional[str] = None
    primary_skill: Optional[str] = None
    enabled_skills: Optional[list[str]] = None
    routing_source: Optional[str] = None
