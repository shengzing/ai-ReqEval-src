"""Stable contracts for stage conversation harness providers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


def _assert_jsonable(value: Any) -> None:
    json.dumps(value, ensure_ascii=False)


@dataclass
class ConversationActionProposal:
    action_type: str
    title: str
    payload: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        _assert_jsonable(payload)
        return payload


@dataclass
class ConversationToolCall:
    tool_name: str
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        _assert_jsonable(payload)
        return payload


@dataclass
class ConversationToolResult:
    tool_name: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    failure: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        _assert_jsonable(payload)
        return payload


@dataclass
class ConversationHarnessRequest:
    project_id: str
    stage_id: str
    conversation_id: str
    user_message: str
    message_history: list[dict[str, Any]] = field(default_factory=list)
    project_context: dict[str, Any] = field(default_factory=dict)
    stage_context: dict[str, Any] = field(default_factory=dict)
    latest_stage_result: dict[str, Any] | None = None
    evidence_summaries: list[dict[str, Any]] = field(default_factory=list)
    recent_run_events: list[dict[str, Any]] = field(default_factory=list)
    available_skills: list[dict[str, Any]] = field(default_factory=list)
    available_actions: list[str] = field(default_factory=list)
    config_version_id: str = ""
    prompt_templates: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        _assert_jsonable(payload)
        return payload


@dataclass
class ConversationHarnessResult:
    conversation_harness_version: str
    runtime_version: str
    assistant_message: str
    intent: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    action_proposals: list[dict[str, Any]] = field(default_factory=list)
    effects: list[dict[str, Any]] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        _assert_jsonable(payload)
        return payload


class ConversationHarnessProvider(Protocol):
    version: str

    def run(self, request: ConversationHarnessRequest) -> ConversationHarnessResult:
        ...
