"""Top-level v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from src.apps.api.app.api.v1.routers import autoresearch, health, projects, runs, settings, skills

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(projects.router, tags=["projects", "stages", "files", "evidence", "reports"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(runs.router, tags=["runs"])
api_router.include_router(autoresearch.router, tags=["autoresearch"])
api_router.include_router(skills.router, tags=["skills"])
