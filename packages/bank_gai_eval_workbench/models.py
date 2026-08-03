from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectMeta:
    project_id: str
    name: str
    description: str
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    tags: list[str] = field(default_factory=list)


@dataclass
class ScenarioRecord:
    scenario_name: str
    scenario_type: str
    boundary: str
    sop_summary: str
    participants: list[str]
    responsibilities: list[str]
    risk_level: str
    hitl_level: str
    audit_requirements: list[str]


@dataclass
class ValueRecord:
    stakeholders: list[str]
    implementation_tax_items: list[dict[str, Any]]
    manual_baseline_cost: float
    ai_operating_cost: float
    expected_benefit: float
    target_sla: float | None = None
    sensitivity_notes: list[str] = field(default_factory=list)


@dataclass
class ProbeSample:
    sample_id: str
    task_name: str
    expected: str
    actual: str
    score: float
    severity: str
    manual_review_minutes: float
    passed: bool


@dataclass
class ProbeRecord:
    atomic_tasks: list[str]
    rubric: list[str]
    samples: list[ProbeSample]


@dataclass
class DecisionRecord:
    recommendation: str
    reason: str
    hard_constraints_passed: bool
    quality_score: float
    efficiency_score: float
    governance_score: float
    target_sla: float
    actual_sla: float


@dataclass
class ProcessingResult:
    implementation_tax_total: float
    net_value: float
    target_sla: float
    actual_sla: float
    quality_score: float
    efficiency_score: float
    governance_score: float
    decision: DecisionRecord


@dataclass
class VersionLogEntry:
    timestamp: str
    model: str
    role: str
    task: str
    notes: str


@dataclass
class ExecutionLogEntry:
    timestamp: str
    actor_type: str
    actor_name: str
    action: str
    project_id: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    project_version: str = "v0.1.1-mvp"
    note: str = ""


def to_dict(instance: Any) -> dict[str, Any]:
    return asdict(instance)
