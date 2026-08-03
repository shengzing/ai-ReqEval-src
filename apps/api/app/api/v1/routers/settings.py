"""Settings router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from src.apps.api.app.api.v1.schemas.settings import (
    ModelOptionListResponse,
    ModelOptionResponse,
    ProjectSettingsBundleResponse,
    ProjectSettingsListResponse,
    ProjectSettingsResponse,
    PublishSettingsRequest,
    SettingsDraftRequest,
    SettingsImpactResponse,
    SkillOptionListResponse,
    SkillOptionResponse,
)
from src.apps.api.app.domain.models import ModelProfile, PromptTemplate, RunPolicy, StageSkillProfile
from src.apps.api.app.services.settings_service import (
    build_settings_impact,
    ensure_default_settings,
    get_draft_settings,
    get_latest_published_settings,
    get_latest_settings,
    get_settings_versions,
    list_model_options,
    publish_settings_draft,
    reset_settings_draft,
    save_settings_draft,
)

router = APIRouter()


def _to_response(settings) -> ProjectSettingsResponse:
    return ProjectSettingsResponse(
        id=settings.id,
        project_id=settings.project_id,
        version_id=settings.version_id,
        base_version_id=settings.base_version_id,
        status=settings.status,
        config_hash=settings.config_hash,
        change_reason=settings.change_reason,
        models=[
            {
                "role": model.role,
                "provider": model.provider,
                "model_name": model.model_name,
                "base_url": model.base_url,
                "api_key": model.api_key,
                "enabled": model.enabled,
                "reasoning_mode": model.reasoning_mode,
            }
            for model in settings.models
        ],
        prompts=[
            {
                "id": prompt.id,
                "category": prompt.category,
                "scope": prompt.scope,
                "title": prompt.title,
                "body": prompt.body,
                "required_variables": list(prompt.required_variables),
                "skill_name": prompt.skill_name,
                "version": prompt.version,
            }
            for prompt in settings.prompts
        ],
        stage_skill_profiles=[
            {
                "stage_id": profile.stage_id,
                "primary_skill": profile.primary_skill,
                "enabled_tools": list(profile.enabled_tools),
                "enabled_subagents": list(profile.enabled_subagents),
                "auto_run_condition": profile.auto_run_condition,
                "harness_version": profile.harness_version,
                "conversation_harness_version": profile.conversation_harness_version,
                "skill_versions": dict(profile.skill_versions),
            }
            for profile in settings.stage_skill_profiles
        ],
        run_policy={
            "require_change_reason": settings.run_policy.require_change_reason,
            "allow_locked_stage_rerun": settings.run_policy.allow_locked_stage_rerun,
            "min_audit_requirements": list(settings.run_policy.min_audit_requirements),
            "conversation_message_limit": settings.run_policy.conversation_message_limit,
            "conversation_evidence_item_limit": settings.run_policy.conversation_evidence_item_limit,
            "conversation_evidence_snippet_limit": settings.run_policy.conversation_evidence_snippet_limit,
            "conversation_run_event_limit": settings.run_policy.conversation_run_event_limit,
        },
        created_at=settings.created_at,
        updated_at=settings.updated_at,
        published_at=settings.published_at,
        created_by=settings.created_by,
    )


def _draft_request_to_domain(request: SettingsDraftRequest):
    models = [
        ModelProfile(
            role=item.role,
            provider="openai",
            model_name=item.model_name,
            base_url=item.base_url,
            api_key=item.api_key,
            enabled=item.enabled,
            reasoning_mode=item.reasoning_mode,
        )
        for item in request.models
    ]
    prompts = [
        PromptTemplate(
            id=item.id,
            category=item.category,
            scope=item.scope,
            title=item.title,
            body=item.body,
            required_variables=list(item.required_variables),
            skill_name=item.skill_name,
            version=item.version,
        )
        for item in request.prompts
    ]
    profiles = [
        StageSkillProfile(
            stage_id=item.stage_id,
            primary_skill=item.primary_skill,
            enabled_tools=list(item.enabled_tools),
            enabled_subagents=list(item.enabled_subagents),
            auto_run_condition=item.auto_run_condition,
            harness_version=item.harness_version,
            conversation_harness_version=item.conversation_harness_version,
            skill_versions=dict(item.skill_versions),
        )
        for item in request.stage_skill_profiles
    ]
    policy = RunPolicy(
        require_change_reason=request.run_policy.require_change_reason,
        allow_locked_stage_rerun=request.run_policy.allow_locked_stage_rerun,
        min_audit_requirements=list(request.run_policy.min_audit_requirements),
        conversation_message_limit=request.run_policy.conversation_message_limit,
        conversation_evidence_item_limit=request.run_policy.conversation_evidence_item_limit,
        conversation_evidence_snippet_limit=request.run_policy.conversation_evidence_snippet_limit,
        conversation_run_event_limit=request.run_policy.conversation_run_event_limit,
    )
    return models, prompts, profiles, policy


@router.get("/projects/{project_id}/settings", response_model=ProjectSettingsBundleResponse)
def get_project_settings_bundle(project_id: str) -> ProjectSettingsBundleResponse:
    published = get_latest_published_settings(project_id) or ensure_default_settings(project_id)
    draft = get_draft_settings(project_id)
    return ProjectSettingsBundleResponse(
        published=_to_response(published) if published is not None else None,
        draft=_to_response(draft) if draft is not None else None,
        has_draft=draft is not None,
    )


@router.post("/projects/{project_id}/settings/draft", response_model=ProjectSettingsResponse)
def post_project_settings_draft(project_id: str, request: SettingsDraftRequest) -> ProjectSettingsResponse:
    models, prompts, profiles, policy = _draft_request_to_domain(request)
    draft = save_settings_draft(
        project_id=project_id,
        models=models,
        prompts=prompts,
        stage_skill_profiles=profiles,
        run_policy=policy,
        change_reason=request.change_reason,
    )
    return _to_response(draft)


@router.post(
    "/projects/{project_id}/settings/publish",
    response_model=ProjectSettingsResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_project_settings_publish(
    project_id: str,
    request: PublishSettingsRequest,
) -> ProjectSettingsResponse:
    draft = get_draft_settings(project_id)
    if draft is None and request.draft_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No settings draft exists; save a draft before publishing.",
        )
    draft_id = request.draft_id or draft.id
    require_change_reason = (
        draft.run_policy.require_change_reason if draft is not None and draft.id == draft_id else True
    )
    settings = publish_settings_draft(
        project_id=project_id,
        draft_id=draft_id,
        change_reason=request.change_reason,
        require_change_reason=require_change_reason,
    )
    return _to_response(settings)


@router.post("/projects/{project_id}/settings/reset", response_model=ProjectSettingsResponse)
def post_project_settings_reset(project_id: str) -> ProjectSettingsResponse:
    return _to_response(reset_settings_draft(project_id))


@router.get(
    "/projects/{project_id}/settings/versions",
    response_model=ProjectSettingsListResponse,
)
def get_project_settings_versions(project_id: str) -> ProjectSettingsListResponse:
    items = get_settings_versions(project_id)
    return ProjectSettingsListResponse(items=[_to_response(item) for item in items])


@router.get(
    "/projects/{project_id}/settings/impact",
    response_model=SettingsImpactResponse,
)
def get_project_settings_impact(project_id: str) -> SettingsImpactResponse:
    payload = build_settings_impact(project_id)
    return SettingsImpactResponse(**payload)


@router.get("/model-options", response_model=ModelOptionListResponse)
def get_model_options() -> ModelOptionListResponse:
    return ModelOptionListResponse(
        items=[
            ModelOptionResponse(
                provider=item["provider"],
                model_name=item["model_name"],
                base_url=item.get("base_url", ""),
            )
            for item in list_model_options()
        ]
    )


@router.get("/skill-options", response_model=SkillOptionListResponse)
def get_skill_options() -> SkillOptionListResponse:
    from src.apps.api.app.agents.skills.registry import list_skills as list_skill_definitions

    items = list_skill_definitions()
    return SkillOptionListResponse(
        items=[
            SkillOptionResponse(
                name=skill.name,
                stage_suffix=skill.stage_suffix,
                description=skill.description,
                allowed_tools=list(skill.allowed_tools),
                allowed_subagents=list(skill.allowed_subagents),
                auto_run_condition=skill.auto_run_condition,
                visibility=skill.visibility,
            )
            for skill in items
        ]
    )
