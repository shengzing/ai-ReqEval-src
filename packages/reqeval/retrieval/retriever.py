from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.packages.reqeval.retrieval.embedding_client import SiliconFlowEmbeddingClient, cosine_similarity


def aggregate_doc_hits(hits: list[dict[str, Any]], top_k_docs: int = 5) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    chunk_map: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for hit in hits:
        doc_id = hit["doc_id"]
        if doc_id not in grouped:
            grouped[doc_id] = {
                "doc_id": doc_id,
                "score": 0.0,
                "max_chunk_score": 0.0,
                "chunks": chunk_map[doc_id],
            }
        grouped[doc_id]["score"] += float(hit.get("score", 0.0))
        grouped[doc_id]["max_chunk_score"] = max(
            grouped[doc_id]["max_chunk_score"], float(hit.get("score", 0.0))
        )
        chunk_map[doc_id].append(hit)

    aggregated = list(grouped.values())
    for item in aggregated:
        item["score"] = round(item["score"], 6)
        item["chunks"].sort(key=lambda chunk: float(chunk.get("score", 0.0)), reverse=True)

    aggregated.sort(
        key=lambda item: (item["score"], item["max_chunk_score"], item["doc_id"]),
        reverse=True,
    )
    return aggregated[:top_k_docs]


def hybridize_chunk_hits(
    query: str,
    lexical_hits: list[dict[str, Any]],
    embedding_client: SiliconFlowEmbeddingClient,
    chunk_embeddings: dict[str, list[float]] | None = None,
    top_k_chunks: int = 20,
    semantic_candidate_pool: int = 200,
) -> list[dict[str, Any]]:
    if not embedding_client.is_configured():
        return lexical_hits[:top_k_chunks]

    query_embedding = embedding_client.embed_with_cache(f"query::{query}", query)

    semantic_hits: list[dict[str, Any]] = []
    max_lexical = max((float(hit.get("score", 0.0)) for hit in lexical_hits), default=1.0) or 1.0
    candidate_hits = lexical_hits[: max(top_k_chunks, semantic_candidate_pool)]

    for record in candidate_hits:
        text = str(record.get("text", ""))
        if not text.strip():
            continue
        embedding = None
        if chunk_embeddings is not None:
            embedding = chunk_embeddings.get(record["chunk_id"])
        if embedding is None:
            embedding = embedding_client.embed_with_cache(record["chunk_id"], text)
        semantic_score = cosine_similarity(query_embedding, embedding)
        if semantic_score <= 0:
            continue
        hit = dict(record)
        hit["semantic_score"] = round(semantic_score, 6)
        semantic_hits.append(hit)

    semantic_hits.sort(key=lambda item: item["semantic_score"], reverse=True)
    top_semantic_hits = semantic_hits[:top_k_chunks]
    max_semantic = (
        max((float(hit.get("semantic_score", 0.0)) for hit in top_semantic_hits), default=1.0) or 1.0
    )

    combined: dict[str, dict[str, Any]] = {}
    for hit in top_semantic_hits:
        chunk_id = hit["chunk_id"]
        combined_hit = dict(hit)
        combined_hit["score"] = 0.45 * (float(hit["semantic_score"]) / max_semantic)
        combined[chunk_id] = combined_hit

    for hit in lexical_hits[:top_k_chunks]:
        chunk_id = hit["chunk_id"]
        lexical_component = 0.55 * (float(hit.get("score", 0.0)) / max_lexical)
        if chunk_id not in combined:
            combined[chunk_id] = dict(hit)
            combined[chunk_id]["semantic_score"] = 0.0
            combined[chunk_id]["score"] = 0.0
        combined[chunk_id]["score"] += lexical_component

    output = list(combined.values())
    output.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return output[:top_k_chunks]
