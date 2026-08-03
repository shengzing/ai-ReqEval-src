"""Risk level confidence distribution — heuristic + LLM.

Produces a probability distribution over {L1, L2, L3} based on
keyword hits and evidence chain quality. When the LLM client is
configured, augments or overrides the heuristic distribution.

The `risk_confidence` field is additive — `risk_level` remains a
discrete enum. When absent, all existing code paths behave identically.
"""

from __future__ import annotations

import logging
from typing import Any

from src.apps.api.app.agents.risk_semantic.models import (
    RiskConfidenceDistribution,
    SemanticRiskResult,
    EvidenceChainReport,
)
from src.apps.api.app.services.stage1_contract import RISK_LEVELS

logger = logging.getLogger(__name__)

# Boundary threshold: top-2 levels within this distance → boundary_flag
_BOUNDARY_THRESHOLD = 0.15


def compute_risk_confidence_distribution(
    semantic_result: SemanticRiskResult,
    evidence_report: EvidenceChainReport | None = None,
    *,
    llm_client: Any = None,
) -> RiskConfidenceDistribution:
    """Compute a confidence distribution over risk levels.

    Args:
        semantic_result: The semantic classification result (fallback or LLM).
        evidence_report: Optional evidence chain report; its overall_score
            adjusts confidence toward L3 when low (evidence doesn't support).
        llm_client: Optional HarnessLLMClient; if configured and the
            semantic_result came from LLM, extract distribution from LLM output.

    Returns:
        RiskConfidenceDistribution with L1/L2/L3 probabilities.
    """
    # If LLM produced a distribution in the semantic result, prefer it
    if semantic_result.source == "llm" and _has_llm_distribution(semantic_result):
        return _extract_llm_distribution(semantic_result)

    # Heuristic computation from keyword hits + evidence
    return _heuristic_distribution(semantic_result, evidence_report)


def _has_llm_distribution(result: SemanticRiskResult) -> bool:
    """Check if LLM result includes confidence distribution data."""
    # LLM may attach distribution in risk_items_semantic extras
    # or the distribution may be embedded in the result dict
    # For now, check if any risk_item has a "confidence_distribution" key
    for item in result.risk_items_semantic:
        if isinstance(item, dict) and "confidence_distribution" in item:
            return True
    return False


def _extract_llm_distribution(
    result: SemanticRiskResult,
) -> RiskConfidenceDistribution:
    """Extract LLM-provided confidence distribution from semantic result."""
    for item in result.risk_items_semantic:
        if isinstance(item, dict) and "confidence_distribution" in item:
            dist = item["confidence_distribution"]
            try:
                l1 = float(dist.get("L1", 0.0))
                l2 = float(dist.get("L2", 0.0))
                l3 = float(dist.get("L3", 0.0))
                # Normalize to sum=1.0
                total = l1 + l2 + l3
                if total > 0:
                    l1, l2, l3 = l1 / total, l2 / total, l3 / total
            except (ValueError, TypeError):
                logger.warning("Invalid LLM confidence distribution, falling back to heuristic")
                return _heuristic_distribution_from_levels(result.risk_level, result.confidence)

            levels = {"L1": l1, "L2": l2, "L3": l3}
            dominant = max(levels, key=levels.get)
            sorted_vals = sorted(levels.values(), reverse=True)
            boundary = (sorted_vals[0] - sorted_vals[1]) < _BOUNDARY_THRESHOLD

            return RiskConfidenceDistribution(
                L1=round(l1, 4),
                L2=round(l2, 4),
                L3=round(l3, 4),
                dominant_level=dominant,
                boundary_flag=boundary,
                source="llm",
            )

    # Fallback if no valid distribution found
    return _heuristic_distribution_from_levels(result.risk_level, result.confidence)


def _heuristic_distribution(
    semantic_result: SemanticRiskResult,
    evidence_report: EvidenceChainReport | None = None,
) -> RiskConfidenceDistribution:
    """Compute heuristic confidence distribution from keyword hits and evidence.

    Logic:
    - L3 keyword hits → L3-dominant distribution
    - L2-only hits → L2-dominant
    - No hits → L1-dominant
    - Low evidence score pushes probability toward L3 (uncertainty increases risk)
    """
    risk_level = semantic_result.risk_level
    base_confidence = semantic_result.confidence

    return _heuristic_distribution_from_levels(risk_level, base_confidence, evidence_report)


def _heuristic_distribution_from_levels(
    risk_level: str,
    base_confidence: float,
    evidence_report: EvidenceChainReport | None = None,
) -> RiskConfidenceDistribution:
    """Build heuristic distribution from a risk level and confidence.

    Args:
        risk_level: L1, L2, or L3.
        base_confidence: Classifier confidence in the risk level.
        evidence_report: Optional; low evidence_score shifts mass toward L3.

    Returns:
        RiskConfidenceDistribution with heuristic probabilities.
    """
    if risk_level not in RISK_LEVELS:
        risk_level = "L1"  # default

    # Base distributions per risk level
    if risk_level == "L3":
        l3 = 0.5 + 0.3 * base_confidence  # 0.5 - 0.8
        l2 = (1.0 - l3) * 0.6
        l1 = 1.0 - l3 - l2
    elif risk_level == "L2":
        l2 = 0.5 + 0.3 * base_confidence  # 0.5 - 0.8
        l3 = (1.0 - l2) * 0.4
        l1 = 1.0 - l2 - l3
    else:  # L1
        l1 = 0.5 + 0.3 * base_confidence  # 0.5 - 0.8
        l2 = (1.0 - l1) * 0.6
        l3 = 1.0 - l1 - l2

    # Evidence quality adjustment: low evidence score → shift toward L3
    if evidence_report is not None:
        evidence_score = evidence_report.overall_score
        if evidence_score < 0.5:
            # Low evidence quality → increase L3 uncertainty
            shift = 0.1 * (1.0 - evidence_score)
            l3 += shift
            l1 -= shift * 0.5
            l2 -= shift * 0.5
            # Clamp negatives
            l1 = max(0.0, l1)
            l2 = max(0.0, l2)
            # Re-normalize
            total = l1 + l2 + l3
            if total > 0:
                l1, l2, l3 = l1 / total, l2 / total, l3 / total

    levels = {"L1": l1, "L2": l2, "L3": l3}
    dominant = max(levels, key=levels.get)
    sorted_vals = sorted(levels.values(), reverse=True)
    boundary = (sorted_vals[0] - sorted_vals[1]) < _BOUNDARY_THRESHOLD

    return RiskConfidenceDistribution(
        L1=round(l1, 4),
        L2=round(l2, 4),
        L3=round(l3, 4),
        dominant_level=dominant,
        boundary_flag=boundary,
        source="heuristic",
    )
