"""Vision-capable LLM client integration."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from fastapi import HTTPException, status

from src.apps.api.app.core.config import get_settings
from src.apps.api.app.domain.models import VisionParseResult


class VisionLLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.vision_llm_base_url or not settings.vision_llm_api_key or not settings.vision_llm_model:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vision LLM is not configured",
            )
        self.base_url = settings.vision_llm_base_url.rstrip("/")
        self.api_key = settings.vision_llm_api_key
        self.model = settings.vision_llm_model

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """流式调用 LLM 并聚合 delta.content，末尾 json.loads 返回完整 dict。

        与 HarnessLLMClient.complete_json 同协议（SSE delta 聚合 + [DONE] 哨兵），
        调用点（parse_file）已有 try/except 兜底，流式异常冒泡到上层 HTTPException。
        """
        stream_payload = {**payload, "stream": True}
        timeout = httpx.Timeout(connect=60.0, read=60.0, write=60.0, pool=60.0)
        content_parts: list[str] = []
        with httpx.Client() as client:
            with client.stream(
                "POST",
                "{0}/chat/completions".format(self.base_url),
                headers={
                    "Authorization": "Bearer {0}".format(self.api_key),
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=stream_payload,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or [{}]
                    delta = choices[0].get("delta", {}) if choices else {}
                    piece = delta.get("content", "")
                    if isinstance(piece, list):
                        piece = "".join(
                            item.get("text", "") if isinstance(item, dict) else str(item)
                            for item in piece
                        )
                    if piece:
                        content_parts.append(piece)
        content = "".join(content_parts)
        if not content:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Vision LLM returned empty stream")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Vision LLM did not return JSON") from exc

    def parse_file(
        self,
        *,
        file_path: Path,
        file_id: str,
        project_id: str,
        prompt: str,
        target_schema: dict[str, str],
        project_context: dict[str, Any],
        content_type: str,
    ) -> VisionParseResult:
        image_b64 = base64.b64encode(file_path.read_bytes()).decode("utf-8")
        request_prompt = (
            "You are a vision parser for requirement evaluation.\n"
            "Return strict JSON with keys: structured_fields, evidence_fragments, uncertainties, to_confirm.\n"
            "Target schema: {0}\n"
            "Project context: {1}\n"
            "User prompt: {2}"
        ).format(json.dumps(target_schema, ensure_ascii=False), json.dumps(project_context, ensure_ascii=False), prompt)
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:{0};base64,{1}".format(content_type or "application/octet-stream", image_b64)
                            },
                        },
                    ],
                }
            ],
        }
        response_data = self._post_chat(payload)
        # 流式聚合后 response_data 已是 LLM 返回的 JSON dict（content 字段已是完整文本）
        # 取 scenario_summary 风格的 content；旧非流式返回 choices[0].message.content，
        # 流式聚合后直接是 dict，所以这里兼容两种形态
        if isinstance(response_data, dict) and "choices" in response_data:
            try:
                raw_content = response_data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid vision LLM response")
        else:
            # 流式聚合后是 LLM 返回的 JSON dict 本身（如 {"structured_fields":...}）
            raw_content = response_data if isinstance(response_data, dict) else {}
        parsed_content = _parse_json_payload(raw_content)
        return VisionParseResult(
            file_id=file_id,
            project_id=project_id,
            model=self.model,
            structured_fields=parsed_content.get("structured_fields", {}),
            evidence_fragments=parsed_content.get("evidence_fragments", []),
            uncertainties=parsed_content.get("uncertainties", []),
            to_confirm=parsed_content.get("to_confirm", []),
            raw_response=raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False),
        )


def _parse_json_payload(raw_content: Any) -> dict[str, Any]:
    if isinstance(raw_content, list):
        raw_content = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in raw_content)
    if not isinstance(raw_content, str):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid vision LLM content")
    content = raw_content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Vision LLM did not return JSON") from exc
