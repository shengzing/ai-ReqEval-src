"""Health router."""

from __future__ import annotations

from fastapi import APIRouter

from src.apps.api.app.api.v1.schemas.health import HealthResponse
from src.apps.api.app.core.config import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(service=settings.service_name, status="ok")
