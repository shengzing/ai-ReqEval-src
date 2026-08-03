from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from src.packages.reqeval.utils.env_loader import load_project_env


DEFAULT_EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1/embeddings"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"
DEFAULT_EMBEDDING_CACHE_PATH = Path("outputs/local_retrieval/embedding_cache.json")

load_project_env()


def build_embedding_payload(texts: list[str], model: str) -> dict[str, Any]:
    return {
        "model": model,
        "input": texts,
    }


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    if not vector_a or not vector_b or len(vector_a) != len(vector_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = sum(a * a for a in vector_a) ** 0.5
    norm_b = sum(b * b for b in vector_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingCache:
    def __init__(self, cache_path: Path = DEFAULT_EMBEDDING_CACHE_PATH) -> None:
        self.cache_path = cache_path
        self._data: dict[str, dict[str, Any]] | None = None

    def load(self) -> dict[str, dict[str, Any]]:
        if self._data is not None:
            return self._data
        if self.cache_path.exists():
            try:
                self._data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                corrupt_path = self.cache_path.with_suffix(f"{self.cache_path.suffix}.corrupt")
                self.cache_path.replace(corrupt_path)
                self._data = {}
        else:
            self._data = {}
        return self._data

    def get(self, key: str) -> dict[str, Any] | None:
        return self.load().get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self.load()[key] = value

    def persist(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.cache_path.with_suffix(f"{self.cache_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(self.load(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.cache_path)


class SiliconFlowEmbeddingClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        cache: EmbeddingCache | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("SILICONFLOW_API_KEY")
        self.base_url = base_url or os.environ.get("EMBEDDING_BASE_URL") or DEFAULT_EMBEDDING_BASE_URL
        self.model = model or os.environ.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        self.cache = cache or EmbeddingCache()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps(build_embedding_payload(texts, self.model)).encode("utf-8")
        req = request.Request(
            self.base_url,
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RuntimeError(f"Embedding request failed: {exc}") from exc
        return [item["embedding"] for item in data["data"]]

    def embed_with_cache(self, cache_key: str, text: str) -> list[float]:
        text_hash = hash_text(text)
        cached = self.cache.get(cache_key)
        if cached and cached.get("text_hash") == text_hash:
            return cached["embedding"]
        embedding = self.embed_texts([text])[0]
        self.cache.set(cache_key, {"text_hash": text_hash, "embedding": embedding})
        self.cache.persist()
        return embedding

    def embed_many_with_cache(self, items: list[tuple[str, str]], batch_size: int = 16) -> dict[str, list[float]]:
        resolved: dict[str, list[float]] = {}
        pending: list[tuple[str, str, str]] = []

        for cache_key, text in items:
            text_hash = hash_text(text)
            cached = self.cache.get(cache_key)
            if cached and cached.get("text_hash") == text_hash:
                resolved[cache_key] = cached["embedding"]
                continue
            pending.append((cache_key, text, text_hash))

        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            embeddings = self.embed_texts([text for _, text, _ in batch])
            for (cache_key, _text, text_hash), embedding in zip(batch, embeddings):
                self.cache.set(cache_key, {"text_hash": text_hash, "embedding": embedding})
                resolved[cache_key] = embedding

        if pending:
            self.cache.persist()
        return resolved
