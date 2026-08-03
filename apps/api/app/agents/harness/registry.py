"""Registry for replaceable harness providers."""

from __future__ import annotations

from fastapi import HTTPException, status

from src.apps.api.app.agents.harness.contracts import HarnessProvider
from src.apps.api.app.agents.harness.versions.langgraph_v1.provider import (
    LangGraphV1HarnessProvider,
)
from src.apps.api.app.agents.harness.versions.deepagents_v1.provider import (
    DeepAgentsV1HarnessProvider,
)
from src.apps.api.app.agents.harness.versions.honeycomb_v1.provider import (
    HoneycombV1HarnessProvider,
)
from src.apps.api.app.core.config import get_settings
from src.apps.api.app.core.harness_constants import DEFAULT_AGENT_HARNESS_VERSION


_PROVIDERS: dict[str, HarnessProvider] = {}


def register_harness_provider(provider: HarnessProvider) -> None:
    _PROVIDERS[provider.version] = provider


def list_harness_versions() -> list[str]:
    return sorted(_PROVIDERS)


def get_harness_provider(version: str | None = None) -> HarnessProvider:
    selected = version or get_settings().agent_harness_version or DEFAULT_AGENT_HARNESS_VERSION
    provider = _PROVIDERS.get(selected)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Unknown harness version: {selected}",
        )
    return provider


register_harness_provider(LangGraphV1HarnessProvider())
register_harness_provider(DeepAgentsV1HarnessProvider())
register_harness_provider(HoneycombV1HarnessProvider())
