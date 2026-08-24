"""Stable contracts for stage conversation harness providers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


SUPPORTED_CONVERSATION_ACTIONS = frozenset(
    {
        "propose_create_run",
        "propose_invoke_skill",
        "propose_request_human_confirmation",
    }
)


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


def normalize_citations(
    request: ConversationHarnessRequest,
    citations: Any,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Keep only citations that refer to the scoped request context."""
    if not isinstance(citations, list):
        return [], [{"code": "invalid_citations", "message": "Citations must be a list."}]

    latest_result_id = (
        str(request.latest_stage_result["id"])
        if request.latest_stage_result and request.latest_stage_result.get("id")
        else None
    )
    allowed_ids = {
        "project_context": {request.project_id},
        "stage_context": {request.stage_id},
        "latest_stage_result": {latest_result_id} if latest_result_id else set(),
        "evidence_summary": {
            str(item["id"])
            for item in request.evidence_summaries
            if isinstance(item, dict) and item.get("id")
        },
        "run_event": {
            str(item["id"])
            for item in request.recent_run_events
            if isinstance(item, dict) and item.get("id")
        },
        "available_skill": {
            str(item["name"])
            for item in request.available_skills
            if isinstance(item, dict) and item.get("name")
        },
    }
    cleaned: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            warnings.append({"code": "invalid_citation", "message": "Ignored malformed citation."})
            continue
        source = citation.get("source")
        identifier = citation.get("id")
        field = citation.get("field", "")
        if (
            not isinstance(source, str)
            or not isinstance(identifier, str)
            or identifier not in allowed_ids.get(source, set())
            or not isinstance(field, str)
        ):
            warnings.append({"code": "invalid_citation", "message": "Ignored out-of-scope citation."})
            continue
        cleaned.append({"source": source, "id": identifier, "field": field})
    return cleaned, warnings


def normalize_action_proposals(
    request: ConversationHarnessRequest,
    proposals: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Validate model-produced actions before they reach a confirmation route."""
    if not isinstance(proposals, list):
        return [], [{"code": "invalid_action_proposals", "message": "Action proposals must be a list."}]

    allowed_actions = set(request.available_actions) & SUPPORTED_CONVERSATION_ACTIONS
    available_skills = {
        str(item["name"])
        for item in request.available_skills
        if isinstance(item, dict) and item.get("name")
    }
    cleaned: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            warnings.append({"code": "invalid_action_proposal", "message": "Ignored malformed action proposal."})
            continue
        action_type = proposal.get("action_type")
        payload = proposal.get("payload", {})
        if action_type not in allowed_actions or not isinstance(payload, dict):
            warnings.append({"code": "invalid_action_proposal", "message": "Ignored unsupported action proposal."})
            continue

        title = proposal.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if action_type == "propose_create_run":
            goal = payload.get("goal")
            goal = goal.strip() if isinstance(goal, str) else ""
            cleaned.append(
                ConversationActionProposal(
                    action_type=action_type,
                    title=title or "创建阶段分析任务",
                    payload={
                        "goal": goal or request.user_message,
                        "config_version_id": request.config_version_id,
                    },
                ).to_dict()
            )
            continue

        if action_type == "propose_invoke_skill":
            skill_name = payload.get("skill_name")
            goal = payload.get("goal")
            if not isinstance(skill_name, str) or skill_name not in available_skills:
                warnings.append({"code": "invalid_action_proposal", "message": "Ignored unavailable Skill proposal."})
                continue
            cleaned.append(
                ConversationActionProposal(
                    action_type=action_type,
                    title=title or f"调用 {skill_name}",
                    payload={
                        "skill_name": skill_name,
                        "goal": goal.strip() if isinstance(goal, str) and goal.strip() else request.user_message,
                        "config_version_id": request.config_version_id,
                    },
                ).to_dict()
            )
            continue

        question = payload.get("question")
        if not isinstance(question, str) or not question.strip():
            warnings.append({"code": "invalid_action_proposal", "message": "Ignored confirmation without a question."})
            continue
        cleaned.append(
            ConversationActionProposal(
                action_type=action_type,
                title=title or "请求人工确认",
                payload={"question": question.strip()},
            ).to_dict()
        )
    return cleaned, warnings


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
