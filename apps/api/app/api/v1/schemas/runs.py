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
    created_at: datetime


class RunEventResponse(BaseModel):
    type: str
    payload: dict[str, Any]
    created_at: datetime


class ResumeRunRequest(BaseModel):
    human_input: Optional[dict[str, Any]] = None
