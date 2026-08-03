from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from src.packages.reqeval.utils.env_loader import load_project_env


PAGEINDEX_BASE_URL = "https://api.pageindex.ai"
DEFAULT_CACHE_DIR = Path("outputs/local_retrieval/pageindex_cache")
DEFAULT_DOC_MAP_PATH = Path("outputs/local_retrieval/pageindex_doc_map.json")

load_project_env()


def build_pageindex_request(query: str, document_url: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": query,
        "document_url": document_url,
        "metadata": metadata,
    }


def build_cache_path(doc_id: str, query: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    safe_query = "".join(char if char.isalnum() else "_" for char in query.lower())[:80]
    return cache_dir / f"{doc_id}__{safe_query}.json"


def normalize_retrieved_nodes(retrieval_result: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for node in retrieval_result.get("retrieved_nodes", []):
        relevant_contents = node.get("relevant_contents", []) or []
        for content in relevant_contents:
            normalized.append(
                {
                    "title": node.get("title"),
                    "node_id": node.get("node_id"),
                    "page_index": content.get("page_index"),
                    "relevant_content": content.get("relevant_content"),
                }
            )
    return normalized


def _run_command(command: list[str], timeout: int = 120) -> dict[str, Any]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "command failed")
    if not result.stdout.strip():
        raise RuntimeError("empty response")
    return json.loads(result.stdout)


class PageIndexClientWrapper:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        doc_map_path: Path = DEFAULT_DOC_MAP_PATH,
    ) -> None:
        self.api_key = api_key or os.environ.get("PAGEINDEX_API_KEY")
        self.base_url = (base_url or os.environ.get("PAGEINDEX_BASE_URL") or PAGEINDEX_BASE_URL).rstrip("/")
        self.cache_dir = cache_dir
        self.doc_map_path = doc_map_path

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _load_doc_map(self) -> dict[str, str]:
        if self.doc_map_path.exists():
            return json.loads(self.doc_map_path.read_text(encoding="utf-8"))
        return {}

    def _save_doc_map(self, doc_map: dict[str, str]) -> None:
        self.doc_map_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_map_path.write_text(
            json.dumps(doc_map, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upload_document(self, pdf_path: str) -> str:
        if not self.api_key:
            raise RuntimeError("PAGEINDEX_API_KEY is not configured")
        response = _run_command(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                f"{self.base_url}/doc/",
                "-H",
                f"api_key: {self.api_key}",
                "-F",
                f"file=@{pdf_path}",
            ],
            timeout=300,
        )
        doc_id = response.get("doc_id")
        if not doc_id:
            raise RuntimeError(f"unexpected PageIndex upload response: {response}")
        return doc_id

    def ensure_document(self, pdf_path: str) -> str:
        resolved = str(Path(pdf_path).resolve())
        doc_map = self._load_doc_map()
        if resolved in doc_map:
            return doc_map[resolved]
        doc_id = self.upload_document(resolved)
        doc_map[resolved] = doc_id
        self._save_doc_map(doc_map)
        return doc_id

    def get_document_metadata(self, doc_id: str) -> dict[str, Any]:
        return _run_command(
            [
                "curl",
                "-s",
                f"{self.base_url}/doc/{doc_id}/metadata",
                "-H",
                f"api_key: {self.api_key}",
            ]
        )

    def wait_until_ready(self, doc_id: str, timeout_seconds: int = 600, poll_seconds: float = 5.0) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            metadata = self.get_document_metadata(doc_id)
            if metadata.get("retrieval_ready") is True:
                return
            time.sleep(poll_seconds)
        raise TimeoutError(f"PageIndex document not ready in time: {doc_id}")

    def submit_query(self, doc_id: str, query: str, thinking: bool = False) -> dict[str, Any]:
        payload = {
            "doc_id": doc_id,
            "query": query,
            "thinking": thinking,
        }
        return _run_command(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                f"{self.base_url}/retrieval",
                "-H",
                f"api_key: {self.api_key}",
                "-H",
                "Content-Type: application/json",
                "-d",
                json.dumps(payload, ensure_ascii=False),
            ],
            timeout=180,
        )

    def get_retrieval(self, retrieval_id: str) -> dict[str, Any]:
        return _run_command(
            [
                "curl",
                "-s",
                f"{self.base_url}/retrieval/{retrieval_id}",
                "-H",
                f"api_key: {self.api_key}",
            ],
            timeout=180,
        )

    def wait_for_retrieval_result(
        self,
        retrieval_id: str,
        timeout_seconds: int = 300,
        poll_seconds: float = 3.0,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            result = self.get_retrieval(retrieval_id)
            if result.get("status") in {"completed", "succeeded"}:
                return result
            time.sleep(poll_seconds)
        raise TimeoutError(f"PageIndex retrieval did not finish in time: {retrieval_id}")

    def write_cache(self, doc_id: str, query: str, payload: dict[str, Any]) -> Path:
        cache_path = build_cache_path(doc_id=doc_id, query=query, cache_dir=self.cache_dir)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return cache_path

    def retrieve_evidence_for_pdf(
        self,
        pdf_path: str,
        query: str,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            return []

        doc_id = self.ensure_document(pdf_path)
        cache_path = build_cache_path(doc_id=doc_id, query=query, cache_dir=self.cache_dir)
        if use_cache and cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return normalize_retrieved_nodes(payload)

        self.wait_until_ready(doc_id)
        retrieval = self.submit_query(doc_id=doc_id, query=query, thinking=False)
        retrieval_id = retrieval.get("retrieval_id")
        if not retrieval_id:
            raise RuntimeError(f"unexpected PageIndex retrieval response: {retrieval}")
        result = self.wait_for_retrieval_result(retrieval_id)
        self.write_cache(doc_id=doc_id, query=query, payload=result)
        return normalize_retrieved_nodes(result)
