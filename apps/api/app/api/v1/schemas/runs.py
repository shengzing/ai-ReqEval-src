"""Run schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    project_id: str
    goal: str = Field(min_length=1)
    stage_id: Optional[str] = None
    conversation_id: Optional[str] = None


class RunResponse(BaseModel):
    id: str
    project_id: str
    stage_id: Optional[str]
    conversation_id: Optional[str]
    goal: str
    status: str
    failure_reason: Optional[str] = None
    failure_context: dict[str, Any] = Field(default_factory=dict)
    config_version_id: Optional[str] = None
    skill_name: Optional[str] = None
    # HCR-P1-02 配置溯源字段（旧 Run 为 None，复现仍走 config_version_id）。
    primary_skill: Optional[str] = None
    enabled_skills: Optional[list[str]] = None
    requested_skill_name: Optional[str] = None
    routing_source: Optional[str] = None
    waiting_reason: Optional[str] = None
    harness_thread_id: Optional[str] = None
    harness_checkpoint_status: Optional[str] = None
    allowed_resumer: Optional[str] = None
    created_at: datetime


class RunEventResponse(BaseModel):
    type: str
    payload: dict[str, Any]
    created_at: datetime


class ResumeRunRequest(BaseModel):
    human_input: Optional[dict[str, Any]] = None
    # Optional caller assertions checked by the resume consistency gate.
    # ``project_id`` / ``stage_id`` must match the paused Run; omitting them
    # (legacy callers) skips that check. NOTE: plain equality, NOT real auth.
    project_id: Optional[str] = None
    stage_id: Optional[str] = None
    # Optional client-supplied identity. Compared against Run.allowed_resumer
    # (plain string equality). NOTE: not a real auth principal — the project
    # has no identity system yet.
    allowed_resumer: Optional[str] = None


class StageCompletionSnapshotResponse(BaseModel):
    """Single read model used to hydrate the UI after a valid Run completes."""

    run: dict[str, Any]
    stage: dict[str, Any]
    latest_result: Optional[dict[str, Any]] = None
    lock_check: dict[str, Any]
    files: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    conversation: Optional[dict[str, Any]] = None
    workspace: dict[str, Any]
    # HCR-P1-05：富集非首屏数据，让前端完成 Run 后只读一次快照。
    # 两字段 additive Optional，旧缓存响应无此字段仍可校验。
    version_log: Optional[dict[str, Any]] = None
    vision_results: list[dict[str, Any]] = Field(default_factory=list)
