"""LLM adapter used by the internal agent harness.

The adapter speaks the OpenAI-compatible chat completions protocol when
configured, and otherwise returns deterministic fallback decisions. This keeps
the harness usable in local tests without network access.

流式实现：complete_json 用 httpx.stream 逐行读 SSE delta.content 聚合，
末尾 json.loads 返回完整 dict（签名不变，调用点 try/except Exception 兜底天然兼容）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from src.apps.api.app.core.config import get_settings
from src.apps.api.app.agents.harness.state import NO_LLM_FALLBACK_MESSAGE


logger = logging.getLogger(__name__)


# Reasoning models (MiniMax-M3 / DeepSeek-R1 / QwQ etc.) ignore OpenAI's
# ``response_format={"type": "json_object"}`` and prepend a free-form
# ``<think>...</think>`` chain before the actual JSON. Extract the first
# parseable JSON object robustly so we don't silently fall back to the
# rule-based template when the model actually did answer.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the first parseable JSON object embedded in ``text``.

    Tries, in order:
    1. ``json.loads(text)`` — works for clean JSON responses (GPT-4o, Claude).
    2. Strip ``<think>...</think>`` blocks then parse — handles reasoning
       models that prepend a thinking chain before the JSON.
    3. Strip markdown ```` ```json ```` / ```` ``` ```` fences then parse.
    4. Scan left→right for a balanced ``{...}`` block and parse each
       candidate. Last-resort fallback for prose-wrapped JSON.
    Returns ``None`` if no parseable object is found.
    """
    if not text:
        return None
    # 1. Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # 2. Strip <think>...</think> reasoning
    cleaned = _THINK_BLOCK_RE.sub("", text)
    if cleaned != text:
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    else:
        cleaned = text
    # 3. Strip ```json ... ``` fences (whole-string or per-line)
    fenced = _JSON_FENCE_RE.sub("", cleaned).strip()
    if fenced and fenced != cleaned:
        try:
            result = json.loads(fenced)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    # 4. Scan left→right for a balanced {...} block. Track string state to
    #    avoid matching braces inside JSON string values (e.g. "{x}" inside
    #    a reply). On parse failure OR unbalanced (end == -1), advance past
    #    this '{' and try the next one. A run-on like "preamble {partial\n\n
    #    {"reply": ...}" must skip the unclosed '{' and try the next.
    i = 0
    n = len(cleaned)
    while i < n:
        if cleaned[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        end = -1
        for j in range(i, n):
            c = cleaned[j]
            if escape:
                escape = False
                continue
            if in_string:
                if c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
                continue
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end == -1:
            # Unbalanced '{' (e.g. prose "preamble {partial" before real JSON).
            # Move past it and look for the next balanced block.
            i += 1
            continue
        try:
            result = json.loads(cleaned[i : end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        i = end + 1
    return None


class HarnessLLMClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        reasoning_mode: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.agent_llm_base_url or "").rstrip("/")
        self.api_key = api_key or settings.agent_llm_api_key or ""
        self.model = model or settings.agent_llm_model or "gpt-4o-mini"
        self.reasoning_mode = reasoning_mode
        self.timeout_seconds = settings.agent_llm_timeout_seconds
        self.required = settings.agent_llm_required
        # transport 仅用于测试注入 MockTransport；生产不传（用 httpx 默认连接池）
        self._transport = transport

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def status(self, *, mode: str | None = None, message: str | None = None) -> dict[str, Any]:
        missing = []
        if not self.base_url:
            missing.append("AGENT_LLM_BASE_URL")
        if not self.api_key:
            missing.append("AGENT_LLM_API_KEY")
        if not self.model:
            missing.append("AGENT_LLM_MODEL")
        configured = self.is_configured()
        status_mode = mode or ("llm" if configured else "fallback")
        status_message = message or ("" if configured else NO_LLM_FALLBACK_MESSAGE)
        return {
            "configured": configured,
            "mode": status_mode,
            "message": status_message,
            "missing": missing,
        }

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        temperature: float = 0,
    ) -> dict[str, Any]:
        """流式调用 LLM 并聚合 delta.content，末尾 json.loads 返回完整 dict。

        签名不变（(*, system_prompt, user_payload) -> dict），调用点 try/except Exception
        兜底天然兼容流式异常（断流/HTTP 错/JSON 错都冒泡到调用方 except）。

        temperature 默认 0 以保持现有调用行为；对话 Harness 等场景可传 0.4 等略高值。
        """
        if not self.is_configured():
            logger.warning(
                "[harness_llm] complete_json: NOT configured (base_url=%s api_key=%s model=%s). Returning {}.",
                bool(self.base_url), bool(self.api_key), self.model,
            )
            return {}
        logger.info(
            "[harness_llm] complete_json: POST %s model=%s temperature=%s stream=True reasoning_mode=%s",
            f"{self.base_url}/chat/completions", self.model, temperature, self.reasoning_mode,
        )
        # reasoning_mode=False 时关闭推理链:既给模型 provider 级开关(MiniMax-M3 /
        # QwQ 等用 chat_template_kwargs.enable_thinking),也在 system prompt 里
        # 兜底要求"直接给最终答案,不要输出 <think>…</think>",使不支持 provider
        # 开关的模型也能尽量输出干净 JSON。reasoning_mode=True 时完全不加任何
        # 指令,保持 MiniMax-M3 / DeepSeek-R1 等推理模型原本"长思考再答"的能力。
        system_content = system_prompt
        if not self.reasoning_mode:
            system_content = (
                system_prompt
                + "\n\n【重要】请直接给出最终答案,不要输出 <think>…</think> 之类的"
                "思考过程或推理链。最终答案用纯文本或 JSON,不要任何前缀思考块。"
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "stream": True,  # 流式
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        }
        if not self.reasoning_mode:
            payload["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        # 流式下 connect/read/write/pool 分离，read 超时按 chunk 续命
        timeout = httpx.Timeout(
            connect=float(self.timeout_seconds),
            read=float(self.timeout_seconds),
            write=float(self.timeout_seconds),
            pool=float(self.timeout_seconds),
        )
        stream_kwargs: dict[str, Any] = {
            "headers": {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            "json": payload,
            "timeout": timeout,
        }

        content_parts: list[str] = []
        # httpx.stream 同步上下文管理器（harness 全链路同步，可用）
        # transport 仅用于测试注入 MockTransport；生产不传用默认连接池
        client_kwargs: dict[str, Any] = {}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        with httpx.Client(**client_kwargs) as http_client:
            with http_client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                **stream_kwargs,
            ) as response:
                response.raise_for_status()  # 连接/HTTP 错在此抛（被调用方 except 捕获）
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue  # 跳过空行/注释行（: heartbeat 等）
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break  # OpenAI 兼容流式终止信号
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue  # 跳过非 JSON 心跳/注释行
                    choices = chunk.get("choices") or [{}]
                    delta = choices[0].get("delta", {}) if choices else {}
                    piece = delta.get("content", "")
                    if isinstance(piece, list):
                        # 兼容 list-of-text content
                        piece = "".join(
                            item.get("text", "") if isinstance(item, dict) else str(item)
                            for item in piece
                        )
                    if piece:
                        content_parts.append(piece)
        content = "".join(content_parts)
        if not content:
            logger.warning("[harness_llm] complete_json: stream returned empty content. Returning {}.")
            return {}  # 空流 → 触发调用方 fallback
        logger.info(
            "[harness_llm] complete_json: stream done, content_len=%d. Parsing JSON…",
            len(content),
        )
        data = _extract_json_object(content)
        if data is None:
            logger.warning(
                "[harness_llm] complete_json: JSON extraction FAILED. content_preview=%r. Returning {}.",
                content[:200],
            )
            return {}
        return data
