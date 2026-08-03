"""Application settings.

Single source of truth: each field is read from an environment variable (or
``src/apps/api/.env``, loaded with ``override=False`` so real env vars win).
``get_settings()`` is cached; tests call ``get_settings.cache_clear()`` after
monkeypatching ``os.environ``.

Removed historically:
- ``OPENAI_*`` fallbacks for ``AGENT_LLM_*`` / ``VISION_LLM_*`` — the harness
  and vision clients read the dedicated vars only, and ``HarnessLLMClient``
  already reports ``missing`` against ``AGENT_LLM_*`` keys. The fallback chain
  was neither used nor tested.
- Standalone ``mongodb_host/port/user/password/auth_source`` fields kept on
  ``Settings`` — ``mongodb.py`` only reads ``mongodb_uri`` + ``mongodb_database``.
  The URI is still assembled from the parts when a full ``MONGODB_URI`` is not
  supplied, but the parts are not exposed as separate Settings fields.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

from src.apps.api.app.core.harness_constants import (
    DEFAULT_AGENT_HARNESS_VERSION,
    DEFAULT_CONVERSATION_HARNESS_VERSION,
)

# API backend reads src/apps/api/.env (parents[2] of core/config.py). Real env
# vars take precedence (override=False) — .env is the persisted fallback.
BACKEND_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(BACKEND_ENV_PATH, override=False)


def _env(name: str, default: str = "") -> str:
    """Read an env var, trimmed; empty → default (then None at call sites)."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _build_mongodb_uri() -> Optional[str]:
    """Assemble a MongoDB URI from parts when MONGODB_URI is not set directly."""
    uri = _env("MONGODB_URI")
    if uri:
        return uri
    user = _env("MONGODB_USER") or None
    password = _env("MONGODB_PASSWORD") or None
    if not (user and password):
        return None
    from urllib.parse import quote_plus

    host = _env("MONGODB_HOST", "127.0.0.1")
    port = _env("MONGODB_PORT", "27017")
    auth_source = _env("MONGODB_AUTH_SOURCE", "admin")
    return (
        f"mongodb://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/?authSource={quote_plus(auth_source)}"
    )


class Settings(BaseModel):
    """Resolved application settings. Construct via :func:`get_settings`."""

    service_name: str = "ai-reqeval-api"
    cors_allow_origins: list[str] = ["*"]

    # MongoDB — mongodb.py reads only these two.
    mongodb_uri: Optional[str] = None
    mongodb_database: str = "ai_ReqEval"

    # Vision LLM (document/OCR parsing). vision_llm.py reads these directly.
    vision_llm_base_url: Optional[str] = None
    vision_llm_api_key: Optional[str] = None
    vision_llm_model: str = "gpt-4o"

    # Agent LLM (harness planner / synthesizer / Deep Agents). HarnessLLMClient
    # reads these directly and reports missing against AGENT_LLM_* keys.
    agent_llm_base_url: Optional[str] = None
    agent_llm_api_key: Optional[str] = None
    agent_llm_model: str = "gpt-4o-mini"
    agent_llm_timeout_seconds: int = 60
    agent_llm_required: bool = False

    # Harness version selection (StageSkillProfile per-stage overrides these).
    agent_harness_version: str = DEFAULT_AGENT_HARNESS_VERSION
    conversation_harness_version: str = DEFAULT_CONVERSATION_HARNESS_VERSION

    # Filesystem roots.
    data_root: Path = Path("data/projects")
    output_root: Path = Path("outputs")
    static_root: Path = Path("src/apps/api/app/static")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        cors_allow_origins=[
            item.strip() for item in _env("CORS_ALLOW_ORIGINS", "*").split(",") if item.strip()
        ],
        mongodb_uri=_build_mongodb_uri(),
        mongodb_database=_env("DATABASE_NAME") or _env("MONGODB_DATABASE", "ai_ReqEval"),
        vision_llm_base_url=_env("VISION_LLM_BASE_URL") or None,
        vision_llm_api_key=_env("VISION_LLM_API_KEY") or None,
        vision_llm_model=_env("VISION_LLM_MODEL", "gpt-4o"),
        agent_llm_base_url=_env("AGENT_LLM_BASE_URL") or None,
        agent_llm_api_key=_env("AGENT_LLM_API_KEY") or None,
        agent_llm_model=_env("AGENT_LLM_MODEL", "gpt-4o-mini"),
        agent_llm_timeout_seconds=int(_env("AGENT_LLM_TIMEOUT_SECONDS", "60") or "60"),
        agent_llm_required=_env("AGENT_LLM_REQUIRED", "false").lower() in {"1", "true", "yes", "on"},
        agent_harness_version=_env("AGENT_HARNESS_VERSION", DEFAULT_AGENT_HARNESS_VERSION) or DEFAULT_AGENT_HARNESS_VERSION,
        conversation_harness_version=_env("CONVERSATION_HARNESS_VERSION", DEFAULT_CONVERSATION_HARNESS_VERSION) or DEFAULT_CONVERSATION_HARNESS_VERSION,
        data_root=Path(_env("AI_REQEVAL_DATA_ROOT", "data/projects")),
        output_root=Path(_env("AI_REQEVAL_OUTPUT_ROOT", "outputs")),
        static_root=Path(_env("AI_REQEVAL_STATIC_ROOT", "src/apps/api/app/static")),
    )
