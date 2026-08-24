"""LLM adapter for harness providers (HVS-P1-03).

包装 HarnessLLMClient，对外暴露 is_configured / status / complete_json。
保留 fallback 行为（未配置时 complete_json 返回 {}，调用方负责 fallback）。
Honeycomb runtime 只依赖 LLMAdapter，不直接依赖 HarnessLLMClient。
"""

from __future__ import annotations

from typing import Any

from src.apps.api.app.agents.harness.llm import HarnessLLMClient


class LLMAdapter:
    """HarnessLLMClient 的薄包装；后续多模型路由只改本 adapter。"""

    def __init__(self, llm_client: HarnessLLMClient | None = None) -> None:
        self._client: HarnessLLMClient = llm_client if llm_client is not None else HarnessLLMClient()

    def is_configured(self) -> bool:
        return self._client.is_configured()

    @property
    def client(self) -> HarnessLLMClient:
        """Expose the scoped client for project tools that opt into LLM input."""
        return self._client

    def status(self, *, mode: str | None = None, message: str | None = None) -> dict[str, Any]:
        return self._client.status(mode=mode, message=message)

    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        """薄透传；底层异常向上抛，调用方捕获后走 fallback。"""
        return self._client.complete_json(system_prompt=system_prompt, user_payload=user_payload)
