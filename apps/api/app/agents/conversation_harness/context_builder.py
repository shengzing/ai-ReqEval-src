"""Build read-only context for stage conversation harness providers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status

from src.apps.api.app.agents.conversation_harness.contracts import ConversationHarnessRequest
from src.apps.api.app.agents.skills.registry import list_skills
from src.apps.api.app.core.harness_constants import DEFAULT_CONVERSATION_HARNESS_VERSION
from src.apps.api.app.domain.models import (
    ConversationMessage,
    EvidenceItem,
    Project,
    RunEvent,
    Stage,
    StageResult,
)
from src.apps.api.app.repositories import store
from src.apps.api.app.services import project_service, settings_service


DEFAULT_MESSAGE_LIMIT = 20
DEFAULT_EVIDENCE_ITEM_LIMIT = 50
DEFAULT_EVIDENCE_SNIPPET_LIMIT = 500
DEFAULT_RUN_EVENT_LIMIT = 30
DEFAULT_AVAILABLE_ACTIONS = [
    "propose_create_run",
    "propose_invoke_skill",
    "propose_request_human_confirmation",
]


def _message_to_dict(message: ConversationMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "source_event_id": message.source_event_id,
        "run_id": message.run_id,
    }


def _project_context(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "goal": project.goal,
        "status": project.status,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "stages": [
            {
                "id": stage.id,
                "name": stage.name,
                "status": stage.status,
                "objective": stage.objective,
            }
            for stage in project.stages
        ],
    }


def _stage_context(stage: Stage) -> dict[str, Any]:
    return {
        "id": stage.id,
        "project_id": stage.project_id,
        "name": stage.name,
        "status": stage.status,
        "objective": stage.objective,
        "created_at": stage.created_at.isoformat(),
    }


def _stage_result_context(stage_result: StageResult | None) -> dict[str, Any] | None:
    if stage_result is None:
        return None
    return {
        "id": stage_result.id,
        "project_id": stage_result.project_id,
        "stage_id": stage_result.stage_id,
        "version_id": stage_result.version_id,
        "base_version_id": stage_result.base_version_id,
        "run_id": stage_result.run_id,
        "status": stage_result.status,
        "result_payload": stage_result.result_payload,
        "summary": stage_result.summary,
        "skill_versions": dict(stage_result.skill_versions),
        "model_config": dict(stage_result.model_config),
        "created_at": stage_result.created_at.isoformat(),
        "updated_at": stage_result.updated_at.isoformat(),
        "locked_at": stage_result.locked_at.isoformat() if stage_result.locked_at else None,
    }


def _evidence_summary(evidence: EvidenceItem, snippet_limit: int) -> dict[str, Any]:
    snippet = evidence.snippet or ""
    return {
        "id": evidence.id,
        "project_id": evidence.project_id,
        "name": evidence.name,
        "source_type": evidence.source_type,
        "source_file_id": evidence.source_file_id,
        "status": evidence.status,
        "snippet": snippet[:snippet_limit],
        "review_note": evidence.review_note,
        "created_at": evidence.created_at.isoformat(),
        "updated_at": evidence.updated_at.isoformat(),
    }


def _run_event_summary(event: RunEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "project_id": event.project_id,
        "stage_id": event.stage_id,
        "conversation_id": event.conversation_id,
        "type": event.type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
    }


def _skill_summary(stage_id: str) -> list[dict[str, Any]]:
    return [
        {
            "name": skill.name,
            "stage_suffix": skill.stage_suffix,
            "description": skill.description,
            "input_schema": dict(skill.input_schema),
            "output_schema": dict(skill.output_schema),
            "allowed_tools": list(skill.allowed_tools),
            "allowed_subagents": list(skill.allowed_subagents),
            "auto_run_condition": skill.auto_run_condition,
            "visibility": skill.visibility,
        }
        for skill in list_skills(stage_id)
    ]


class ConversationContextBuilder:
    def __init__(
        self,
        *,
        message_limit: int = DEFAULT_MESSAGE_LIMIT,
        evidence_item_limit: int = DEFAULT_EVIDENCE_ITEM_LIMIT,
        evidence_snippet_limit: int = DEFAULT_EVIDENCE_SNIPPET_LIMIT,
        run_event_limit: int = DEFAULT_RUN_EVENT_LIMIT,
    ) -> None:
        self.message_limit = message_limit
        self.evidence_item_limit = evidence_item_limit
        self.evidence_snippet_limit = evidence_snippet_limit
        self.run_event_limit = run_event_limit

    def build(
        self,
        conversation_id: str,
        user_message: str,
        config_version_id: str | None = None,
    ) -> ConversationHarnessRequest:
        logger = logging.getLogger(__name__)
        logger.info(
            "[conversation_harness] ContextBuilder.build: start conversation_id=%s user_message_preview=%r",
            conversation_id, user_message[:80],
        )
        conversation = store.get_conversation(conversation_id)
        if conversation is None or conversation.status == "deleted":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation is not active",
            )
        # P3-b: 取 snapshot 提前到裁剪前，从 run_policy 透传 limit（缺字段回退 self 默认）
        stage = store.get_stage(conversation.stage_id)
        if stage is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
        project = project_service.get_project(conversation.project_id or stage.project_id)
        snapshot = settings_service.settings_snapshot(project.id, stage.id, config_version_id)
        # 日志:输出项目 settings 里的模型配置(明文 api_key 已打码),便于排查"LLM 未配置"问题
        _ocm_secrets = snapshot.get("openai_compatible_models", {}) or {}
        _ocm_safe = snapshot.get("model_config", {}).get("openai_compatible_models", {}) or {}
        logging.getLogger(__name__).info(
            "[conversation_harness] ContextBuilder.build: settings snapshot for project=%s stage=%s "
            "config_version_id=%s | openai_compatible_models(secrets) roles=%s | general secret: %s | general safe: %s",
            project.id, stage.id, snapshot.get("config_version_id"),
            list(_ocm_secrets.keys()),
            {k: ("***" if k == "api_key" and v else v) for k, v in (_ocm_secrets.get("general") or {}).items()},
            _ocm_safe.get("general"),
        )
        run_policy = snapshot.get("run_policy", {}) or {}
        self.message_limit = int(run_policy.get("conversation_message_limit", self.message_limit))
        self.evidence_item_limit = int(run_policy.get("conversation_evidence_item_limit", self.evidence_item_limit))
        self.evidence_snippet_limit = int(run_policy.get("conversation_evidence_snippet_limit", self.evidence_snippet_limit))
        self.run_event_limit = int(run_policy.get("conversation_run_event_limit", self.run_event_limit))

        stage_result = store.get_latest_stage_result(stage.id)
        evidence_items = store.list_evidence_items(project.id)
        # bound the number of evidence items; list_evidence_items returns
        # newest-first per repository ordering, so keep the most recent ones.
        truncated_evidence = evidence_items[: self.evidence_item_limit]
        run_events = store.list_run_events_by_conversation(conversation.id)
        effective_config_version_id = snapshot.get("config_version_id") or config_version_id or ""
        prompt_templates = dict(snapshot.get("prompt_bodies", {}))
        conversation_harness_version = (
            snapshot.get("conversation_harness_versions_by_stage", {}).get(stage.id)
            or snapshot.get("model_config", {})
            .get("conversation_harness_versions_by_stage", {})
            .get(stage.id)
            or DEFAULT_CONVERSATION_HARNESS_VERSION
        )

        request = ConversationHarnessRequest(
            project_id=project.id,
            stage_id=stage.id,
            conversation_id=conversation.id,
            user_message=user_message,
            message_history=[
                _message_to_dict(message)
                for message in conversation.messages[-self.message_limit :]
            ],
            project_context=_project_context(project),
            stage_context=_stage_context(stage),
            latest_stage_result=_stage_result_context(stage_result),
            evidence_summaries=[
                _evidence_summary(item, self.evidence_snippet_limit) for item in truncated_evidence
            ],
            recent_run_events=[
                _run_event_summary(event) for event in run_events[-self.run_event_limit :]
            ],
            available_skills=_skill_summary(stage.id),
            available_actions=list(DEFAULT_AVAILABLE_ACTIONS),
            config_version_id=effective_config_version_id,
            prompt_templates=prompt_templates,
            options={
                "conversation_harness_version": conversation_harness_version,
                "settings_snapshot": _compact_settings_snapshot(snapshot),
            },
        )
        request.to_dict()
        return request


def _compact_settings_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    # P3-c: 补全 model_config 供 deepagents/openharness provider 选 model
    # model_config.openai_compatible_models 是 safe 版本(只有 api_key_configured: bool)
    # 顶层 openai_compatible_models 是明文版本(含真实 api_key),供对话 Harness
    # 实例化 HarnessLLMClient 用项目 settings 配置而非全局 env。
    model_config = snapshot.get("model_config", {}) or {}
    return {
        "config_version_id": snapshot.get("config_version_id", ""),
        "config_hash": snapshot.get("config_hash", ""),
        "conversation_harness_versions_by_stage": dict(
            snapshot.get("conversation_harness_versions_by_stage", {})
        ),
        "harness_versions_by_stage": dict(snapshot.get("harness_versions_by_stage", {})),
        "skill_versions": dict(snapshot.get("skill_versions", {})),
        "model_config": {
            "llm_capability": model_config.get("llm_capability", "text"),
            "config_version_id": model_config.get("config_version_id", ""),
            "config_hash": model_config.get("config_hash", ""),
            "model_aliases": dict(model_config.get("model_aliases", {})),
            "openai_compatible_models": dict(model_config.get("openai_compatible_models", {})),
            "min_audit_requirements": list(model_config.get("min_audit_requirements", [])),
            "harness_versions_by_stage": dict(
                model_config.get("harness_versions_by_stage", {})
            ),
            "conversation_harness_versions_by_stage": dict(
                model_config.get("conversation_harness_versions_by_stage", {})
            ),
        },
        # 对话 Harness 实例化 LLM 客户端需要明文 api_key。注意:此 dict 会进入
        # ConversationHarnessRequest.options,经 request.to_dict() 做 jsonable 校验,
        # 但不会被写入 ConversationHarnessResult(结果只存 raw.llm_used),不会泄漏。
        # conversation_harness_service 写 execution_log 时 raw 来自 result,不含此字段。
        "openai_compatible_models_with_secrets": dict(snapshot.get("openai_compatible_models", {})),
    }
