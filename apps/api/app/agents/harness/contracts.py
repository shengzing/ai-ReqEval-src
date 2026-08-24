"""Stable contracts for replaceable harness providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any, Protocol

from src.apps.api.app.core.harness_constants import DEFAULT_AGENT_HARNESS_VERSION


@dataclass
class HarnessRequest:
    project_id: str
    stage_id: str
    run_id: str
    goal: str
    stage_name: str
    skill_name: str
    skill_version: str = ""
    skill_description: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    enabled_tools: list[str] = field(default_factory=list)
    allowed_subagents: list[str] = field(default_factory=list)
    enabled_subagents: list[str] = field(default_factory=list)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    vision_results: list[dict[str, Any]] = field(default_factory=list)
    previous_stage_result: dict[str, Any] | None = None
    config_version_id: str = ""
    prompt_templates: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    prompt_hashes: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    # HCR-P1-02 配置溯源：primary_skill/enabled_skills 从冻结 snapshot 提取，
    # 与 skill_name（实际派发的 Skill）并存。仅审计/复现展示用。
    primary_skill: str = ""
    enabled_skills: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HarnessResult:
    harness_version: str
    graph_version: str
    plan: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    tool_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_result_items: list[dict[str, Any]] = field(default_factory=list)
    tool_failures: list[dict[str, Any]] = field(default_factory=list)
    tool_skips: list[dict[str, Any]] = field(default_factory=list)
    synthesized_payload: dict[str, Any] = field(default_factory=dict)
    validation_issues: list[dict[str, Any]] = field(default_factory=list)
    quality_scores: dict[str, Any] = field(default_factory=dict)
    subagent_results: list[dict[str, Any]] = field(default_factory=list)
    subagent_audits: list[dict[str, Any]] = field(default_factory=list)
    autoresearch_record_ids: list[str] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    effects: list[dict[str, Any]] = field(default_factory=list)
    checkpoint: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_legacy_state(self) -> dict[str, Any]:
        state = dict(self.raw)
        state.update(
            {
                "harness_version": self.harness_version,
                "graph_version": self.graph_version,
                "plan": dict(self.plan),
                "decision": dict(self.decision),
                "tool_results": dict(self.tool_results),
                "tool_result_items": [dict(item) for item in self.tool_result_items],
                "tool_failures": [dict(item) for item in self.tool_failures],
                "tool_skips": [dict(item) for item in self.tool_skips],
                "synthesized_payload": dict(self.synthesized_payload),
                "validation_issues": [dict(item) for item in self.validation_issues],
                "quality_scores": dict(self.quality_scores),
                "subagent_results": [dict(item) for item in self.subagent_results],
                "subagent_audits": [dict(item) for item in self.subagent_audits],
                "autoresearch_record_ids": list(self.autoresearch_record_ids),
                "traces": [dict(item) for item in self.traces],
                "effects": [dict(item) for item in self.effects],
                "checkpoint": dict(self.checkpoint),
            }
        )
        return state


class HarnessProvider(Protocol):
    version: str

    def run(self, request: HarnessRequest) -> HarnessResult:
        ...


@dataclass
class HarnessToolCall:
    tool_name: str
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessToolResult:
    tool_name: str
    success: bool
    status: str = "completed"  # completed | skipped_missing_input | failed
    name: str = ""
    summary: str = ""
    raw_output: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    audit: dict[str, Any] = field(default_factory=dict)

    def to_result_item(self) -> dict[str, Any]:
        return {
            "name": self.name or self.tool_name,
            "summary": self.summary,
            "raw_output": dict(self.raw_output),
            "evidence_refs": list(self.evidence_refs),
            "warnings": list(self.warnings),
            "status": self.status,
            "audit": dict(self.audit),
        }

    def to_failure_item(self) -> dict[str, Any]:
        failure = dict(self.failure or {})
        return {
            "tool_name": self.tool_name,
            "detail": str(failure.get("detail", self.summary or "Tool failed")),
            "status": self.status,
            "audit": dict(self.audit),
        }

    def to_skip_item(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "summary": self.summary,
            "warnings": list(self.warnings),
            "audit": dict(self.audit),
        }


@dataclass
class SubagentAuditRecord:
    subagent_name: str
    invocation_id: str
    status: str
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    failure: dict[str, Any] | None = None
    duration_ms: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    review_status: str = ""
    adoption_status: str = "not_adopted"
    adoption_reason: str = ""
    provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload_digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def summarize_subagent_input(
    *,
    goal: str,
    stage_name: str,
    tool_results: dict[str, Any],
    previous_stage_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a replay-safe input summary without persisting source material."""

    return {
        "goal_hash": _payload_digest(goal),
        "stage_name": stage_name,
        "tool_names": sorted(str(name) for name in tool_results),
        "tool_result_count": len(tool_results),
        "previous_stage_result_present": previous_stage_result is not None,
        "input_hash": _payload_digest({
            "goal": goal,
            "stage_name": stage_name,
            "tool_results": tool_results,
            "previous_stage_result": previous_stage_result,
        }),
    }


def collect_subagent_evidence_refs(tool_results: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for result in tool_results.values():
        if not isinstance(result, dict):
            continue
        for ref in result.get("evidence_refs", []):
            value = str(ref)
            if value and value not in refs:
                refs.append(value)
    return refs


def summarize_subagent_output(result: dict[str, Any]) -> dict[str, Any]:
    summary = str(result.get("summary", ""))
    return {
        "summary": summary[:500],
        "review_status": str(result.get("review_status", "")),
        "confidence": float(result.get("confidence", 0.0) or 0.0),
        "issue_count": len(result.get("issues", []) or []),
        "suggestion_count": len(result.get("suggestions", []) or []),
        "output_hash": _payload_digest(result),
    }


def build_skipped_subagent_audits(
    request: HarnessRequest,
    *,
    provider: str,
    reason: str,
) -> list[dict[str, Any]]:
    input_summary = summarize_subagent_input(
        goal=request.goal,
        stage_name=request.stage_name,
        tool_results={},
        previous_stage_result=request.previous_stage_result,
    )
    return [
        SubagentAuditRecord(
            subagent_name=name,
            invocation_id=f"subagent-{request.run_id}-{index}",
            status="skipped",
            input_summary=dict(input_summary),
            failure={"code": "provider_subagent_unsupported", "detail": reason},
            adoption_status="not_applicable",
            adoption_reason=reason,
            provider=provider,
        ).to_dict()
        for index, name in enumerate(request.enabled_subagents, start=1)
    ]


def harness_result_from_legacy_state(
    state: dict[str, Any],
    *,
    harness_version: str = DEFAULT_AGENT_HARNESS_VERSION,
) -> HarnessResult:
    return HarnessResult(
        harness_version=harness_version,
        graph_version=str(state.get("graph_version", "")),
        plan=dict(state.get("plan", {})),
        decision=dict(state.get("decision", {})),
        tool_results={str(key): dict(value) for key, value in dict(state.get("tool_results", {})).items()},
        tool_result_items=[dict(item) for item in state.get("tool_result_items", [])],
        tool_failures=[dict(item) for item in state.get("tool_failures", [])],
        tool_skips=[dict(item) for item in state.get("tool_skips", [])],
        synthesized_payload=dict(state.get("synthesized_payload", {})),
        validation_issues=[dict(item) for item in state.get("validation_issues", [])],
        quality_scores=dict(state.get("quality_scores", {})),
        subagent_results=[dict(item) for item in state.get("subagent_results", [])],
        subagent_audits=[dict(item) for item in state.get("subagent_audits", [])],
        autoresearch_record_ids=[str(item) for item in state.get("autoresearch_record_ids", [])],
        traces=[dict(item) for item in state.get("traces", [])],
        effects=[dict(item) for item in state.get("effects", [])],
        checkpoint=dict(state.get("checkpoint", {})),
        raw=dict(state),
    )
