"""Settings schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.apps.api.app.core.harness_constants import (
    DEFAULT_AGENT_HARNESS_VERSION,
    DEFAULT_CONVERSATION_HARNESS_VERSION,
)


class ModelProfileRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    role: str
    model_name: str
    base_url: str = ""
    api_key: str = ""
    enabled: bool = True
    # True = reasoning models may emit <think>...</think> chains before JSON.
    # False = harness appends extra_body={enable_thinking: False} plus a
    # system-prompt directive asking the model to skip the thinking chain.
    # Defaults to True for backward compatibility with MiniMax-M3 etc.
    reasoning_mode: bool = True


class ModelProfileResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    role: str
    model_name: str
    base_url: str = ""
    api_key: str = ""
    enabled: bool
    reasoning_mode: bool = True


class PromptTemplateRequest(BaseModel):
    id: str
    category: str
    scope: str = ""
    title: str = ""
    body: str
    required_variables: list[str] = Field(default_factory=list)
    skill_name: Optional[str] = None
    version: str = "v1"


class PromptTemplateResponse(BaseModel):
    id: str
    category: str
    scope: str = ""
    title: str = ""
    body: str
    required_variables: list[str]
    skill_name: Optional[str] = None
    version: str


class StageSkillProfileRequest(BaseModel):
    stage_id: str
    primary_skill: str
    enabled_tools: list[str] = Field(default_factory=list)
    enabled_subagents: list[str] = Field(default_factory=list)
    enabled_skills: list[str] = Field(default_factory=list)
    auto_run_condition: str = "manual"
    harness_version: str = DEFAULT_AGENT_HARNESS_VERSION
    conversation_harness_version: str = DEFAULT_CONVERSATION_HARNESS_VERSION
    skill_versions: dict[str, str] = Field(default_factory=dict)


class StageSkillProfileResponse(BaseModel):
    stage_id: str
    primary_skill: str
    enabled_tools: list[str]
    enabled_subagents: list[str]
    enabled_skills: list[str] = Field(default_factory=list)
    auto_run_condition: str
    harness_version: str = DEFAULT_AGENT_HARNESS_VERSION
    conversation_harness_version: str = DEFAULT_CONVERSATION_HARNESS_VERSION
    skill_versions: dict[str, str] = Field(default_factory=dict)


class RunPolicyRequest(BaseModel):
    require_change_reason: bool = True
    # Default True: locked stages stay rerunnable unless the operator
    # explicitly opts in to the guard. The 409 gate fires only when this
    # is False (see ``create_run`` in run_service.py).
    allow_locked_stage_rerun: bool = True
    min_audit_requirements: list[str] = Field(
        default_factory=lambda: [
            "config_version_id",
            "model_alias",
            "prompt_hash",
            "skill_version",
        ]
    )
    # P3-b: 对话 Harness 上下文裁剪 limit
    conversation_message_limit: int = 20
    conversation_evidence_item_limit: int = 50
    conversation_evidence_snippet_limit: int = 500
    conversation_run_event_limit: int = 30


class RunPolicyResponse(BaseModel):
    require_change_reason: bool
    allow_locked_stage_rerun: bool
    min_audit_requirements: list[str]
    conversation_message_limit: int
    conversation_evidence_item_limit: int
    conversation_evidence_snippet_limit: int
    conversation_run_event_limit: int


class ProjectSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    version_id: str
    base_version_id: Optional[str] = None
    status: str
    config_hash: str
    change_reason: str
    models: list[ModelProfileResponse]
    prompts: list[PromptTemplateResponse]
    stage_skill_profiles: list[StageSkillProfileResponse]
    run_policy: RunPolicyResponse
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    created_by: str


class ProjectSettingsBundleResponse(BaseModel):
    published: Optional[ProjectSettingsResponse] = None
    draft: Optional[ProjectSettingsResponse] = None
    has_draft: bool


class SettingsDraftRequest(BaseModel):
    models: list[ModelProfileRequest]
    prompts: list[PromptTemplateRequest]
    stage_skill_profiles: list[StageSkillProfileRequest]
    run_policy: RunPolicyRequest
    change_reason: str = ""


class PublishSettingsRequest(BaseModel):
    draft_id: Optional[str] = None
    change_reason: str = ""


class ModelOptionResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    base_url: str = ""


class ModelOptionListResponse(BaseModel):
    items: list[ModelOptionResponse]


class ModelTestRequest(BaseModel):
    """Ad-hoc model connectivity probe payload.

    The fields mirror :class:`ModelProfileRequest` minus ``role``. The route
    builds a transient :class:`HarnessLLMClient` from these values and pings
    the provider; nothing is persisted.
    """

    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    base_url: str = ""
    api_key: str = ""
    reasoning_mode: bool = True


class ModelTestResponse(BaseModel):
    ok: bool
    latency_ms: Optional[int] = None
    message: str
    model: str
    base_url: str


class SkillOptionResponse(BaseModel):
    name: str
    stage_suffix: str
    description: str
    allowed_tools: list[str]
    allowed_subagents: list[str]
    auto_run_condition: str
    visibility: str


class SkillOptionListResponse(BaseModel):
    items: list[SkillOptionResponse]


class SettingsImpactResponse(BaseModel):
    project_id: str
    draft_id: Optional[str] = None
    draft_version_id: Optional[str] = None
    has_draft: bool
    impacted_stages: list[dict]
    impacted_models: list[dict]
    impacted_prompts: list[dict]
    impacted_policy_keys: list[str]
    summary: str


class ProjectSettingsListResponse(BaseModel):
    items: list[ProjectSettingsResponse]
