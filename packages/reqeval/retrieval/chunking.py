from __future__ import annotations

import re
from typing import Dict, List


SENTENCE_ENDINGS = set(".!?;。！？；")
CLOSING_QUOTES = set("\"'”’」』）》）)]】")


def _extract_blocks(text: str) -> List[Dict[str, object]]:
    blocks: List[Dict[str, object]] = []
    for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
        block_text = match.group().strip()
        if not block_text:
            continue
        blocks.append(
            {
                "text": block_text,
                "char_start": match.start(),
                "char_end": match.end(),
            }
        )
    return blocks


def _is_heading_like(block_text: str) -> bool:
    lines = [line.strip() for line in block_text.splitlines() if line.strip()]
    if not lines or len(lines) > 2:
        return False
    joined = " ".join(lines)
    if len(joined) > 80:
        return False
    if any(char in joined for char in "。！？!?；;.:"):
        return False
    alpha_ratio = sum(char.isalpha() for char in joined) / max(len(joined), 1)
    if alpha_ratio > 0.7 and len(joined.split()) <= 12:
        return True
    if len(joined) <= 30:
        return True
    return False


def _merge_heading_blocks(blocks: List[Dict[str, object]]) -> List[Dict[str, object]]:
    merged: List[Dict[str, object]] = []
    pending_heading: Dict[str, object] | None = None

    for block in blocks:
        if _is_heading_like(str(block["text"])):
            if pending_heading is None:
                pending_heading = dict(block)
            else:
                pending_heading["text"] = f"{pending_heading['text']}\n{block['text']}".strip()
                pending_heading["char_end"] = block["char_end"]
            continue

        if pending_heading is not None:
            merged.append(
                {
                    "text": f"{pending_heading['text']}\n{block['text']}".strip(),
                    "char_start": pending_heading["char_start"],
                    "char_end": block["char_end"],
                }
            )
            pending_heading = None
            continue

        merged.append(block)

    if pending_heading is not None:
        merged.append(pending_heading)
    return merged


def _split_sentence_spans(block_text: str, block_start: int) -> List[Dict[str, object]]:
    spans: List[Dict[str, object]] = []
    start = 0
    index = 0

    while index < len(block_text):
        char = block_text[index]
        is_boundary = char in SENTENCE_ENDINGS
        if char == "\n":
            prev_char = block_text[index - 1] if index > 0 else ""
            next_char = block_text[index + 1] if index + 1 < len(block_text) else ""
            is_boundary = prev_char and next_char and prev_char != "\n" and next_char != "\n"
        if not is_boundary:
            index += 1
            continue

        end = index + 1
        while end < len(block_text) and block_text[end] in CLOSING_QUOTES:
            end += 1
        sentence_text = block_text[start:end].strip()
        if sentence_text:
            leading_ws = len(block_text[start:end]) - len(block_text[start:end].lstrip())
            trailing_ws = len(block_text[start:end]) - len(block_text[start:end].rstrip())
            spans.append(
                {
                    "text": sentence_text,
                    "char_start": block_start + start + leading_ws,
                    "char_end": block_start + end - trailing_ws,
                }
            )
        start = end
        index = end

    tail_text = block_text[start:].strip()
    if tail_text:
        raw_tail = block_text[start:]
        leading_ws = len(raw_tail) - len(raw_tail.lstrip())
        trailing_ws = len(raw_tail) - len(raw_tail.rstrip())
        spans.append(
            {
                "text": tail_text,
                "char_start": block_start + start + leading_ws,
                "char_end": block_start + len(block_text) - trailing_ws,
            }
        )
    return spans


def _sentence_window_chunks(
    doc_id: str,
    block_text: str,
    block_start: int,
    chunk_size: int,
    overlap: int,
    chunk_index_start: int,
) -> List[Dict[str, object]]:
    spans = _split_sentence_spans(block_text, block_start)
    if not spans:
        return []

    chunks: List[Dict[str, object]] = []
    sentence_index = 0
    chunk_index = chunk_index_start
    soft_limit = max(chunk_size, int(chunk_size * 1.35))

    while sentence_index < len(spans):
        current: List[Dict[str, object]] = []
        current_len = 0
        lookahead = sentence_index

        while lookahead < len(spans):
            span = spans[lookahead]
            span_len = len(str(span["text"]))
            projected_len = current_len + span_len + (1 if current else 0)
            if current and projected_len > chunk_size:
                if len(current) == 1 and projected_len <= soft_limit:
                    current.append(span)
                    current_len = projected_len
                    lookahead += 1
                break
            current.append(span)
            current_len = projected_len
            lookahead += 1
            if current_len >= chunk_size:
                break

        if not current:
            span = spans[lookahead]
            text = str(span["text"])
            current = [span]
            current_len = len(text)
            lookahead += 1

        chunk_text = " ".join(str(item["text"]).strip() for item in current).strip()
        chunks.append(
            {
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}::C{chunk_index:04d}",
                "chunk_index": chunk_index,
                "text": chunk_text,
                "char_start": int(current[0]["char_start"]),
                "char_end": int(current[-1]["char_end"]),
            }
        )
        chunk_index += 1

        if lookahead >= len(spans):
            break

        if overlap <= 0:
            sentence_index = lookahead
            continue

        overlap_chars = 0
        rewind = lookahead - 1
        while rewind > sentence_index and overlap_chars < overlap:
            overlap_chars += len(str(spans[rewind]["text"])) + 1
            rewind -= 1
        sentence_index = max(rewind + 1, sentence_index + 1)

    return chunks


def _append_chunk(
    chunks: List[Dict[str, object]],
    doc_id: str,
    chunk_index: int,
    text: str,
    char_start: int,
    char_end: int,
) -> int:
    chunk_text = text.strip()
    if not chunk_text:
        return chunk_index
    chunks.append(
        {
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}::C{chunk_index:04d}",
            "chunk_index": chunk_index,
            "text": chunk_text,
            "char_start": char_start,
            "char_end": char_end,
        }
    )
    return chunk_index + 1


def chunk_document_text(
    doc_id: str, text: str, chunk_size: int, overlap: int
) -> List[Dict[str, object]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and less than chunk_size")

    text = text.strip()
    if not text:
        return []

    blocks = _merge_heading_blocks(_extract_blocks(text))
    if not blocks:
        return []

    chunks: List[Dict[str, object]] = []
    chunk_index = 1
    pending_text = ""
    pending_start: int | None = None
    pending_end: int | None = None

    for block in blocks:
        block_text = str(block["text"]).strip()
        block_start = int(block["char_start"])
        block_end = int(block["char_end"])
        if not block_text:
            continue

        if len(block_text) > chunk_size:
            if pending_text:
                chunk_index = _append_chunk(
                    chunks,
                    doc_id,
                    chunk_index,
                    pending_text,
                    int(pending_start),
                    int(pending_end),
                )
                pending_text = ""
                pending_start = None
                pending_end = None
            block_chunks = _sentence_window_chunks(
                doc_id=doc_id,
                block_text=block_text,
                block_start=block_start,
                chunk_size=chunk_size,
                overlap=overlap,
                chunk_index_start=chunk_index,
            )
            if block_chunks:
                chunks.extend(block_chunks)
                chunk_index = int(block_chunks[-1]["chunk_index"]) + 1
            else:
                chunk_index = _append_chunk(
                    chunks,
                    doc_id,
                    chunk_index,
                    block_text[:chunk_size],
                    block_start,
                    min(block_start + chunk_size, block_end),
                )
            continue

        candidate_text = block_text if not pending_text else f"{pending_text}\n\n{block_text}"
        if pending_text and len(candidate_text) > chunk_size:
            chunk_index = _append_chunk(
                chunks,
                doc_id,
                chunk_index,
                pending_text,
                int(pending_start),
                int(pending_end),
            )
            pending_text = block_text
            pending_start = block_start
            pending_end = block_end
            continue

        pending_text = candidate_text
        pending_start = block_start if pending_start is None else pending_start
        pending_end = block_end

    if pending_text:
        _append_chunk(
            chunks,
            doc_id,
            chunk_index,
            pending_text,
            int(pending_start),
            int(pending_end),
        )

    return chunks
