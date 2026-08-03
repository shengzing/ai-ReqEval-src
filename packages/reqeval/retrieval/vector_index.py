from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.packages.reqeval.retrieval.embedding_client import SiliconFlowEmbeddingClient, hash_text


DEFAULT_VECTOR_INDEX_DIR = Path("outputs/local_retrieval/vector_index")


def vector_index_path(
    chunk_size: int,
    chunk_overlap: int,
    output_dir: Path = DEFAULT_VECTOR_INDEX_DIR,
) -> Path:
    return output_dir / f"chunks_cs{chunk_size}_ov{chunk_overlap}.json"


def build_corpus_fingerprint(chunk_records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in chunk_records:
        digest.update(f"{record['chunk_id']}::{hash_text(str(record.get('text', '')))}\n".encode("utf-8"))
    return digest.hexdigest()


def load_vector_index(index_path: Path) -> dict[str, Any] | None:
    if not index_path.exists():
        return None
    return json.loads(index_path.read_text(encoding="utf-8"))


def build_or_load_vector_index(
    chunk_records: list[dict[str, Any]],
    embedding_client: SiliconFlowEmbeddingClient,
    chunk_size: int,
    chunk_overlap: int,
    batch_size: int = 16,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    index_path = vector_index_path(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    corpus_fingerprint = build_corpus_fingerprint(chunk_records)
    existing = None if force_rebuild else load_vector_index(index_path)

    if existing:
        metadata = existing.get("metadata", {})
        if (
            metadata.get("corpus_fingerprint") == corpus_fingerprint
            and metadata.get("model") == embedding_client.model
            and metadata.get("base_url") == embedding_client.base_url
        ):
            return existing

    existing_records = {}
    if existing:
        for item in existing.get("records", []):
            chunk_id = item.get("chunk_id")
            text_hash_value = item.get("text_hash")
            embedding = item.get("embedding")
            if chunk_id and text_hash_value and embedding:
                existing_records[chunk_id] = {
                    "text_hash": text_hash_value,
                    "embedding": embedding,
                }

    pending_items: list[tuple[str, str]] = []
    output_records: list[dict[str, Any]] = []
    resolved_embeddings: dict[str, list[float]] = {}

    for record in chunk_records:
        chunk_id = str(record["chunk_id"])
        text = str(record.get("text", ""))
        text_hash_value = hash_text(text)
        existing_record = existing_records.get(chunk_id)
        if existing_record and existing_record["text_hash"] == text_hash_value:
            resolved_embeddings[chunk_id] = existing_record["embedding"]
            continue
        pending_items.append((chunk_id, text))

    if pending_items:
        total_batches = (len(pending_items) + batch_size - 1) // batch_size
        print(
            f"Building embedding index: pending_chunks={len(pending_items)}, batches={total_batches}",
            flush=True,
        )
        for batch_index, start in enumerate(range(0, len(pending_items), batch_size), start=1):
            batch_items = pending_items[start : start + batch_size]
            resolved_embeddings.update(
                embedding_client.embed_many_with_cache(batch_items, batch_size=batch_size)
            )
            if batch_index == 1 or batch_index % 10 == 0 or batch_index == total_batches:
                print(
                    f"Embedding index progress: batch {batch_index}/{total_batches}",
                    flush=True,
                )

    for record in chunk_records:
        chunk_id = str(record["chunk_id"])
        text = str(record.get("text", ""))
        output_records.append(
            {
                "chunk_id": chunk_id,
                "text_hash": hash_text(text),
                "embedding": resolved_embeddings[chunk_id],
            }
        )

    payload = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "chunk_count": len(chunk_records),
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "model": embedding_client.model,
            "base_url": embedding_client.base_url,
            "corpus_fingerprint": corpus_fingerprint,
        },
        "records": output_records,
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def vector_lookup_from_payload(payload: dict[str, Any]) -> dict[str, list[float]]:
    return {
        item["chunk_id"]: item["embedding"]
        for item in payload.get("records", [])
        if item.get("chunk_id") and item.get("embedding")
    }
