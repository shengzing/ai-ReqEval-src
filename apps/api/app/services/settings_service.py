"""Project settings service.

Implements the project-level settings (model profiles, prompt templates,
stage skill profiles, run policy) lifecycle described in
``SET-P0-01`` and ``SET-P0-02``.

Design notes
------------
* A project must always have exactly one *latest* ``published`` settings
  record. Drafts are optional and may be created on demand.
* ``published`` settings are immutable. Editing a published settings
  creates a new ``draft`` whose ``base_version_id`` references the latest
  published one.
* ``config_hash`` is computed over the canonicalised payload (sorted
  JSON). Changing the content changes the hash; identical content yields
  the same hash.
* API keys, real secrets and cleartext credentials are explicitly NOT
  persisted. ``ModelProfile`` only stores model aliases and capability
  flags - the secret material lives in backend ``.env`` files.
"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from typing import Any, Iterable, Optional
from uuid import uuid4

from fastapi import HTTPException, status

from src.apps.api.app.agents.skills.registry import (
    SKILL_DEFINITIONS,
    get_skill_by_name,
    get_skill_for_stage,
)
from src.apps.api.app.core.harness_constants import (
    DEFAULT_AGENT_HARNESS_VERSION,
    DEFAULT_CONVERSATION_HARNESS_VERSION,
)
from src.apps.api.app.domain.models import (
    ModelProfile,
    Project,
    ProjectSettings,
    PromptTemplate,
    RunPolicy,
    Stage,
    StageSkillProfile,
    utcnow,
)

logger = logging.getLogger(__name__)
from src.apps.api.app.repositories.store import (
    get_latest_draft_settings,
    get_latest_published_settings,
    get_project as repo_get_project,
    get_project_settings,
    list_project_settings,
    list_stages,
    save_project_settings,
)
from src.apps.api.app.services.log_service import create_execution_log, create_version_log


def _require_project(project_id: str) -> Project:
    project = repo_get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project

# ---------------------------------------------------------------------------
# Default model catalogue
# ---------------------------------------------------------------------------

DEFAULT_MODEL_OPTIONS: list[dict[str, Any]] = [
    {
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "base_url": "",
    },
    {
        "provider": "openai",
        "model_name": "gpt-4o",
        "base_url": "",
    },
    {
        "provider": "openai",
        "model_name": "gpt-4.1",
        "base_url": "",
    },
]

DEFAULT_MODEL_PROFILES: list[ModelProfile] = [
    ModelProfile(
        role="general",
        provider="openai",
        model_name="gpt-4o-mini",
        base_url="",
        api_key="",
        enabled=True,
        reasoning_mode=True,
    ),
    ModelProfile(
        role="vision",
        provider="openai",
        model_name="gpt-4o",
        base_url="",
        api_key="",
        enabled=True,
        reasoning_mode=True,
    ),
    ModelProfile(
        role="judge",
        provider="openai",
        model_name="gpt-4.1",
        base_url="",
        api_key="",
        enabled=False,
        reasoning_mode=True,
    ),
]


# ---------------------------------------------------------------------------
# Default prompt templates
# ---------------------------------------------------------------------------

DEFAULT_PROMPT_TEMPLATES: list[PromptTemplate] = [
    PromptTemplate(
        id="prompt-system",
        category="system",
        scope="system",
        title="系统提示词",
        body=(
            "你是 AI ReqEval 的评估助手，目标是把项目目标拆解为阶段任务并产出可追溯结论。"
            "请始终引用证据片段、保持中文输出，并在不确定时标记为 to_confirm。"
        ),
        required_variables=["project_goal"],
        version="v1",
    ),
    PromptTemplate(
        id="prompt-stage-1",
        category="stage",
        scope="stage-1",
        title="阶段一：场景解构与风险定级",
        body=(
            "请基于 {{project_goal}} 描述 {{stage_objective}}，"
            "参考 {{previous_stage_result}} 与 {{evidence_summary}}，"
            "输出场景边界、风险等级、HITL 与审计要求。"
        ),
        required_variables=[
            "project_goal",
            "stage_objective",
            "evidence_summary",
            "previous_stage_result",
        ],
        skill_name="scenario_risk_skill",
        version="v1",
    ),
    PromptTemplate(
        id="prompt-stage-2",
        category="stage",
        scope="stage-2",
        title="阶段二：价值建模与目标 SLA",
        body=(
            "请结合 {{project_goal}} 与 {{previous_stage_result}} 计算 {{stage_objective}}，"
            "汇总 {{evidence_summary}}，输出价值结论、目标 SLA 与实施税。"
        ),
        required_variables=[
            "project_goal",
            "stage_objective",
            "evidence_summary",
            "previous_stage_result",
        ],
        skill_name="value_modeling_skill",
        version="v1",
    ),
    PromptTemplate(
        id="prompt-stage-3",
        category="stage",
        scope="stage-3",
        title="阶段三：任务拆解与微型探针",
        body=(
            "请基于 {{project_goal}} 与 {{previous_stage_result}} 完成 {{stage_objective}}，"
            "参考 {{evidence_summary}}，生成任务台账、样本评分与 Actual SLA 摘要。"
        ),
        required_variables=[
            "project_goal",
            "stage_objective",
            "evidence_summary",
            "previous_stage_result",
        ],
        skill_name="probe_validation_skill",
        version="v1",
    ),
    PromptTemplate(
        id="prompt-stage-4",
        category="stage",
        scope="stage-4",
        title="阶段四：三维对齐与报告",
        body=(
            "请基于 {{project_goal}} 与 {{previous_stage_result}} 完成 {{stage_objective}}，"
            "汇总 {{evidence_summary}}，输出决策建议、证据链摘要与报告草稿。"
        ),
        required_variables=[
            "project_goal",
            "stage_objective",
            "evidence_summary",
            "previous_stage_result",
        ],
        skill_name="evidence_decision_skill",
        version="v1",
    ),
    PromptTemplate(
        id="prompt-vision",
        category="vision",
        scope="vision",
        title="视觉解析提示词",
        body=(
            "请解析图片 {{evidence_summary}}，"
            "输出结构化字段、证据片段、不确定项与待确认字段。"
        ),
        required_variables=["evidence_summary"],
        version="v1",
    ),
    PromptTemplate(
        id="prompt-judge",
        category="judge",
        scope="judge",
        title="Judge 校准提示词",
        body=(
            "请基于 {{previous_stage_result}} 与 {{evidence_summary}} 输出辅助判断，"
            "不要直接改写最终结论。"
        ),
        required_variables=[
            "previous_stage_result",
            "evidence_summary",
        ],
        version="v1",
    ),
    PromptTemplate(
        id="prompt-report",
        category="report",
        scope="report",
        title="报告生成提示词",
        body=(
            "请基于 {{previous_stage_result}} 与 {{evidence_summary}} 生成报告草稿，"
            "保留阶段引用、证据引用与建议结论。"
        ),
        required_variables=[
            "previous_stage_result",
            "evidence_summary",
        ],
        version="v1",
    ),
    PromptTemplate(
        id="prompt-conversation-reply",
        category="conversation",
        scope="conversation",
        title="阶段对话回复提示词",
        body=(
            "你是 AI ReqEval 的阶段对话助手。请基于所提供的项目上下文、阶段上下文、"
            "最新阶段结果、证据摘要、历史消息等上下文，用中文回答用户当前的问题。\n\n"
            "必须返回如下 JSON 结构：\n"
            '{"reply": "给用户的中文回复", "action_proposals": []}\n\n'
            "回复要求：\n"
            "- 始终用中文回复；\n"
            "- 引用上下文中的具体信息（如阶段名称、风险等级、证据片段），不要编造上下文中没有的内容；\n"
            "- 不确定时在 reply 中明确标注“待确认”；\n"
            "- 回复聚焦用户问题，简洁清晰。\n\n"
            "受控动作要求：\n"
            "- 仅当用户明确要求重新分析 / 重跑 / 再跑一次时，才在 action_proposals 中放入一个对象：\n"
            '  {"action_type": "propose_create_run", "title": "创建阶段分析任务", '
            '"payload": {"goal": "用户原话"}, "requires_confirmation": true}\n'
            "- 其他情况下 action_proposals 必须为空数组，不要凭空生成其他 action_type。"
        ),
        required_variables=["user_message"],
        version="v1",
    ),
]


# ---------------------------------------------------------------------------
# Stage skill profiles
# ---------------------------------------------------------------------------

REQUIRED_VARIABLES = [
    "project_goal",
    "stage_objective",
    "evidence_summary",
    "previous_stage_result",
]


def _stage_default_profile(stage: Stage) -> StageSkillProfile:
    skill = get_skill_for_stage(stage.id)
    return StageSkillProfile(
        stage_id=stage.id,
        primary_skill=skill.name,
        enabled_tools=list(skill.allowed_tools),
        enabled_subagents=list(skill.allowed_subagents),
        auto_run_condition="manual",
        harness_version=DEFAULT_AGENT_HARNESS_VERSION,
        conversation_harness_version=DEFAULT_CONVERSATION_HARNESS_VERSION,
        skill_versions={skill.name: "mvp-v1"},
    )


def _build_default_settings(project_id: str) -> ProjectSettings:
    stages = list_stages(project_id)
    profiles = [_stage_default_profile(stage) for stage in stages]
    return ProjectSettings(
        id=f"settings-{uuid4().hex[:8]}",
        project_id=project_id,
        version_id=f"setv-{uuid4().hex[:8]}",
        base_version_id=None,
        status="published",
        config_hash="",  # filled below
        change_reason="Initial system default settings.",
        models=deepcopy(DEFAULT_MODEL_PROFILES),
        prompts=deepcopy(DEFAULT_PROMPT_TEMPLATES),
        stage_skill_profiles=profiles,
        run_policy=RunPolicy(),
        created_by="system",
        published_at=utcnow(),
    )


def _canonical_payload(settings: ProjectSettings) -> dict[str, Any]:
    payload = {
        "models": [_model_to_dict(model) for model in settings.models],
        "prompts": [_prompt_to_dict(prompt) for prompt in settings.prompts],
        "stage_skill_profiles": [
            _stage_skill_to_dict(profile) for profile in settings.stage_skill_profiles
        ],
        "run_policy": _policy_to_dict(settings.run_policy),
    }
    return _jsonable(payload)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _model_to_dict(model: ModelProfile) -> dict[str, Any]:
    return {
        "role": model.role,
        "provider": "openai",
        "model_name": model.model_name,
        "base_url": model.base_url,
        "api_key": model.api_key,
        "enabled": model.enabled,
        "reasoning_mode": model.reasoning_mode,
    }


def _prompt_to_dict(prompt: PromptTemplate) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "category": prompt.category,
        "scope": prompt.scope,
        "title": prompt.title,
        "body": prompt.body,
        "required_variables": list(prompt.required_variables),
        "skill_name": prompt.skill_name,
        "version": prompt.version,
    }


def _stage_skill_to_dict(profile: StageSkillProfile) -> dict[str, Any]:
    return {
        "stage_id": profile.stage_id,
        "primary_skill": profile.primary_skill,
        "enabled_tools": sorted(profile.enabled_tools),
        "enabled_subagents": sorted(profile.enabled_subagents),
        "auto_run_condition": profile.auto_run_condition,
        "harness_version": profile.harness_version,
        "conversation_harness_version": profile.conversation_harness_version,
        "skill_versions": dict(profile.skill_versions),
    }


def _policy_to_dict(policy: RunPolicy) -> dict[str, Any]:
    return {
        "require_change_reason": policy.require_change_reason,
        "allow_locked_stage_rerun": policy.allow_locked_stage_rerun,
        "min_audit_requirements": list(policy.min_audit_requirements),
    }


def compute_config_hash(settings: ProjectSettings) -> str:
    """Deterministic SHA-256 hash of the canonicalised settings payload."""
    payload = _canonical_payload(settings)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class SettingsValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _validate_models(models: Iterable[ModelProfile]) -> list[ModelProfile]:
    seen_roles: set[str] = set()
    cleaned: list[ModelProfile] = []
    for model in models:
        if model.role in seen_roles:
            raise SettingsValidationError(f"Duplicate model role: {model.role}")
        seen_roles.add(model.role)
        if model.role not in {"general", "vision", "judge"}:
            raise SettingsValidationError(f"Unsupported model role: {model.role}")
        model.provider = "openai"
        model.model_name = model.model_name.strip()
        model.base_url = model.base_url.strip()
        model.api_key = model.api_key.strip()
        if not model.model_name:
            raise SettingsValidationError("Model name cannot be empty")
        if model.base_url and not model.base_url.startswith(("http://", "https://")):
            raise SettingsValidationError("Model Base URL must start with http:// or https://")
        cleaned.append(model)
    return cleaned


def _validate_prompts(prompts: Iterable[PromptTemplate]) -> list[PromptTemplate]:
    seen_ids: set[str] = set()
    cleaned: list[PromptTemplate] = []
    for prompt in prompts:
        if prompt.id in seen_ids:
            raise SettingsValidationError(f"Duplicate prompt id: {prompt.id}")
        seen_ids.add(prompt.id)
        if prompt.category not in {"system", "stage", "vision", "judge", "report", "conversation"}:
            raise SettingsValidationError(f"Unsupported prompt category: {prompt.category}")
        if not prompt.body.strip():
            raise SettingsValidationError(f"Prompt body cannot be empty: {prompt.id}")
        if not prompt.required_variables:
            raise SettingsValidationError(f"Prompt must declare required_variables: {prompt.id}")
        if prompt.category == "stage":
            missing = [var for var in REQUIRED_VARIABLES if f"{{{{{var}}}}}" not in prompt.body]
            if missing:
                raise SettingsValidationError(
                    f"Stage prompt body must include placeholders for {sorted(missing)}: {prompt.id}"
                )
        cleaned.append(prompt)
    return cleaned


def _validate_stage_skill_profiles(
    profiles: Iterable[StageSkillProfile],
    *,
    available_stages: list[str],
) -> list[StageSkillProfile]:
    seen_stages: set[str] = set()
    cleaned: list[StageSkillProfile] = []
    known_skill_names = {definition.name for definition in SKILL_DEFINITIONS}
    for profile in profiles:
        if profile.stage_id in seen_stages:
            raise SettingsValidationError(f"Duplicate stage skill profile: {profile.stage_id}")
        seen_stages.add(profile.stage_id)
        if available_stages and profile.stage_id not in available_stages:
            raise SettingsValidationError(f"Unknown stage_id: {profile.stage_id}")
        if profile.primary_skill not in known_skill_names:
            raise SettingsValidationError(f"Unknown primary skill: {profile.primary_skill}")
        skill = get_skill_by_name(profile.primary_skill)
        illegal_tools = sorted(set(profile.enabled_tools) - set(skill.allowed_tools))
        if illegal_tools:
            raise SettingsValidationError(
                f"enabled_tools must be a subset of {skill.name}.allowed_tools, illegal: {illegal_tools}"
            )
        illegal_subagents = sorted(set(profile.enabled_subagents) - set(skill.allowed_subagents))
        if illegal_subagents:
            raise SettingsValidationError(
                f"enabled_subagents must be a subset of {skill.name}.allowed_subagents, illegal: {illegal_subagents}"
            )
        if profile.auto_run_condition not in {"manual", "on_inputs_ready", "auto"}:
            raise SettingsValidationError(
                f"Invalid auto_run_condition: {profile.auto_run_condition}"
            )
        from src.apps.api.app.agents.harness.registry import list_harness_versions
        from src.apps.api.app.agents.conversation_harness.registry import list_conversation_harness_versions

        if profile.harness_version not in set(list_harness_versions()):
            raise SettingsValidationError(
                f"Invalid harness_version: {profile.harness_version}"
            )
        if profile.conversation_harness_version not in set(list_conversation_harness_versions()):
            raise SettingsValidationError(
                f"Invalid conversation_harness_version: {profile.conversation_harness_version}"
            )
        cleaned.append(profile)
    return cleaned


def _validate_run_policy(policy: RunPolicy) -> RunPolicy:
    minimum = {"config_version_id", "model_alias", "prompt_hash", "skill_version"}
    missing = minimum - set(policy.min_audit_requirements)
    if missing:
        raise SettingsValidationError(
            f"Run policy must keep minimum audit requirements, missing: {sorted(missing)}"
        )
    return policy


def validate_settings_payload(
    settings: ProjectSettings,
    *,
    available_stages: Optional[list[str]] = None,
) -> ProjectSettings:
    settings.models = _validate_models(settings.models)
    settings.prompts = _validate_prompts(settings.prompts)
    settings.stage_skill_profiles = _validate_stage_skill_profiles(
        settings.stage_skill_profiles,
        available_stages=available_stages or [],
    )
    settings.run_policy = _validate_run_policy(settings.run_policy)
    settings.config_hash = compute_config_hash(settings)
    return settings


# ---------------------------------------------------------------------------
# Service-level API
# ---------------------------------------------------------------------------


def ensure_default_settings(project_id: str) -> ProjectSettings:
    """Return the latest published settings, creating defaults if missing.

    P1-11: 命中已发布 settings 时也走一次版本注册性兜底，避免历史数据
    含已下线版本一路透传到运行时 409/422。
    """
    latest = get_latest_published_settings(project_id)
    if latest is not None:
        latest.stage_skill_profiles = _sanitize_registered_versions(latest.stage_skill_profiles)
        return latest
    settings = _build_default_settings(project_id)
    stages = list_stages(project_id)
    available_stage_ids = [stage.id for stage in stages]
    settings.stage_skill_profiles = _validate_stage_skill_profiles(
        settings.stage_skill_profiles,
        available_stages=available_stage_ids,
    )
    settings.config_hash = compute_config_hash(settings)
    save_project_settings(settings)
    create_execution_log(
        project_id=project_id,
        action="project_settings.published",
        resource_type="project_settings",
        resource_id=settings.id,
        details={"version_id": settings.version_id, "config_hash": settings.config_hash, "source": "system-default"},
    )
    return settings


def get_latest_settings(project_id: str) -> ProjectSettings:
    _ = _require_project(project_id)
    latest = get_latest_published_settings(project_id) or get_latest_draft_settings(project_id)
    if latest is None:
        latest = ensure_default_settings(project_id)
    return latest


def get_draft_settings(project_id: str) -> Optional[ProjectSettings]:
    """Return the latest *explicit* draft, or ``None`` if no draft exists yet.

    A draft is only created when the user explicitly saves one via
    ``POST /settings/draft`` or ``POST /settings/reset``. Auto-cloning a
    draft on read would let the API return a "fake" draft that the user
    has not actually authored, which breaks the ``has_draft`` contract.
    """
    _ = _require_project(project_id)
    return get_latest_draft_settings(project_id)


def get_settings_versions(project_id: str) -> list[ProjectSettings]:
    _ = _require_project(project_id)
    return list_project_settings(project_id)


def _clone_as_draft(base: ProjectSettings) -> ProjectSettings:
    clone = deepcopy(base)
    clone.id = f"settings-{uuid4().hex[:8]}"
    clone.version_id = f"setv-{uuid4().hex[:8]}"
    clone.base_version_id = base.version_id
    clone.status = "draft"
    clone.change_reason = ""
    clone.published_at = None
    clone.created_at = utcnow()
    clone.updated_at = clone.created_at
    clone.created_by = "user-draft"
    clone.config_hash = compute_config_hash(clone)
    return clone


def _apply_to_draft(
    existing: ProjectSettings,
    base: ProjectSettings,
    *,
    models: list[ModelProfile],
    prompts: list[PromptTemplate],
    stage_skill_profiles: list[StageSkillProfile],
    run_policy: RunPolicy,
    change_reason: str,
    created_by: str,
) -> ProjectSettings:
    """Mutate the existing draft in place, keeping its id/version_id stable.

    Repeated saves reuse the same draft document so the project_settings
    collection does not accumulate orphan draft records.
    """
    draft = existing
    draft.base_version_id = base.version_id
    draft.status = "draft"
    draft.published_at = None
    draft.updated_at = utcnow()
    draft.created_by = created_by
    draft.models = list(models)
    draft.prompts = list(prompts)
    draft.stage_skill_profiles = list(stage_skill_profiles)
    draft.run_policy = run_policy
    draft.change_reason = change_reason
    return draft


def save_settings_draft(
    *,
    project_id: str,
    models: list[ModelProfile],
    prompts: list[PromptTemplate],
    stage_skill_profiles: list[StageSkillProfile],
    run_policy: RunPolicy,
    change_reason: str = "",
    created_by: str = "user",
) -> ProjectSettings:
    _ = _require_project(project_id)
    available_stages = [stage.id for stage in list_stages(project_id)]
    base = get_latest_published_settings(project_id) or ensure_default_settings(project_id)
    existing_draft = get_latest_draft_settings(project_id)
    if existing_draft is not None:
        draft = _apply_to_draft(
            existing_draft,
            base,
            models=models,
            prompts=prompts,
            stage_skill_profiles=stage_skill_profiles,
            run_policy=run_policy,
            change_reason=change_reason,
            created_by=created_by,
        )
    else:
        draft = _clone_as_draft(base)
        draft.models = list(models)
        draft.prompts = list(prompts)
        draft.stage_skill_profiles = list(stage_skill_profiles)
        draft.run_policy = run_policy
        draft.change_reason = change_reason
        draft.created_by = created_by
    draft = validate_settings_payload(draft, available_stages=available_stages)
    save_project_settings(draft)
    create_execution_log(
        project_id=project_id,
        action="project_settings.draft_saved",
        resource_type="project_settings",
        resource_id=draft.id,
        details={
            "version_id": draft.version_id,
            "base_version_id": draft.base_version_id,
            "config_hash": draft.config_hash,
        },
    )
    return draft


def reset_settings_draft(project_id: str) -> ProjectSettings:
    _ = _require_project(project_id)
    base = get_latest_published_settings(project_id) or ensure_default_settings(project_id)
    default_settings = _build_default_settings(project_id)
    existing_draft = get_latest_draft_settings(project_id)
    if existing_draft is not None:
        draft = _apply_to_draft(
            existing_draft,
            base,
            models=deepcopy(default_settings.models),
            prompts=deepcopy(default_settings.prompts),
            stage_skill_profiles=deepcopy(default_settings.stage_skill_profiles),
            run_policy=deepcopy(default_settings.run_policy),
            change_reason="Reset to system default configuration.",
            created_by="user-reset",
        )
    else:
        draft = _clone_as_draft(base)
        draft.models = deepcopy(default_settings.models)
        draft.prompts = deepcopy(default_settings.prompts)
        draft.stage_skill_profiles = deepcopy(default_settings.stage_skill_profiles)
        draft.run_policy = deepcopy(default_settings.run_policy)
        draft.change_reason = "Reset to system default configuration."
    available_stages = [stage.id for stage in list_stages(project_id)]
    draft = validate_settings_payload(draft, available_stages=available_stages)
    save_project_settings(draft)
    create_execution_log(
        project_id=project_id,
        action="project_settings.draft_reset",
        resource_type="project_settings",
        resource_id=draft.id,
        details={"version_id": draft.version_id, "base_version_id": draft.base_version_id},
    )
    return draft


def publish_settings_draft(
    *,
    project_id: str,
    draft_id: str,
    change_reason: str,
    require_change_reason: bool = True,
) -> ProjectSettings:
    _ = _require_project(project_id)
    if require_change_reason and not change_reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="change_reason is required to publish settings",
        )
    draft = get_project_settings(draft_id)
    if draft is None or draft.project_id != project_id or draft.status != "draft":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settings draft not found")
    available_stages = [stage.id for stage in list_stages(project_id)]
    draft = validate_settings_payload(draft, available_stages=available_stages)
    now = utcnow()
    draft.status = "published"
    draft.published_at = now
    draft.updated_at = now
    # P1-12: 直接赋 strip 后的值，避免 `or draft.change_reason` 静默沿用旧值
    # 掩盖用户传空字符串想清空的意图。require_change_reason=True 时 L727 已挡空。
    draft.change_reason = change_reason.strip()
    save_project_settings(draft)
    create_execution_log(
        project_id=project_id,
        action="project_settings.published",
        resource_type="project_settings",
        resource_id=draft.id,
        details={
            "version_id": draft.version_id,
            "config_hash": draft.config_hash,
            "change_reason": draft.change_reason,
        },
    )
    create_version_log(
        project_id=project_id,
        resource_type="project_settings",
        resource_id=draft.id,
        change_type="published",
        summary="Project settings published.",
        details={
            "version_id": draft.version_id,
            "config_hash": draft.config_hash,
            "version_scope": "project_settings",
            "change_reason": draft.change_reason,
        },
    )
    return draft


def build_settings_impact(project_id: str) -> dict[str, Any]:
    """Summarise how unpublished draft changes would affect new Runs."""
    _ = _require_project(project_id)
    latest_published = get_latest_published_settings(project_id)
    draft = get_latest_draft_settings(project_id)
    if draft is None:
        return {
            "project_id": project_id,
            "has_draft": False,
            "impacted_stages": [],
            "impacted_models": [],
            "impacted_prompts": [],
            "impacted_policy_keys": [],
            "summary": "No draft pending; current published settings are in effect.",
        }
    base = latest_published
    if base is None:
        # No published yet: compare draft against system defaults in memory.
        base = _build_default_settings(project_id)
    impacted_stages = _diff_stage_profiles(base, draft)
    impacted_models = _diff_models(base, draft)
    impacted_prompts = _diff_prompts(base, draft)
    impacted_policy = _diff_run_policy(base, draft)
    return {
        "project_id": project_id,
        "draft_id": draft.id,
        "draft_version_id": draft.version_id,
        "has_draft": True,
        "impacted_stages": impacted_stages,
        "impacted_models": impacted_models,
        "impacted_prompts": impacted_prompts,
        "impacted_policy_keys": impacted_policy,
        "summary": "Unpublished draft detected; new Runs will still use the published settings until publish.",
    }


def _diff_models(base: ProjectSettings, draft: ProjectSettings) -> list[dict[str, Any]]:
    base_map = {model.role: model for model in base.models}
    draft_map = {model.role: model for model in draft.models}
    changes: list[dict[str, Any]] = []
    for role in sorted(set(base_map) | set(draft_map)):
        base_model = base_map.get(role)
        draft_model = draft_map.get(role)
        if base_model is None and draft_model is not None:
            changes.append({"role": role, "change_type": "added", "draft": _model_to_dict(draft_model)})
            continue
        if draft_model is None and base_model is not None:
            changes.append({"role": role, "change_type": "removed", "base": _model_to_dict(base_model)})
            continue
        assert base_model is not None and draft_model is not None
        if _model_to_dict(base_model) != _model_to_dict(draft_model):
            changes.append(
                {
                    "role": role,
                    "change_type": "modified",
                    "base": _model_to_dict(base_model),
                    "draft": _model_to_dict(draft_model),
                }
            )
    return changes


def _diff_prompts(base: ProjectSettings, draft: ProjectSettings) -> list[dict[str, Any]]:
    base_map = {prompt.id: prompt for prompt in base.prompts}
    draft_map = {prompt.id: prompt for prompt in draft.prompts}
    changes: list[dict[str, Any]] = []
    for prompt_id in sorted(set(base_map) | set(draft_map)):
        base_prompt = base_map.get(prompt_id)
        draft_prompt = draft_map.get(prompt_id)
        if base_prompt is None and draft_prompt is not None:
            changes.append({"prompt_id": prompt_id, "change_type": "added"})
            continue
        if draft_prompt is None and base_prompt is not None:
            changes.append({"prompt_id": prompt_id, "change_type": "removed"})
            continue
        assert base_prompt is not None and draft_prompt is not None
        if _prompt_to_dict(base_prompt) != _prompt_to_dict(draft_prompt):
            changes.append({"prompt_id": prompt_id, "change_type": "modified"})
    return changes


def _diff_stage_profiles(base: ProjectSettings, draft: ProjectSettings) -> list[dict[str, Any]]:
    base_map = {profile.stage_id: profile for profile in base.stage_skill_profiles}
    draft_map = {profile.stage_id: profile for profile in draft.stage_skill_profiles}
    changes: list[dict[str, Any]] = []
    for stage_id in sorted(set(base_map) | set(draft_map)):
        base_profile = base_map.get(stage_id)
        draft_profile = draft_map.get(stage_id)
        if base_profile is None and draft_profile is not None:
            changes.append({"stage_id": stage_id, "change_type": "added"})
            continue
        if draft_profile is None and base_profile is not None:
            changes.append({"stage_id": stage_id, "change_type": "removed"})
            continue
        assert base_profile is not None and draft_profile is not None
        if _stage_skill_to_dict(base_profile) != _stage_skill_to_dict(draft_profile):
            changes.append({"stage_id": stage_id, "change_type": "modified"})
    return changes


def _diff_run_policy(base: ProjectSettings, draft: ProjectSettings) -> list[str]:
    base_policy = _policy_to_dict(base.run_policy)
    draft_policy = _policy_to_dict(draft.run_policy)
    return sorted(key for key in base_policy.keys() | draft_policy.keys() if base_policy.get(key) != draft_policy.get(key))


def list_model_options() -> list[dict[str, Any]]:
    return deepcopy(DEFAULT_MODEL_OPTIONS)


def required_prompt_variables() -> list[str]:
    return list(REQUIRED_VARIABLES)


def get_effective_settings_for_run(
    project_id: str,
    stage_id: Optional[str] = None,
    config_version_id: Optional[str] = None,
) -> ProjectSettings:
    """Return the settings a new Run should reference.

    Falls back to the project default (creating one if necessary) so that
    every Run has a ``config_version_id``. Draft settings are NEVER used.

    P1-11: 命中已发布 settings 时走一次版本注册性兜底，避免历史数据
    含已下线版本透传到运行时。
    """
    if config_version_id:
        settings = _get_published_settings_by_version(project_id, config_version_id)
        if settings is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Published settings version not found: {config_version_id}",
            )
        settings.stage_skill_profiles = _sanitize_registered_versions(settings.stage_skill_profiles)
        return settings
    settings = get_latest_published_settings(project_id)
    if settings is None:
        settings = ensure_default_settings(project_id)
    else:
        settings.stage_skill_profiles = _sanitize_registered_versions(settings.stage_skill_profiles)
    return settings


def _sanitize_registered_versions(
    profiles: Iterable[StageSkillProfile],
) -> list[StageSkillProfile]:
    """读取路径专用：未注册 harness/conversation_harness 版本回填默认 + 记 warning。

    与 _validate_stage_skill_profiles 不同，这里不抛错（读取路径不应
    因历史数据含下线版本而 409/422 中断），只兜底为默认值让运维可追溯。
    """
    from src.apps.api.app.agents.harness.registry import list_harness_versions
    from src.apps.api.app.agents.conversation_harness.registry import list_conversation_harness_versions

    known_harness = set(list_harness_versions())
    known_conv = set(list_conversation_harness_versions())
    cleaned: list[StageSkillProfile] = []
    for profile in profiles:
        if profile.harness_version not in known_harness:
            logger.warning(
                "settings: stage %s harness_version %s not registered, falling back to %s",
                profile.stage_id, profile.harness_version, DEFAULT_AGENT_HARNESS_VERSION,
            )
            profile = _replace_profile_version(
                profile,
                harness_version=DEFAULT_AGENT_HARNESS_VERSION,
            )
        if profile.conversation_harness_version not in known_conv:
            logger.warning(
                "settings: stage %s conversation_harness_version %s not registered, falling back to %s",
                profile.stage_id, profile.conversation_harness_version, DEFAULT_CONVERSATION_HARNESS_VERSION,
            )
            profile = _replace_profile_version(
                profile,
                conversation_harness_version=DEFAULT_CONVERSATION_HARNESS_VERSION,
            )
        cleaned.append(profile)
    return cleaned


def _replace_profile_version(
    profile: StageSkillProfile,
    *,
    harness_version: Optional[str] = None,
    conversation_harness_version: Optional[str] = None,
) -> StageSkillProfile:
    """Return a copy of profile with specified version fields replaced."""
    from dataclasses import replace
    kwargs: dict[str, str] = {}
    if harness_version is not None:
        kwargs["harness_version"] = harness_version
    if conversation_harness_version is not None:
        kwargs["conversation_harness_version"] = conversation_harness_version
    return replace(profile, **kwargs)


def _get_published_settings_by_version(project_id: str, version_id: str) -> Optional[ProjectSettings]:
    for settings in list_project_settings(project_id):
        if settings.version_id == version_id and settings.status == "published":
            return settings
    return None


def settings_snapshot(
    project_id: str,
    stage_id: Optional[str] = None,
    config_version_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return a compact snapshot of effective settings for a Run/Stage."""
    settings = get_effective_settings_for_run(
        project_id,
        stage_id=stage_id,
        config_version_id=config_version_id,
    )
    model_aliases: dict[str, str] = {}
    openai_compatible_models: dict[str, dict[str, Any]] = {}
    openai_compatible_models_safe: dict[str, dict[str, Any]] = {}
    for model in settings.models:
        if model.enabled:
            model_aliases[model.role] = model.model_name
            openai_compatible_models[model.role] = {
                "model_name": model.model_name,
                "base_url": model.base_url,
                "api_key": model.api_key,
                "reasoning_mode": model.reasoning_mode,
            }
            openai_compatible_models_safe[model.role] = {
                "model_name": model.model_name,
                "base_url": model.base_url,
                "api_key_configured": bool(model.api_key),
                "reasoning_mode": model.reasoning_mode,
            }
    prompt_refs: list[dict[str, str]] = []
    prompt_bodies: dict[str, str] = {}
    for prompt in settings.prompts:
        prompt_refs.append(
            {
                "id": prompt.id,
                "category": prompt.category,
                "version": prompt.version,
                "skill_name": prompt.skill_name or "",
            }
        )
        # L1-A: expose prompt body so runner can inject into HarnessState
        # and graph.py can read it instead of the hardcoded fallback strings.
        prompt_bodies[prompt.id] = prompt.body
    skill_versions: dict[str, str] = {}
    for profile in settings.stage_skill_profiles:
        skill_versions.update(profile.skill_versions)
    enabled_tools_by_stage: dict[str, list[str]] = {}
    enabled_subagents_by_stage: dict[str, list[str]] = {}
    harness_versions_by_stage: dict[str, str] = {}
    conversation_harness_versions_by_stage: dict[str, str] = {}
    stage_skill_profiles: list[dict[str, Any]] = []
    # P1-10: 读取路径对未注册版本兜底为默认值，避免运行时 409/422
    sanitized_profiles = _sanitize_registered_versions(settings.stage_skill_profiles)
    for profile in sanitized_profiles:
        enabled_tools_by_stage[profile.stage_id] = list(profile.enabled_tools)
        enabled_subagents_by_stage[profile.stage_id] = list(profile.enabled_subagents)
        harness_versions_by_stage[profile.stage_id] = profile.harness_version
        conversation_harness_versions_by_stage[profile.stage_id] = profile.conversation_harness_version
        stage_skill_profiles.append(_stage_skill_to_dict(profile))
    return {
        "config_version_id": settings.version_id,
        "config_hash": settings.config_hash,
        "model_aliases": model_aliases,
        "model_config": {
            "llm_capability": "vision" if model_aliases.get("vision") else "text",
            "config_version_id": settings.version_id,
            "config_hash": settings.config_hash,
            "model_aliases": model_aliases,
            "openai_compatible_models": openai_compatible_models_safe,
            "min_audit_requirements": list(settings.run_policy.min_audit_requirements),
            "harness_versions_by_stage": harness_versions_by_stage,
            "conversation_harness_versions_by_stage": conversation_harness_versions_by_stage,
        },
        "openai_compatible_models": openai_compatible_models,
        "skill_versions": skill_versions,
        "prompt_refs": prompt_refs,
        "prompt_bodies": prompt_bodies,
        "enabled_tools_by_stage": enabled_tools_by_stage,
        "enabled_subagents_by_stage": enabled_subagents_by_stage,
        "harness_versions_by_stage": harness_versions_by_stage,
        "conversation_harness_versions_by_stage": conversation_harness_versions_by_stage,
        "stage_skill_profiles": stage_skill_profiles,
        "run_policy": {
            "require_change_reason": settings.run_policy.require_change_reason,
            "allow_locked_stage_rerun": settings.run_policy.allow_locked_stage_rerun,
            "min_audit_requirements": list(settings.run_policy.min_audit_requirements),
            # P3-b: 对话 Harness 上下文裁剪 limit
            "conversation_message_limit": settings.run_policy.conversation_message_limit,
            "conversation_evidence_item_limit": settings.run_policy.conversation_evidence_item_limit,
            "conversation_evidence_snippet_limit": settings.run_policy.conversation_evidence_snippet_limit,
            "conversation_run_event_limit": settings.run_policy.conversation_run_event_limit,
        },
    }


def filter_tools_for_skill(
    project_id: str,
    stage_id: Optional[str],
    skill_name: str,
    declared_tools: Iterable[str],
    declared_subagents: Iterable[str],
    config_version_id: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """Return the subset of tools/subagents that are enabled for this stage.

    The settings layer is the only trusted source of truth; the Skill
    registry declares the universe of allowed tools/subagents, while the
    settings record decides which ones are *enabled* for a given project.

    A missing ``stage_id`` is treated as an explicit empty filter rather
    than a fallback to the declared universe, so a caller without a
    project-scoped stage can never silently bypass the project allowlist.
    """
    if not stage_id:
        return [], []
    settings = get_effective_settings_for_run(
        project_id,
        stage_id=stage_id,
        config_version_id=config_version_id,
    )
    for profile in settings.stage_skill_profiles:
        if profile.stage_id == stage_id and profile.primary_skill == skill_name:
            declared_tool_set = set(declared_tools)
            declared_subagent_set = set(declared_subagents)
            enabled_tools = [tool for tool in profile.enabled_tools if tool in declared_tool_set]
            enabled_subagents = [
                subagent for subagent in profile.enabled_subagents if subagent in declared_subagent_set
            ]
            return enabled_tools, enabled_subagents
    return [], []
