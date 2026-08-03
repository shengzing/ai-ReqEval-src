"""Semantic risk classifier — LLM-augmented risk identification.

When the LLM client is configured, sends a RiskBrief to the LLM for
semantic risk classification. When unconfigured (or on LLM error),
falls back to deterministic keyword-based logic identical to the
pre-refactor system.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.apps.api.app.agents.risk_semantic.models import (
    RiskBrief,
    SemanticRiskResult,
)
from src.apps.api.app.agents.risk_semantic.prompts import RISK_CLASSIFICATION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def classify_risk_semantic(
    brief: RiskBrief,
    *,
    llm_client: Any = None,
) -> SemanticRiskResult:
    """Classify risk using LLM (when available) or deterministic fallback.

    Args:
        brief: Context summary for risk classification.
        llm_client: Optional HarnessLLMClient instance. When None or
            unconfigured (returns {}), deterministic fallback is used.

    Returns:
        SemanticRiskResult with source="llm" or source="fallback".
    """
    # Attempt LLM classification
    llm_result = _try_llm_classify(brief, llm_client=llm_client)
    if llm_result is not None:
        return llm_result

    # Deterministic fallback
    return _fallback_classify(brief)


def _try_llm_classify(
    brief: RiskBrief,
    *,
    llm_client: Any = None,
) -> SemanticRiskResult | None:
    """Attempt LLM-based classification. Returns None on failure (to trigger fallback)."""
    if llm_client is None:
        return None

    # Build user payload from RiskBrief
    user_payload = {
        "scenario_name": brief.scenario_name,
        "combined_text": brief.combined_text[:3000],  # Truncate for token limits
        "keyword_hits_l3": brief.keyword_hits_l3,
        "keyword_hits_l2": brief.keyword_hits_l2,
        "negated_keywords": sorted(brief.negated_keywords),
        "known_risk_points": brief.known_risk_points,
        "prohibited_conditions": brief.prohibited_conditions,
        "boundary_flag": brief.boundary_flag,
    }

    try:
        response = llm_client.complete_json(
            system_prompt=RISK_CLASSIFICATION_SYSTEM_PROMPT,
            user_payload=user_payload,
        )
    except Exception:
        logger.warning("LLM classification failed, using fallback", exc_info=True)
        return None

    if not response:
        return None

    # Normalize and validate LLM output
    return _normalize_llm_output(response, brief)


def _normalize_llm_output(
    response: dict[str, Any],
    brief: RiskBrief,
) -> SemanticRiskResult | None:
    """Normalize LLM JSON response into a SemanticRiskResult.

    Returns None if the output cannot be normalized (invalid risk_level
    or hitl_level that cannot be mapped to contract enums).
    """
    from src.apps.api.app.services.stage1_contract import (
        HITL_LEVELS,
        RISK_LEVELS,
        normalize_hitl_level,
        normalize_risk_level,
    )

    # Normalize risk_level
    raw_risk = response.get("risk_level", "")
    try:
        risk_level = normalize_risk_level(raw_risk)
    except (ValueError, TypeError):
        logger.warning("LLM returned invalid risk_level %r, using fallback", raw_risk)
        return None

    # Normalize hitl_level
    raw_hitl = response.get("hitl_level", "")
    try:
        hitl_level = normalize_hitl_level(raw_hitl, risk_level=risk_level)
    except (ValueError, TypeError):
        logger.warning("LLM returned invalid hitl_level %r, using fallback", raw_hitl)
        return None

    # Extract risk_items_semantic
    risk_items_semantic = response.get("risk_items_semantic", [])
    if not isinstance(risk_items_semantic, list):
        risk_items_semantic = []

    # Extract confidence (clamp to [0, 1])
    confidence = response.get("confidence", 0.5)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (ValueError, TypeError):
        confidence = 0.5

    # Extract reasoning
    reasoning = str(response.get("reasoning", ""))

    # Extract boundary_flag
    boundary_flag = bool(response.get("boundary_flag", brief.boundary_flag))

    return SemanticRiskResult(
        risk_level=risk_level,
        hitl_level=hitl_level,
        risk_items_semantic=risk_items_semantic,
        confidence=confidence,
        reasoning=reasoning,
        boundary_flag=boundary_flag,
        source="llm",
    )


def _fallback_classify(brief: RiskBrief) -> SemanticRiskResult:
    """Deterministic fallback classification using keyword hits.

    This produces output identical to the pre-refactor risk_identify_tool
    keyword logic. Keywords are pre-screening triggers; the classifier
    decides final risk_level based on them.
    """
    from src.apps.api.app.services.stage1_contract import normalize_hitl_level

    # Determine risk level from keyword hits
    if brief.keyword_hits_l3:
        risk_level = "L3"
    elif brief.keyword_hits_l2:
        risk_level = "L2"
    else:
        risk_level = "L1"

    # Determine HITL level
    if risk_level == "L3":
        # Check for mandatory conditions from known_risk_points and prohibited_conditions
        mandatory_keywords = ["不得自动", "必须人工确认", "风险等级调整", "客户处置", "监管敏感"]
        combined = brief.combined_text
        is_mandatory = any(kw in combined for kw in mandatory_keywords)
        raw_hitl = "mandatory" if is_mandatory else "strict"
    elif risk_level == "L2":
        raw_hitl = "standard"
    else:
        raw_hitl = "none"

    hitl_level = normalize_hitl_level(raw_hitl, risk_level=risk_level)

    # Build reasoning from keyword hits
    parts = []
    if brief.keyword_hits_l3:
        parts.append(f"L3关键词命中: {', '.join(brief.keyword_hits_l3)}")
    if brief.keyword_hits_l2:
        parts.append(f"L2关键词命中: {', '.join(brief.keyword_hits_l2)}")
    if brief.negated_keywords:
        parts.append(f"否定关键词: {', '.join(sorted(brief.negated_keywords))}")
    if brief.boundary_flag:
        parts.append("L2+L3同时命中，标记等级边界")

    reasoning = "; ".join(parts) if parts else "无关键词命中，判定为L1低风险"

    # Confidence heuristic: more keyword hits → higher confidence
    total_hits = len(brief.keyword_hits_l3) + len(brief.keyword_hits_l2)
    confidence = min(0.9, 0.5 + 0.1 * total_hits) if total_hits > 0 else 0.3

    return SemanticRiskResult(
        risk_level=risk_level,
        hitl_level=hitl_level,
        risk_items_semantic=[],  # Fallback doesn't produce semantic risk items
        confidence=confidence,
        reasoning=reasoning,
        boundary_flag=brief.boundary_flag,
        source="fallback",
    )
