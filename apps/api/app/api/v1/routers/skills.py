"""Skill routers."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from src.apps.api.app.api.v1.schemas.skills import InvokeSkillRequest, SkillInvokeResponse, SkillListResponse, SkillResponse
from src.apps.api.app.services.skill_service import invoke_skill, list_skills

router = APIRouter()


@router.get("/skills", response_model=SkillListResponse)
def get_skills(stage_id: Optional[str] = Query(default=None)) -> SkillListResponse:
    items = list_skills(stage_id)
    return SkillListResponse(items=[SkillResponse.model_validate(item, from_attributes=True) for item in items])


@router.post("/skills/{skill_id}/invoke", response_model=SkillInvokeResponse)
def post_skill_invoke(skill_id: str, request: InvokeSkillRequest) -> SkillInvokeResponse:
    result = invoke_skill(
        skill_name=skill_id,
        project_id=request.project_id,
        stage_id=request.stage_id,
        run_id=request.run_id,
        goal=request.goal,
    )
    return SkillInvokeResponse.model_validate(result)
