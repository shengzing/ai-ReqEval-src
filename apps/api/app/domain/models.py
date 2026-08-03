"""Domain models for the API MVP skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from typing import Any

from src.apps.api.app.core.harness_constants import (
    DEFAULT_AGENT_HARNESS_VERSION,
    DEFAULT_CONVERSATION_HARNESS_VERSION,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ConversationMessage:
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = field(default_factory=utcnow)
    source_event_id: Optional[str] = None  # populated when message was transcribed from a RunEvent
    run_id: Optional[str] = None  # source Run (if any)
    action_proposals: list[dict[str, Any]] = field(default_factory=list)
    harness_warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Conversation:
    id: str
    stage_id: str
    project_id: str  # redundant with stage.project_id; lets clients skip a join
    title: str
    status: str = "active"  # "active" | "archived" | "deleted"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    archived_at: Optional[datetime] = None
    messages: list[ConversationMessage] = field(default_factory=list)


@dataclass
class Stage:
    id: str
    project_id: str
    name: str
    status: str = "pending"
    created_at: datetime = field(default_factory=utcnow)
    objective: Optional[str] = None


@dataclass
class Project:
    id: str
    name: str
    goal: str
    status: str = "created"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    stages: list[Stage] = field(default_factory=list)


@dataclass
class RunEvent:
    id: str
    run_id: str
    project_id: str
    stage_id: Optional[str]
    conversation_id: Optional[str]
    type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class Run:
    id: str
    project_id: str
    stage_id: Optional[str]
    conversation_id: Optional[str]
    goal: str
    status: str = "created"
    created_at: datetime = field(default_factory=utcnow)
    failure_reason: Optional[str] = None
    failure_context: dict[str, Any] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    config_version_id: Optional[str] = None


@dataclass
class ConversationActionProposalRecord:
    id: str
    project_id: str
    stage_id: str
    conversation_id: str
    conversation_harness_version: str
    action_type: str
    title: str
    payload: dict[str, Any] = field(default_factory=dict)
    # pending | accepting | accepted | rejected
    # - pending: created, waiting for user confirm/reject
    # - accepting: atomically claimed by a confirm caller, run creation in flight
    # - accepted: run created, run_id set
    # - rejected: user declined, no run created
    status: str = "pending"
    requires_confirmation: bool = True
    run_id: Optional[str] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class StageResult:
    id: str
    project_id: str
    stage_id: str
    version_id: str
    base_version_id: Optional[str]
    run_id: str
    status: str = "draft"
    input_file_ids: list[str] = field(default_factory=list)
    evidence_item_ids: list[str] = field(default_factory=list)
    model_config: dict[str, Any] = field(default_factory=dict)
    skill_versions: dict[str, str] = field(default_factory=dict)
    autoresearch_record_ids: list[str] = field(default_factory=list)
    confirmation_ids: list[str] = field(default_factory=list)
    result_payload: dict[str, Any] = field(default_factory=dict)
    # L1-A: prompt runtime audit fields. prompt_hashes is the SHA-256 hex of
    # each PromptTemplate.body used for this Run, prompt_versions is the
    # per-prompt version string. Together with config_hash they let us
    # reconstruct the exact prompts that produced a given scenario_summary.
    prompt_hashes: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    summary: str = ""
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    locked_at: Optional[datetime] = None


@dataclass
class AutoResearchRecord:
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
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    note: Optional[str] = None
    edited_description: Optional[str] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    confirmed_at: Optional[datetime] = None


@dataclass
class FrozenEvalContract:
    """Versioned frozen evaluation contract — the immutable rules that gate
    AutoResearch patch acceptance.  Materialised from stage1_contract.py
    constants so the eval baseline is auditable and comparable across runs."""

    id: str  # "fec-xxxxxxxx"
    version: str  # "v1", "v2"…
    stage_id: str  # "proj-xxx-stage-1"
    frozen_fields: list[dict[str, Any]]  # [{rule_id, rule_type, description, parameters}]
    mutable_fields: list[str]  # sorted(_WHITELISTED_PATCH_FIELDS)
    created_at: datetime = field(default_factory=utcnow)
    created_by: str = "system"


@dataclass
class AutoResearchCandidate:
    """A candidate patch proposed during the AutoResearch refinement loop or
    the confirmation path.  Captures hypothesis, before/after metrics, and
    gate result so every optimisation step is reproducible and comparable."""

    id: str  # "cand-xxxxxxxx"
    project_id: str
    stage_id: str
    run_id: str
    change_type: str  # "enum_normalization" | "missing_field_add" | …
    target_stage: str  # "stage-1"
    hypothesis: str
    changed_refs: list[str]
    expected_effect: str
    must_not_change: list[str]
    status: str  # "proposed" | "applied" | "rejected" | "reverted"
    iteration: int  # 0-based in refine loop, -1 = confirmation path
    metrics_before: dict[str, Any] = field(default_factory=dict)
    metrics_after: dict[str, Any] = field(default_factory=dict)
    gate_result: str = ""  # "pass" | "fail" | "blocked"
    gate_reason: str = ""  # "" | "post_patch_validation_failed" | "L3_gate" | "not_whitelisted"
    human_review_status: str = "not_required"  # "not_required" | "pending" | "accepted" | "rejected"
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class RejectedCandidate:
    """Persisted record of a candidate that was rejected — the 'rejected
    candidate buffer' from the Bank-GAI AutoResearch Loop spec.  Captures
    failure reason, failed metrics, and reusable insights so failures become
    learning, not lost experience."""

    id: str  # "rc-xxxxxxxx"
    project_id: str
    stage_id: str
    candidate_id: str  # FK → AutoResearchCandidate.id
    rejection_reason: str  # "not_whitelisted" | "post_patch_validation_failed" | …
    failed_metrics: dict[str, Any] = field(default_factory=dict)
    hard_constraint_triggered: str = ""  # "" | "L3_risk" | "boundary_flag" | "audit_readiness<0.5"
    reusable_insights: list[str] = field(default_factory=list)
    retry_allowed: bool = True
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class RuleProposal:
    """L2: AutoResearch proposal to change a frozen eval rule.

    When a validation_issue is unpatchable via the data-layer
    ``_WHITELISTED_PATCH_FIELDS`` (i.e. ``_build_suggested_patch`` returns
    ``None``), the harness emits a RuleProposal asking the human reviewer
    to either add, modify, or deprecate a frozen rule.

    Lifecycle:
      * ``proposed``  — emitted by refine_stage1
      * ``accepted``  — human reviewer approved; next ``seed_frozen_eval_contract``
                        picks up the rule change
      * ``rejected``  — human reviewer declined; frozen rule stays as-is
      * ``superseded``— a newer proposal targets the same rule
    """

    id: str  # "rp-xxxxxxxx"
    project_id: str
    stage_id: str
    run_id: str
    proposal_kind: str  # "add_rule" | "modify_rule" | "deprecate_rule"
    target_rule_id: str  # e.g. "stage1-risk-level-enum"
    new_rule: Optional[dict[str, Any]] = None  # populated for add_rule/modify_rule
    rationale: str = ""  # why the rule should change
    supporting_metrics: dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"  # proposed | accepted | rejected | superseded
    human_review_status: str = "pending"  # not_required | pending | accepted | rejected
    created_at: datetime = field(default_factory=utcnow)
    accepted_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_rationale: str = ""


@dataclass
class CapabilityMutabilityContract:
    """L2/L3: gate for AutoResearch capability changes (prompt/tool/model/skill_version).

    Distinct from ``FrozenEvalContract`` which locks *data* fields
    (scenario_summary shape).  ``CapabilityMutabilityContract`` locks the
    conditions under which the harness can change *capability* fields
    (PromptTemplate.body, StageSkillProfile.enabled_tools, model.alias,
    skill.skill_version).

    Versioning is synchronised with ``FrozenEvalContract`` for the same
    ``stage_id`` — bumping one bumps the other.
    """

    id: str  # "cmc-xxxxxxxx"
    version: str  # "v1" | "v2" | …
    stage_id: str
    mutable_capabilities: list[str] = field(default_factory=list)
    capability_gates: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    created_by: str = "system"


@dataclass
class SkillRunComparison:
    """L4: same input under skill v(N) vs v(N+1) — quantify capability
    evolution's effect on quality.

    Created by :func:`compare_skill_runs` after :func:`run_skill_ab_comparison`
    runs the same input through two different skill versions.  Verdict
    summarises the delta in plain English for the human reviewer:

      * ``improved``  — audit_readiness_score v2 > v1 * 1.05
      * ``regressed`` — any quality dim v2 < v1 * 0.95
      * ``neutral``   — neither of the above
    """

    id: str  # "srcmp-xxxxxxxx"
    project_id: str
    stage_id: str
    skill_name: str
    run_id_v1: str
    version_v1: str
    run_id_v2: str
    version_v2: str
    input_payload_hash: str
    quality_v1: dict[str, float] = field(default_factory=dict)
    quality_v2: dict[str, float] = field(default_factory=dict)
    quality_delta: dict[str, float] = field(default_factory=dict)
    issue_count_v1: int = 0
    issue_count_v2: int = 0
    tool_call_diff: dict[str, int] = field(default_factory=dict)
    prompt_hashes_v1: dict[str, str] = field(default_factory=dict)
    prompt_hashes_v2: dict[str, str] = field(default_factory=dict)
    verdict: str = "neutral"  # "improved" | "regressed" | "neutral"
    verdict_reason: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class FileArtifact:
    id: str
    project_id: str
    filename: str
    content_type: str
    status: str = "uploaded"
    storage_path: Optional[str] = None
    size_bytes: int = 0
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class EvidenceItem:
    id: str
    project_id: str
    name: str
    source_type: str
    source_file_id: Optional[str] = None
    attachment_path: Optional[str] = None
    snippet: Optional[str] = None
    status: str = "parsed"
    review_note: Optional[str] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class ReportArtifact:
    id: str
    project_id: str
    title: str
    status: str = "draft"
    approval_check_passed: bool = False
    export_path: Optional[str] = None
    decision_card_path: Optional[str] = None
    evidence_directory_path: Optional[str] = None
    bundle_export_path: Optional[str] = None
    stage_result_ids: list[str] = field(default_factory=list)
    evidence_item_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class VisionParseResult:
    file_id: str
    project_id: str
    model: str
    structured_fields: dict[str, Any]
    evidence_fragments: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    to_confirm: list[dict[str, Any]] = field(default_factory=list)
    raw_response: str = ""


@dataclass
class ExecutionLog:
    id: str
    project_id: str
    action: str
    resource_type: str
    resource_id: str
    run_id: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class VersionLog:
    id: str
    project_id: str
    resource_type: str
    resource_id: str
    change_type: str
    summary: str
    run_id: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ModelProfile:
    """Per-role OpenAI-compatible LLM configuration."""

    role: str  # "general" | "vision" | "judge"
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    base_url: str = ""
    api_key: str = ""
    enabled: bool = True
    # Reasoning mode toggle. Defaults to True to preserve current behaviour
    # for reasoning models (MiniMax-M3 / DeepSeek-R1 / QwQ). When False the
    # harness sends extra_body={"chat_template_kwargs": {"enable_thinking":
    # False}} plus a system-prompt suffix that asks the model to skip the
    # <think>...</think> chain, so the JSON output is clean and our
    # _extract_json_object fallback isn't needed.
    reasoning_mode: bool = True


@dataclass
class PromptTemplate:
    """A prompt template version bound to a profile/category."""

    id: str
    category: str  # "system" | "stage" | "vision" | "judge" | "report" | "conversation"
    scope: str = ""  # e.g. stage name or skill name
    title: str = ""
    body: str = ""
    required_variables: list[str] = field(default_factory=list)
    skill_name: Optional[str] = None
    version: str = "v1"


@dataclass
class StageSkillProfile:
    """Per-stage Skill configuration bound to a registered skill."""

    stage_id: str
    primary_skill: str
    enabled_tools: list[str] = field(default_factory=list)
    enabled_subagents: list[str] = field(default_factory=list)
    auto_run_condition: str = "manual"  # manual | on_inputs_ready | auto
    harness_version: str = DEFAULT_AGENT_HARNESS_VERSION
    conversation_harness_version: str = DEFAULT_CONVERSATION_HARNESS_VERSION
    skill_versions: dict[str, str] = field(default_factory=dict)


@dataclass
class RunPolicy:
    """Project-level run, retention and audit policy."""

    require_change_reason: bool = True
    allow_locked_stage_rerun: bool = True
    min_audit_requirements: list[str] = field(
        default_factory=lambda: [
            "config_version_id",
            "model_alias",
            "prompt_hash",
            "skill_version",
        ]
    )
    # P3-b: 对话 Harness 上下文裁剪 limit，可经 settings 配置透传到 ConversationContextBuilder
    conversation_message_limit: int = 20
    conversation_evidence_item_limit: int = 50
    conversation_evidence_snippet_limit: int = 500
    conversation_run_event_limit: int = 30


@dataclass
class ProjectSettings:
    """A versioned settings record for a project.

    Status values:
      * ``draft``    - editable, never referenced by Runs.
      * ``published`` - referenced by new Runs as ``config_version_id``.
    """

    id: str
    project_id: str
    version_id: str
    base_version_id: Optional[str]
    status: str  # "draft" | "published"
    config_hash: str
    change_reason: str = ""
    models: list[ModelProfile] = field(default_factory=list)
    prompts: list[PromptTemplate] = field(default_factory=list)
    stage_skill_profiles: list[StageSkillProfile] = field(default_factory=list)
    run_policy: RunPolicy = field(default_factory=RunPolicy)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    published_at: Optional[datetime] = None
    created_by: str = "system"
