"""Stable contracts for replaceable harness providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    synthesized_payload: dict[str, Any] = field(default_factory=dict)
    validation_issues: list[dict[str, Any]] = field(default_factory=list)
    quality_scores: dict[str, Any] = field(default_factory=dict)
    subagent_results: list[dict[str, Any]] = field(default_factory=list)
    autoresearch_record_ids: list[str] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    effects: list[dict[str, Any]] = field(default_factory=list)
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
                "synthesized_payload": dict(self.synthesized_payload),
                "validation_issues": [dict(item) for item in self.validation_issues],
                "quality_scores": dict(self.quality_scores),
                "subagent_results": [dict(item) for item in self.subagent_results],
                "autoresearch_record_ids": list(self.autoresearch_record_ids),
                "traces": [dict(item) for item in self.traces],
                "effects": [dict(item) for item in self.effects],
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
        }

    def to_failure_item(self) -> dict[str, Any]:
        failure = dict(self.failure or {})
        return {
            "tool_name": self.tool_name,
            "detail": str(failure.get("detail", self.summary or "Tool failed")),
        }


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
        synthesized_payload=dict(state.get("synthesized_payload", {})),
        validation_issues=[dict(item) for item in state.get("validation_issues", [])],
        quality_scores=dict(state.get("quality_scores", {})),
        subagent_results=[dict(item) for item in state.get("subagent_results", [])],
        autoresearch_record_ids=[str(item) for item in state.get("autoresearch_record_ids", [])],
        traces=[dict(item) for item in state.get("traces", [])],
        effects=[dict(item) for item in state.get("effects", [])],
        raw=dict(state),
    )
