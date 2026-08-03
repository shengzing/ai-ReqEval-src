"""Semantic patch builder — LLM-augmented refinement patches.

When the LLM client is configured, asks the LLM to propose a semantic
patch for an issue identified by contract validation.  When unconfigured
(or on LLM error / low confidence / whitelist violation), returns ``None``
so callers fall back to the deterministic hardcoded patch templates in
``autoresearch_service._build_suggested_patch``.

The LLM path is gated by ``_WHITELISTED_PATCH_FIELDS`` to ensure contract
safety: any patch referencing a non-whitelisted field is dropped at the
normalize step.
"""

from __future__ import annotations

import logging
from typing import Any

from src.apps.api.app.agents.risk_semantic.patcher_prompts import (
    SEMANTIC_PATCH_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


# Mirrors autoresearch_service._WHITELISTED_PATCH_FIELDS — local copy to
# avoid an import cycle (autoresearch_service imports from this module for
# the LLM path).
_WHITELISTED_PATCH_FIELDS = frozenset({
    "risk_level", "boundary", "risk_items", "risk_matrix",
    "hitl_rules", "hitl_level", "audit_requirements",
    "prohibited_conditions", "fatal_errors", "to_confirm",
    "risk_confidence",
    "implementation_tax", "target_sla", "stability",
    "sample_size", "low_score_samples", "actual_sla", "gap_to_target_pct",
    "bundle_status", "report_status", "decision_card", "export_ready",
    "evidence_count", "sections", "gaps", "blocking_issues",
})

# Patch operations the AutoResearch loop accepts.  Anything outside this
# set is rejected.
_VALID_PATCH_OPS = frozenset({"replace", "add", "multi"})

# Issues where the LLM may have a meaningful semantic edge over the
# hardcoded template.  Outside this set we still fall through to the
# deterministic template for consistency.
_PATCHABLE_ISSUE_TYPES = frozenset({
    "invalid_enum",
    "missing_field",
    "hitl_mismatch",
    "value_mismatch",
    "placeholder_content",
    "confidence_mismatch",
})


def build_semantic_patch(
    issue: dict[str, Any],
    scenario_summary: dict[str, Any],
    *,
    llm_client: Any = None,
) -> dict[str, Any] | None:
    """Build a semantic patch dict for an issue.

    Returns ``None`` if the LLM path is unavailable or returns a patch
    that fails whitelist / shape validation.  Callers should fall through
    to ``_build_suggested_patch`` when this returns ``None``.
    """
    issue_type = str(issue.get("issue_type", ""))
    if issue_type not in _PATCHABLE_ISSUE_TYPES:
        return None

    patch = _try_llm_patch(issue, scenario_summary, llm_client=llm_client)
    if patch is not None and _patch_passes_gates(patch):
        return patch

    return None


# ── LLM path ───────────────────────────────────────────────────────────────


def _try_llm_patch(
    issue: dict[str, Any],
    scenario_summary: dict[str, Any],
    *,
    llm_client: Any = None,
) -> dict[str, Any] | None:
    """Attempt LLM-based patch generation. Returns None on failure."""
    if llm_client is None:
        return None

    user_payload = {
        "issue": issue,
        "scenario_summary": _summarise_for_patch(scenario_summary),
    }

    try:
        response = llm_client.complete_json(
            system_prompt=SEMANTIC_PATCH_SYSTEM_PROMPT,
            user_payload=user_payload,
        )
    except Exception:
        logger.warning("LLM semantic patch failed, using fallback", exc_info=True)
        return None

    if not isinstance(response, dict):
        return None
    if str(response.get("op", "")).strip().lower() == "skip":
        return None

    return response


def _patch_passes_gates(patch: dict[str, Any]) -> bool:
    """Validate the LLM-returned patch against whitelist + shape gates.

    Returns True only when every field in the patch is whitelisted, the
    ``op`` is recognised, and ``multi`` patches contain at least one
    valid sub-patch.  Drops evidence_refs-protection patches.
    """
    op = str(patch.get("op", "")).strip().lower()
    if op not in _VALID_PATCH_OPS:
        return False

    if op == "multi":
        sub_patches = patch.get("patches", [])
        if not isinstance(sub_patches, list) or not sub_patches:
            return False
        for sub in sub_patches:
            if not isinstance(sub, dict):
                return False
            field = str(sub.get("field", "")).strip()
            if not field or field not in _WHITELISTED_PATCH_FIELDS:
                return False
            if field == "evidence_refs":
                return False
        return True

    field = str(patch.get("field", "")).strip()
    if not field or field not in _WHITELISTED_PATCH_FIELDS:
        return False
    if field == "evidence_refs":
        return False
    if "value" not in patch:
        return False
    return True


# ── Shared helpers ─────────────────────────────────────────────────────────


# Same projection used by ``reviewer._summarise_for_review`` — limit the
# payload to fields the LLM needs to reason about a patch.
_PATCH_SUMMARY_FIELDS = (
    "scenario_name",
    "scenario_type",
    "risk_level",
    "hitl_level",
    "risk_items",
    "risk_matrix",
    "hitl_rules",
    "process_nodes",
    "prohibited_conditions",
    "fatal_errors",
    "evidence_refs",
    "audit_requirements",
    "boundary",
    "boundary_flag",
    "implementation_tax",
    "target_sla",
    "stability",
)


def _summarise_for_patch(scenario_summary: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for field in _PATCH_SUMMARY_FIELDS:
        if field in scenario_summary:
            summary[field] = scenario_summary[field]
    return summary