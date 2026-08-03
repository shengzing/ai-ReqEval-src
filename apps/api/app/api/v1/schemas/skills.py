"""Skill schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SkillResponse(BaseModel):
    name: str
    stage_suffix: str
    description: str
    input_schema: dict[str, str]
    output_schema: dict[str, str]
    allowed_tools: list[str]
    allowed_subagents: list[str]
    auto_run_condition: str
    visibility: str


class SkillListResponse(BaseModel):
    items: list[SkillResponse]


class InvokeSkillRequest(BaseModel):
    project_id: str
    stage_id: str
    run_id: Optional[str] = None
    goal: str = Field(min_length=1)


class SkillInvokeResponse(BaseModel):
    skill_name: str
    stage_id: str
    project_id: str
    summary: str
    tool_names: list[str]
    subagent_names: list[str]
    enabled_tools: list[str] = Field(default_factory=list)
    enabled_subagents: list[str] = Field(default_factory=list)
    config_version_id: Optional[str] = None
    goal: str
    stage_result_id: str
    report_id: Optional[str] = None
    tool_results: list[dict]
    warnings: list[dict] = Field(default_factory=list)
