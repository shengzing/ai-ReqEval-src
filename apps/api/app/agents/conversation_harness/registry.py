"""Registry for stage conversation harness providers."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from src.apps.api.app.agents.conversation_harness.contracts import (
    ConversationHarnessProvider,
)
from src.apps.api.app.agents.conversation_harness.versions.deepagents_v1 import (
    ConversationDeepAgentsV1Provider,
)
from src.apps.api.app.agents.conversation_harness.versions.openharness_v1 import (
    ConversationOpenHarnessV1Provider,
)
from src.apps.api.app.agents.conversation_harness.versions.simple_v1 import (
    ConversationSimpleV1Provider,
)
from src.apps.api.app.core.config import get_settings
from src.apps.api.app.core.harness_constants import (
    DEFAULT_CONVERSATION_HARNESS_VERSION,
)


logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, ConversationHarnessProvider] = {}


def register_conversation_harness_provider(provider: ConversationHarnessProvider) -> None:
    existing = _PROVIDERS.get(provider.version)
    if existing is not None and existing is not provider:
        logger.warning(
            "Conversation harness provider for version %s is already registered by %s; "
            "overwriting with %s",
            provider.version,
            type(existing).__name__,
            type(provider).__name__,
        )
    _PROVIDERS[provider.version] = provider


def list_conversation_harness_versions() -> list[str]:
    return sorted(_PROVIDERS)


def get_conversation_harness_provider(version: str | None = None) -> ConversationHarnessProvider:
    selected = version or get_settings().conversation_harness_version or DEFAULT_CONVERSATION_HARNESS_VERSION
    provider = _PROVIDERS.get(selected)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown conversation harness version: {selected}",
        )
    return provider


register_conversation_harness_provider(ConversationSimpleV1Provider())
register_conversation_harness_provider(ConversationDeepAgentsV1Provider())
register_conversation_harness_provider(ConversationOpenHarnessV1Provider())
