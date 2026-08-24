"""Contracts for the internal agent harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.apps.api.app.agents.tools.registry import ToolResult


@dataclass
class HarnessTrace:
    event: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessPlan:
    tool_names: list[str]
    reasoning: str
    source: str = "fallback"


@dataclass
class HarnessStep:
    tool_name: str
    status: str
    result: ToolResult | None = None
    error: str | None = None


@dataclass
class LLMDecision:
    should_continue: bool
    summary: str
    confidence: float = 0.5
    notes: list[str] = field(default_factory=list)
    source: str = "fallback"


@dataclass
class HarnessExecutionResult:
    """State-first result returned by the LangGraph harness."""

    state: dict[str, Any] = field(default_factory=dict)

    @property
    def plan(self) -> HarnessPlan:
        plan = self.state.get("plan", {})
        return HarnessPlan(
            tool_names=list(plan.get("tool_names", [])),
            reasoning=str(plan.get("reasoning", "")),
            source=str(plan.get("source", "fallback")),
        )

    @property
    def decision(self) -> LLMDecision:
        decision = self.state.get("decision", {})
        return LLMDecision(
            should_continue=bool(decision.get("should_continue", False)),
            summary=str(decision.get("summary", "")),
            confidence=float(decision.get("confidence", 0.0)),
            notes=[str(item) for item in decision.get("notes", [])],
            source=str(decision.get("source", "fallback")),
        )

    @property
    def traces(self) -> list[HarnessTrace]:
        return [HarnessTrace(event=str(item.get("event", "")), payload=dict(item.get("payload", {}))) for item in self.state.get("traces", [])]

    @property
    def steps(self) -> list[HarnessStep]:
        result_by_name = {item["name"]: item for item in self.state.get("tool_result_items", [])}
        skip_by_name = {item["tool_name"]: item for item in self.state.get("tool_skips", [])}
        steps: list[HarnessStep] = []
        for tool_name in self.state.get("plan", {}).get("tool_names", []):
            failure = next((item for item in self.state.get("tool_failures", []) if item.get("tool_name") == tool_name), None)
            item = result_by_name.get(tool_name)
            if item is not None:
                steps.append(
                    HarnessStep(
                        tool_name=tool_name,
                        status="completed",
                        result=ToolResult(
                            name=item["name"],
                            summary=item["summary"],
                            raw_output=item["raw_output"],
                            evidence_refs=list(item.get("evidence_refs", [])),
                            warnings=list(item.get("warnings", [])),
                        ),
                    )
                )
            elif failure is not None:
                steps.append(HarnessStep(tool_name=tool_name, status="failed", error=str(failure.get("detail", "Tool failed"))))
            elif tool_name in skip_by_name:
                steps.append(HarnessStep(tool_name=tool_name, status="skipped", error=str(skip_by_name[tool_name].get("summary", "Tool skipped"))))
        return steps

    @property
    def tool_payload(self) -> dict[str, dict[str, Any]]:
        return dict(self.state.get("tool_results", {}))

    @property
    def tool_results(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.state.get("tool_result_items", [])]

    @property
    def failures(self) -> list[dict[str, str]]:
        return [
            {"tool_name": str(item.get("tool_name", "")), "detail": str(item.get("detail", "Tool failed"))}
            for item in self.state.get("tool_failures", [])
        ]


HarnessResult = HarnessExecutionResult
