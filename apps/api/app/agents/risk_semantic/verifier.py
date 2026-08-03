"""Evidence chain semantic verifier — LLM-augmented evidence-risk binding verification.

When the LLM client is configured, sends (risk_item.description, evidence_snippet)
pairs to the LLM for semantic verification. When unconfigured (or on LLM error),
falls back to rule-based word-overlap verification.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.apps.api.app.agents.risk_semantic.models import (
    EvidenceChainReport,
    EvidenceVerificationResult,
)
from src.apps.api.app.agents.risk_semantic.verifier_prompts import (
    EVIDENCE_VERIFICATION_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def verify_evidence_chain(
    risk_items: list[dict[str, Any]],
    evidence_snippets: dict[str, str],
    *,
    llm_client: Any = None,
    batch_size: int = 5,
) -> EvidenceChainReport:
    """Verify that evidence snippets actually support risk item descriptions.

    Args:
        risk_items: List of risk item dicts, each with at least
            'risk_id' and 'evidence_refs' fields.
        evidence_snippets: Mapping of evidence_id → snippet text.
        llm_client: Optional HarnessLLMClient for LLM-based verification.
        batch_size: Max risk items per LLM call (for token limits).

    Returns:
        EvidenceChainReport with per-item verification results.
    """
    results: list[EvidenceVerificationResult] = []
    unverified: list[str] = []

    for item in risk_items:
        risk_id = item.get("risk_id", "unknown")
        description = item.get("description", "")
        ev_refs = item.get("evidence_refs", [])

        if not ev_refs:
            # No evidence → cannot verify
            results.append(EvidenceVerificationResult(
                risk_id=risk_id,
                evidence_id="",
                supports=False,
                confidence=0.0,
                reasoning="风险项无证据引用，无法验证",
                source="rule",
            ))
            unverified.append(risk_id)
            continue

        # Verify against each evidence ref (use first for simplicity)
        primary_ev_id = ev_refs[0]
        snippet = evidence_snippets.get(primary_ev_id, "")

        if not snippet:
            results.append(EvidenceVerificationResult(
                risk_id=risk_id,
                evidence_id=primary_ev_id,
                supports=False,
                confidence=0.0,
                reasoning=f"证据 {primary_ev_id} 无内容",
                source="rule",
            ))
            unverified.append(risk_id)
            continue

        # Attempt LLM verification
        llm_result = _try_llm_verify(
            risk_id=risk_id,
            evidence_id=primary_ev_id,
            description=description,
            snippet=snippet,
            llm_client=llm_client,
        )

        if llm_result is not None:
            results.append(llm_result)
            if not llm_result.supports:
                unverified.append(risk_id)
        else:
            # Fall back to rule-based verification
            rule_result = _rule_based_verify(risk_id, primary_ev_id, description, snippet)
            results.append(rule_result)
            if not rule_result.supports:
                unverified.append(risk_id)

    # Compute overall score
    supported_count = sum(1 for r in results if r.supports)
    overall_score = supported_count / len(results) if results else 0.0

    return EvidenceChainReport(
        results=results,
        overall_score=round(overall_score, 4),
        unverified_items=unverified,
    )


def _try_llm_verify(
    *,
    risk_id: str,
    evidence_id: str,
    description: str,
    snippet: str,
    llm_client: Any = None,
) -> EvidenceVerificationResult | None:
    """Attempt LLM-based evidence verification. Returns None on failure."""
    if llm_client is None:
        return None

    user_payload = {
        "risk_description": description[:500],
        "evidence_snippet": snippet[:2000],
    }

    try:
        response = llm_client.complete_json(
            system_prompt=EVIDENCE_VERIFICATION_SYSTEM_PROMPT,
            user_payload=user_payload,
        )
    except Exception:
        logger.warning("LLM evidence verification failed, using rule-based", exc_info=True)
        return None

    if not response:
        return None

    return _normalize_llm_verify_output(response, risk_id, evidence_id)


def _normalize_llm_verify_output(
    response: dict[str, Any],
    risk_id: str,
    evidence_id: str,
) -> EvidenceVerificationResult | None:
    """Normalize LLM verification output. Returns None if invalid."""
    supports = response.get("supports")
    if not isinstance(supports, bool):
        # Try to coerce
        if isinstance(supports, str):
            supports = supports.lower() in {"true", "yes", "1", "支持"}
        else:
            logger.warning("LLM returned non-boolean 'supports': %r", supports)
            return None

    confidence = response.get("confidence", 0.5)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (ValueError, TypeError):
        confidence = 0.5

    reasoning = str(response.get("reasoning", ""))

    return EvidenceVerificationResult(
        risk_id=risk_id,
        evidence_id=evidence_id,
        supports=supports,
        confidence=confidence,
        reasoning=reasoning,
        source="llm",
    )


# ── Chinese stop-words for meaningful word extraction ──────────────────────────

_STOP_CHARS = set("的了是在不有和就都而及与或但虽说从被把让给向对于为着过")

_MEANINGLESS_PATTERNS = re.compile(
    r"^(?:这|那|此|该|其|另|一|些|种|类|项|个|条|件|事|情|况|样|方|面|"
    r"部|分|内|外|中|上|下|前|后|间|时|期|般|性|化|等|之|所|以)$"
)


def _extract_meaningful_words(text: str, min_len: int = 2) -> set[str]:
    """Extract meaningful Chinese words from text for overlap comparison.

    Uses simple character-window segmentation: consecutive non-stop-char
    sequences of at least *min_len* characters, filtered against common
    function words.
    """
    words: set[str] = set()
    # Find runs of non-stop characters
    current: list[str] = []
    for ch in text:
        if ch in _STOP_CHARS or ch.isspace() or ch in "，。、；：！？（）【】""''—\"":
            if len(current) >= min_len:
                word = "".join(current)
                if not _MEANINGLESS_PATTERNS.match(word):
                    words.add(word)
            current = []
        else:
            current.append(ch)

    # Handle trailing segment
    if len(current) >= min_len:
        word = "".join(current)
        if not _MEANINGLESS_PATTERNS.match(word):
            words.add(word)

    return words


def _rule_based_verify(
    risk_id: str,
    evidence_id: str,
    description: str,
    snippet: str,
) -> EvidenceVerificationResult:
    """Rule-based evidence verification using word overlap.

    A risk item is considered supported if at least 2 meaningful words
    from its description appear in the evidence snippet. Single-word
    overlap is not sufficient to avoid false positives from common terms.
    """
    desc_words = _extract_meaningful_words(description)
    snippet_words = _extract_meaningful_words(snippet)

    overlap = desc_words & snippet_words
    overlap_count = len(overlap)

    supports = overlap_count >= 2
    confidence = min(0.9, 0.3 + 0.2 * overlap_count) if supports else min(0.4, 0.1 + 0.1 * overlap_count)

    overlap_str = ", ".join(sorted(overlap)) if overlap else "无"
    reasoning = (
        f"关键词重叠数: {overlap_count}, 重叠词: {overlap_str}; "
        + ("语义支撑充分" if supports else "语义支撑不足")
    )

    return EvidenceVerificationResult(
        risk_id=risk_id,
        evidence_id=evidence_id,
        supports=supports,
        confidence=round(confidence, 4),
        reasoning=reasoning,
        source="rule",
    )
