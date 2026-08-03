from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text or "")]


class LocalBM25Index:
    def __init__(self, records: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.records = records
        self.k1 = k1
        self.b = b
        self.documents = [tokenize(str(record.get("text", ""))) for record in records]
        self.doc_freqs: Counter[str] = Counter()
        self.term_freqs: list[Counter[str]] = []
        self.doc_lengths: list[int] = []

        for tokens in self.documents:
            term_counter = Counter(tokens)
            self.term_freqs.append(term_counter)
            self.doc_lengths.append(len(tokens))
            self.doc_freqs.update(term_counter.keys())

        self.doc_count = len(self.documents)
        self.avg_doc_len = (
            sum(self.doc_lengths) / self.doc_count if self.doc_count else 0.0
        )

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "LocalBM25Index":
        return cls(records=records)

    def _idf(self, term: str) -> float:
        doc_freq = self.doc_freqs.get(term, 0)
        if doc_freq == 0 or self.doc_count == 0:
            return 0.0
        return math.log(1 + (self.doc_count - doc_freq + 0.5) / (doc_freq + 0.5))

    def _score_document(self, query_tokens: list[str], index: int) -> float:
        if not query_tokens or self.avg_doc_len == 0:
            return 0.0

        score = 0.0
        term_freq = self.term_freqs[index]
        doc_length = self.doc_lengths[index]

        for term in query_tokens:
            frequency = term_freq.get(term, 0)
            if frequency == 0:
                continue
            numerator = frequency * (self.k1 + 1)
            denominator = frequency + self.k1 * (
                1 - self.b + self.b * (doc_length / self.avg_doc_len)
            )
            score += self._idf(term) * (numerator / denominator)
        return score

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_tokens = tokenize(query)
        scored_hits: list[dict[str, Any]] = []

        for index, record in enumerate(self.records):
            score = self._score_document(query_tokens, index)
            if score <= 0:
                continue
            hit = dict(record)
            hit["score"] = round(score, 6)
            scored_hits.append(hit)

        scored_hits.sort(key=lambda item: item["score"], reverse=True)
        return scored_hits[:top_k]
