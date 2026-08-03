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


@dataclass
class AgentPlan:
    stage_id: str
    stage_name: str
    reasoning: str
    skill_name: str
    tool_names: list[str] = field(default_factory=list)
    subagent_names: list[str] = field(default_factory=list)
