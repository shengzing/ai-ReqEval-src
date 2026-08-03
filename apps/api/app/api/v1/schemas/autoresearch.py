"""autoResearch schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from src.apps.api.app.api.v1.schemas.projects import StageResultResponse


class CreateAutoResearchRequest(BaseModel):
    stage_id: str
    run_id: str


class CreateManualAutoResearchRequest(BaseModel):
    stage_id: str
    title: str
    description: str
    action: str
    impact: str = "影响当前阶段结果"
    risk: str = "medium"
    source: str = "vision_manual"
    run_id: Optional[str] = None
    context: dict = {}


class ConfirmAutoResearchRequest(BaseModel):
    decision: str
    note: Optional[str] = None
    edited_description: Optional[str] = None


class AutoResearchRecordResponse(BaseModel):
    id: str
    project_id: str
    stage_id: str
    run_id: str
    stage_result_id: str
    title: str
    source: str
    impact: str
    risk: str
    description: str
    action: str
    context: dict
    status: str
    note: Optional[str] = None
    edited_description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None


class AutoResearchRecordListResponse(BaseModel):
    items: list[AutoResearchRecordResponse]


class AutoResearchConfirmResponse(BaseModel):
    record: AutoResearchRecordResponse
    stage_result: Optional[StageResultResponse] = None


# ── Frozen Eval Contract / Candidate / Rejected schemas ──


class FrozenEvalContractResponse(BaseModel):
    id: str
    version: str
    stage_id: str
    frozen_fields: list[dict[str, Any]]
    mutable_fields: list[str]
    created_at: datetime
    created_by: str = "system"


class AutoResearchCandidateResponse(BaseModel):
    id: str
    project_id: str
    stage_id: str
    run_id: str
    change_type: str
    target_stage: str
    hypothesis: str
    changed_refs: list[str]
    expected_effect: str
    must_not_change: list[str]
    status: str
    iteration: int
    metrics_before: dict[str, Any] = {}
    metrics_after: dict[str, Any] = {}
    gate_result: str = ""
    gate_reason: str = ""
    human_review_status: str = "not_required"
    created_at: datetime


class AutoResearchCandidateListResponse(BaseModel):
    items: list[AutoResearchCandidateResponse]


class RejectedCandidateResponse(BaseModel):
    id: str
    project_id: str
    stage_id: str
    candidate_id: str
    rejection_reason: str
    failed_metrics: dict[str, Any] = {}
    hard_constraint_triggered: str = ""
    reusable_insights: list[str] = []
    retry_allowed: bool = True
    created_at: datetime


class RejectedCandidateListResponse(BaseModel):
    items: list[RejectedCandidateResponse]


# ── L2: Rule proposal ─────────────────────────────────────────────────────


class RuleProposalResponse(BaseModel):
    id: str
    project_id: str
    stage_id: str
    run_id: str
    proposal_kind: str
    target_rule_id: str
    new_rule: Optional[dict[str, Any]] = None
    rationale: str = ""
    supporting_metrics: dict[str, Any] = {}
    status: str = "proposed"
    human_review_status: str = "pending"
    created_at: datetime
    accepted_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_rationale: str = ""


class RuleProposalListResponse(BaseModel):
    items: list[RuleProposalResponse]


class RuleProposalDecisionRequest(BaseModel):
    reviewer: str = "human"
    rationale: str = ""


class CapabilityMutabilityContractResponse(BaseModel):
    id: str
    version: str
    stage_id: str
    mutable_capabilities: list[str]
    capability_gates: list[dict[str, Any]]
    created_at: datetime
    created_by: str = "system"


# ── L4: Skill run comparison ──────────────────────────────────────────────


class SkillRunComparisonResponse(BaseModel):
    id: str
    project_id: str
    stage_id: str
    skill_name: str
    run_id_v1: str
    version_v1: str
    run_id_v2: str
    version_v2: str
    input_payload_hash: str
    quality_v1: dict[str, float] = {}
    quality_v2: dict[str, float] = {}
    quality_delta: dict[str, float] = {}
    issue_count_v1: int = 0
    issue_count_v2: int = 0
    tool_call_diff: dict[str, int] = {}
    prompt_hashes_v1: dict[str, str] = {}
    prompt_hashes_v2: dict[str, str] = {}
    verdict: str = "neutral"
    verdict_reason: str = ""
    created_at: datetime


class SkillRunComparisonListResponse(BaseModel):
    items: list[SkillRunComparisonResponse]


class ABCompareRequest(BaseModel):
    project_id: str
    stage_id: str
    skill_name: str
    version_v1: str
    version_v2: str
    input_payload: dict[str, Any] = {}
