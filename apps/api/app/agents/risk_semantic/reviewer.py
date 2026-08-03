"""Semantic risk review second-opinion — LLM-augmented risk reviewer.

When the LLM client is configured, asks the LLM for a second-opinion review
that augments the rule-based ``_review_risk`` in ``subagents.py``.  When
unconfigured (or on LLM error), returns an empty ``RiskReviewResult`` so
``_review_risk``'s output is byte-identical to the pre-upgrade baseline
(additional_issues: []).
"""

from __future__ import annotations

import logging
from typing import Any

from src.apps.api.app.agents.risk_semantic.models import RiskReviewResult
from src.apps.api.app.agents.risk_semantic.reviewer_prompts import (
    RISK_REVIEW_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def review_risk_semantic(
    scenario_summary: dict[str, Any],
    existing_issues: list[dict[str, Any]],
    *,
    llm_client: Any = None,
) -> RiskReviewResult:
    """LLM second-opinion review of *scenario_summary*.

    Args:
        scenario_summary: The full stage-1 summary dict under review.
        existing_issues: Issues already produced by rule-based validation.
            Used as input so the LLM can avoid duplicates and reason
            about coverage gaps.
        llm_client: Optional HarnessLLMClient. When None or unconfigured,
            returns an empty ``RiskReviewResult`` (fallback).

    Returns:
        RiskReviewResult with additional_issues / suggestions / confidence
        / reasoning / source label.
    """
    llm_result = _try_llm_review(
        scenario_summary,
        existing_issues=existing_issues,
        llm_client=llm_client,
    )
    if llm_result is not None:
        return llm_result
    return RiskReviewResult(source="fallback")


# ── LLM path ───────────────────────────────────────────────────────────────


def _try_llm_review(
    scenario_summary: dict[str, Any],
    *,
    existing_issues: list[dict[str, Any]],
    llm_client: Any = None,
) -> RiskReviewResult | None:
    """Attempt LLM-based review. Returns None on failure (→ empty fallback)."""
    if llm_client is None:
        return None

    user_payload = {
        "scenario_summary": _summarise_for_review(scenario_summary),
        "existing_issues": existing_issues,
    }

    try:
        response = llm_client.complete_json(
            system_prompt=RISK_REVIEW_SYSTEM_PROMPT,
            user_payload=user_payload,
        )
    except Exception:
        logger.warning("LLM risk review failed, using fallback", exc_info=True)
        return None

    if not isinstance(response, dict):
        return None

    return _normalize_llm_output(response)


def _normalize_llm_output(response: dict[str, Any]) -> RiskReviewResult | None:
    """Normalize LLM JSON into a RiskReviewResult.

    Returns None if the response cannot be normalized — caller falls back.
    """
    raw_issues = response.get("additional_issues", [])
    if not isinstance(raw_issues, list):
        return None

    additional_issues: list[dict[str, Any]] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        issue_type = str(raw.get("issue_type", "")).strip()
        field = str(raw.get("field", "")).strip()
        message = str(raw.get("message", "")).strip()
        severity = str(raw.get("severity", "medium")).strip().lower()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        # require at least an issue_type + message to count as actionable
        if not issue_type or not message:
            continue
        additional_issues.append({
            "issue_type": issue_type,
            "field": field,
            "severity": severity,
            "message": message,
            "suggested_action": str(raw.get("suggested_action", "")),
        })

    raw_suggestions = response.get("suggestions", [])
    suggestions: list[str] = []
    if isinstance(raw_suggestions, list):
        for s in raw_suggestions:
            if isinstance(s, str) and s.strip():
                suggestions.append(s.strip())

    confidence_raw = response.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reasoning = str(response.get("reasoning", ""))

    return RiskReviewResult(
        additional_issues=additional_issues,
        suggestions=suggestions,
        confidence=confidence,
        reasoning=reasoning,
        source="llm",
    )


# ── Shared helpers ─────────────────────────────────────────────────────────


# Fields that are useful for the LLM to reason about.  Limit size to keep
# the prompt bounded while still giving the LLM enough structure to find
# semantic gaps.
_REVIEW_SUMMARY_FIELDS = (
    "scenario_name",
    "scenario_type",
    "risk_level",
    "hitl_level",
    "risk_items",
    "hitl_rules",
    "process_nodes",
    "prohibited_conditions",
    "fatal_errors",
    "evidence_refs",
    "audit_requirements",
    "boundary_flag",
    "boundary",
)


def _summarise_for_review(scenario_summary: dict[str, Any]) -> dict[str, Any]:
    """Project scenario_summary to the fields a reviewer needs.

    Keeps process_nodes lean (just node_id + name + human_review_required)
    and risk_items lean (risk_id + description + risk_level + node_id).
    """
    summary: dict[str, Any] = {}
    for field in _REVIEW_SUMMARY_FIELDS:
        if field in scenario_summary:
            summary[field] = scenario_summary[field]

    nodes = scenario_summary.get("process_nodes", [])
    if isinstance(nodes, list):
        summary["process_nodes"] = [
            {
                "node_id": str(n.get("node_id", "")),
                "name": str(n.get("name", "")),
                "human_review_required": bool(n.get("human_review_required")),
                "owner_role": str(n.get("owner_role", "")),
            }
            for n in nodes
            if isinstance(n, dict)
        ]

    items = scenario_summary.get("risk_items", [])
    if isinstance(items, list):
        summary["risk_items"] = [
            {
                "risk_id": str(it.get("risk_id", "")),
                "description": str(it.get("description", "")),
                "risk_level": str(it.get("risk_level", "")),
                "node_id": str(it.get("node_id", "")),
            }
            for it in items
            if isinstance(it, dict)
        ]

    rules = scenario_summary.get("hitl_rules", [])
    if isinstance(rules, list):
        summary["hitl_rules"] = [
            {
                "rule_id": str(r.get("rule_id", "")),
                "review_level": str(r.get("review_level", "")),
                "review_owner": str(r.get("review_owner", "")),
                "node_id": str(r.get("node_id", "")),
            }
            for r in rules
            if isinstance(r, dict)
        ]

    return summary