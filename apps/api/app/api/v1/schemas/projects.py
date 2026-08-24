"""Project and stage schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class UpdateProjectRequest(BaseModel):
    name: str = Field(min_length=1)


class ProjectResponse(BaseModel):
    id: str
    name: str
    goal: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]


class StageResponse(BaseModel):
    id: str
    project_id: str
    name: str
    status: str
    created_at: datetime
    objective: Optional[str] = None


class StageListResponse(BaseModel):
    items: list[StageResponse]


class StageResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, protected_namespaces=())

    id: str
    project_id: str
    stage_id: str
    version_id: str
    base_version_id: Optional[str] = None
    run_id: str
    status: str
    input_file_ids: list[str]
    evidence_item_ids: list[str]
    model_config_field: dict = Field(alias="model_config", serialization_alias="model_config")
    skill_versions: dict[str, str]
    autoresearch_record_ids: list[str]
    # L1-A: prompt runtime audit fields — exposed so callers can verify which
    # prompts produced a given scenario_summary.
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    confirmation_ids: list[str]
    result_payload: dict
    summary: str
    valid_result: bool = True
    invalid_reason: Optional[str] = None
    invalidated_at: Optional[datetime] = None
    superseded_by_run_id: Optional[str] = None
    # HCR-P1-02：first-class 溯源字段（旧 doc 为 None，仍可从
    # result_payload 嵌套副本或 Run.config_version_id 复现）。
    skill_name: Optional[str] = None
    config_version_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    locked_at: Optional[datetime] = None


class StageResultListResponse(BaseModel):
    items: list[StageResultResponse]


class StageLockCheckItemResponse(BaseModel):
    key: str
    label: str
    passed: bool
    machine_code: str
    hint: str
    object_id: Optional[str] = None


class LockStageResponse(BaseModel):
    stage: StageResponse
    version_log_id: str
    checks: list[StageLockCheckItemResponse]


class StageLockCheckResponse(BaseModel):
    stage_id: str
    checks: list[StageLockCheckItemResponse]
    ready: bool


class CreateConversationRequest(BaseModel):
    title: str = Field(min_length=1)
    initial_message: Optional[str] = None


class ConversationMessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
    source_event_id: Optional[str] = None
    run_id: Optional[str] = None
    action_proposals: list[dict] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    harness_warnings: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    process_only: bool = False


class ConversationResponse(BaseModel):
    id: str
    stage_id: str
    project_id: str
    title: str
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]


class WorkspaceStageNodeResponse(StageResponse):
    pending_confirmations: int = 0
    conversations: list[ConversationResponse] = Field(default_factory=list)


class WorkspaceProjectNodeResponse(ProjectResponse):
    pending_count: int = 0
    file_count: int = 0
    stages: list[WorkspaceStageNodeResponse] = Field(default_factory=list)


class WorkspaceTreeResponse(BaseModel):
    items: list[WorkspaceProjectNodeResponse]


class FileUploadRequest(BaseModel):
    project_id: str
    filename: str = Field(min_length=1)
    content_type: str = "application/octet-stream"
    content: Optional[str] = None
    content_base64: Optional[str] = None


class FileArtifactResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    content_type: str
    status: str
    storage_path: Optional[str] = None
    size_bytes: int = 0
    relevance_status: str = "pending_parse"
    relevance_score: float = 0.0
    relevance_reasons: list[str] = Field(default_factory=list)
    relevance_rule_version: str = ""
    relevance_input_hash: str = ""
    relevance_source: str = "machine"
    relevance_review_reason: Optional[str] = None
    relevance_reviewed_by: Optional[str] = None
    relevance_reviewed_at: Optional[datetime] = None
    # HCR-P1-03：人工复核前态（旧 doc 为 None）。
    relevance_previous_status: Optional[str] = None
    security_rejected: bool = False
    created_at: datetime


class FileArtifactListResponse(BaseModel):
    items: list[FileArtifactResponse]


class FileRelevanceReviewRequest(BaseModel):
    decision: Literal["related", "unrelated", "rejected"]
    reason: str = Field(min_length=3, max_length=500)
    reviewer: str = Field(default="workspace_user", min_length=1, max_length=100)


class FilePreviewResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    content_type: str
    preview_type: str
    content: str
    encoding: str = "utf-8"
    size_bytes: int = 0
    truncated: bool = False


class VisionParseRequest(BaseModel):
    prompt: str = Field(min_length=1)
    target_schema: dict[str, str]
    project_context: dict = Field(default_factory=dict)


class VisionParseResponse(BaseModel):
    file_id: str
    project_id: str
    model: str
    structured_fields: dict
    evidence_fragments: list[dict]
    uncertainties: list[str]
    to_confirm: list[dict]
    raw_response: str


class VisionResultSummaryResponse(BaseModel):
    file_id: str
    model: str
    structured_fields: dict
    evidence_fragments: list[dict]
    uncertainties: list[str]
    to_confirm: list[dict]


class VisionResultSummaryListResponse(BaseModel):
    items: list[VisionResultSummaryResponse]


class EvidenceItemResponse(BaseModel):
    id: str
    project_id: str
    name: str
    source_type: str
    source_file_id: Optional[str] = None
    attachment_path: Optional[str] = None
    snippet: Optional[str] = None
    created_at: datetime
    status: str
    review_note: Optional[str] = None
    relevance_status: str = "pending_parse"
    relevance_score: float = 0.0
    relevance_reasons: list[str] = Field(default_factory=list)
    relevance_rule_version: str = ""
    relevance_input_hash: str = ""
    relevance_source: str = "machine"
    relevance_review_reason: Optional[str] = None
    relevance_reviewed_by: Optional[str] = None
    relevance_reviewed_at: Optional[datetime] = None
    # HCR-P1-03：人工复核前态（旧 doc 为 None）。
    relevance_previous_status: Optional[str] = None
    updated_at: datetime


class EvidenceListResponse(BaseModel):
    items: list[EvidenceItemResponse]


class GenerateReportRequest(BaseModel):
    project_id: str
    title: str = Field(min_length=1)


class ReportResponse(BaseModel):
    id: str
    project_id: str
    title: str
    status: str
    approval_check_passed: bool
    export_path: Optional[str] = None
    decision_card_path: Optional[str] = None
    evidence_directory_path: Optional[str] = None
    bundle_export_path: Optional[str] = None
    stage_result_ids: list[str] = Field(default_factory=list)
    evidence_item_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class ReportContentResponse(BaseModel):
    id: str
    title: str
    status: str
    content: str


class ExecutionLogResponse(BaseModel):
    id: str
    project_id: str
    action: str
    resource_type: str
    resource_id: str
    run_id: Optional[str] = None
    details: dict
    created_at: datetime


class ExecutionLogListResponse(BaseModel):
    items: list[ExecutionLogResponse]


class VersionLogResponse(BaseModel):
    id: str
    project_id: str
    resource_type: str
    resource_id: str
    change_type: str
    summary: str
    run_id: Optional[str] = None
    details: dict
    created_at: datetime


class VersionLogListResponse(BaseModel):
    items: list[VersionLogResponse]


class AppendMessageRequest(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1)
    run_harness: bool = False
    config_version_id: Optional[str] = None


class AssistantHarnessMessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
    tool_calls: list[dict] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)


class ActionProposalSummary(BaseModel):
    """脱敏后的 action proposal 摘要，前端可直接拿 id 调 confirm/reject 路由。

    不回传 payload（含 stage_id/goal 等敏感字段）与 runtime_version。
    """
    id: str
    action_type: str
    title: str
    requires_confirmation: bool
    status: str = "pending"
    confirmation_id: Optional[str] = None


class HarnessSummary(BaseModel):
    """强类型 harness 摘要，替换原裸 dict，避免泄漏内部 runtime 信息。"""
    conversation_harness_version: str
    intent: dict
    citations: list[dict]
    warnings: list[dict]
    action_proposals: list[ActionProposalSummary]


class ActionProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    action_type: str
    title: str
    status: str
    requires_confirmation: bool
    run_id: Optional[str] = None
    confirmation_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ConfirmActionProposalResponse(BaseModel):
    proposal: ActionProposalResponse
    run_id: Optional[str] = None
    confirmation_id: Optional[str] = None


class AppendMessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
    assistant_message: Optional[AssistantHarnessMessageResponse] = None
    harness: Optional[HarnessSummary] = None
