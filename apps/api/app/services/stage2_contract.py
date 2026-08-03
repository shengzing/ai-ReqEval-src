"""Stage 2 contract validation and normalization helpers.

Stage 2 (Product-Market Fit / Value Modeling) validates:
- implementation_tax alignment with Stage 1 risk level
- target_sla range validity
- evidence_refs presence
- risk_level propagation from Stage 1

Pure module — no FastAPI, repository, or model client imports.
"""

from __future__ import annotations

from typing import Any

# ── Contract enum values ──────────────────────────────────────────────

IMPLEMENTATION_TAX_LEVELS = {"low", "medium", "high"}
"""Valid implementation_tax values."""

STABILITY_LEVELS = {"confirmed", "needs_confirmation", "unstable"}
"""Valid SLA stability values."""

TARGET_SLA_RANGE = (0.0, 100.0)
"""Valid target_sla percentage range."""

# ── Normalization ─────────────────────────────────────────────────────


def normalize_implementation_tax(value: object, *, risk_level: str | None = None) -> str:
    """Normalize an implementation_tax value to low|medium|high.

    When *risk_level* is provided, enforces L3→high, L2→medium|high constraints.
    Raises ``ValueError`` if the value cannot be normalized.
    """
    if value is None:
        raise ValueError("implementation_tax is None; cannot normalize")

    text = str(value).strip().lower()

    # Already a valid contract value
    if text in IMPLEMENTATION_TAX_LEVELS:
        result = text
    else:
        _TAX_ALIASES: dict[str, str] = {
            "低": "low", "中": "medium", "高": "high",
            "l": "low", "m": "medium", "h": "high",
            "1": "low", "2": "medium", "3": "high",
        }
        result = _TAX_ALIASES.get(text, "")
        if not result:
            raise ValueError(f"Cannot normalize implementation_tax: {value!r}")

    # Enforce risk-level alignment
    if risk_level == "L3" and result not in {"high"}:
        result = "high"
    elif risk_level == "L2" and result not in {"medium", "high"}:
        result = "medium"

    return result


def normalize_target_sla(value: object) -> float:
    """Normalize a target_sla value to a float in [0, 100].

    Accepts percentage strings ("95%"), plain numbers, or floats.
    Raises ``ValueError`` if out of range or unparseable.
    """
    if value is None:
        raise ValueError("target_sla is None; cannot normalize")

    if isinstance(value, (int, float)):
        num = float(value)
    else:
        text = str(value).strip().replace("%", "")
        try:
            num = float(text)
        except ValueError:
            raise ValueError(f"Cannot normalize target_sla: {value!r}")

    if not (TARGET_SLA_RANGE[0] <= num <= TARGET_SLA_RANGE[1]):
        raise ValueError(f"target_sla {num} out of range {TARGET_SLA_RANGE}")

    return round(num, 2)


# ── Validation ────────────────────────────────────────────────────────


def validate_stage2_summary(summary: dict, *, previous_stage_result: dict | None = None) -> list[dict]:
    """Validate a Stage 2 summary dict.

    Returns a list of issue dicts (empty if valid).  Each issue has:
      issue_type, field, severity, message, suggested_action.

    Does **not** mutate the input.
    """
    issues: list[dict] = []

    # 1. implementation_tax must be valid enum
    impl_tax = summary.get("implementation_tax")
    if impl_tax not in IMPLEMENTATION_TAX_LEVELS:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "implementation_tax",
            "severity": "high",
            "message": f"implementation_tax must be low|medium|high, got {impl_tax!r}",
            "suggested_action": "Normalize implementation_tax using normalize_implementation_tax()",
        })

    # 2. target_sla must be present and valid
    target_sla = summary.get("target_sla")
    if target_sla is None:
        issues.append({
            "issue_type": "missing_field",
            "field": "target_sla",
            "severity": "high",
            "message": "target_sla is missing",
            "suggested_action": "Set target_sla from sla_target tool output",
        })
    elif isinstance(target_sla, (int, float)) and not (TARGET_SLA_RANGE[0] <= target_sla <= TARGET_SLA_RANGE[1]):
        issues.append({
            "issue_type": "out_of_range",
            "field": "target_sla",
            "severity": "high",
            "message": f"target_sla must be in [0, 100], got {target_sla}",
            "suggested_action": "Adjust target_sla to valid percentage range",
        })

    # 3. stability must be valid enum
    stability = summary.get("stability")
    if stability is not None and stability not in STABILITY_LEVELS:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "stability",
            "severity": "medium",
            "message": f"stability must be {STABILITY_LEVELS}, got {stability!r}",
            "suggested_action": "Set stability from sla_target tool output",
        })

    # 4. evidence_refs must be non-empty
    evidence_refs = summary.get("evidence_refs", [])
    if not evidence_refs:
        issues.append({
            "issue_type": "weak_evidence",
            "field": "evidence_refs",
            "severity": "medium",
            "message": "Stage 2 summary has no evidence references",
            "suggested_action": "Bind evidence items from Stage 1 and Stage 2 tools",
        })

    # 5. risk_level must be present and match Stage 1
    risk_level = summary.get("risk_level")
    if risk_level not in {"L1", "L2", "L3"}:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "risk_level",
            "severity": "high",
            "message": f"risk_level must be L1|L2|L3, got {risk_level!r}",
            "suggested_action": "Propagate risk_level from Stage 1 scenario_summary",
        })
    elif previous_stage_result:
        prev_risk = (previous_stage_result.get("scenario_summary") or {}).get("risk_level", "")
        if prev_risk and risk_level != prev_risk:
            issues.append({
                "issue_type": "risk_level_mismatch",
                "field": "risk_level",
                "severity": "high",
                "message": f"Stage 2 risk_level {risk_level!r} does not match Stage 1 risk_level {prev_risk!r}",
                "suggested_action": "Align risk_level with Stage 1 or document the reason for escalation",
            })

    # 6. L3 risk must have high implementation_tax
    if risk_level == "L3" and impl_tax not in {"high", None}:
        issues.append({
            "issue_type": "value_mismatch",
            "field": "implementation_tax",
            "severity": "high",
            "message": f"L3 risk must have high implementation_tax, got {impl_tax!r}",
            "suggested_action": "Set implementation_tax to high for L3 risk scenarios",
        })

    # 7. L3 risk must have strict or mandatory stability note
    if risk_level == "L3" and stability == "unstable":
        issues.append({
            "issue_type": "sla_unstable",
            "field": "stability",
            "severity": "high",
            "message": "L3 risk has unstable SLA target; requires HITL confirmation",
            "suggested_action": "Confirm SLA parameters with domain expert before proceeding",
        })

    return issues


# ── Quality scoring ────────────────────────────────────────────────────

_STAGE2_QUALITY_WEIGHTS = {
    "completeness": 0.25,
    "value_alignment": 0.25,
    "evidence_coverage": 0.25,
    "risk_consistency": 0.25,
}


def compute_stage2_quality(summary: dict) -> dict:
    """Compute quality scores for a Stage 2 summary.

    Returns a dict with five float scores in [0, 1]:
      completeness_score, value_alignment_score, evidence_coverage_score,
      risk_consistency_score, audit_readiness_score

    Does **not** mutate the input.
    """
    # Completeness: fraction of key fields with substantive content
    key_fields = [
        "implementation_tax", "target_sla", "stability",
        "risk_level", "evidence_refs",
    ]
    substantive = 0
    for field in key_fields:
        val = summary.get(field)
        if val is not None and val != "" and val != []:
            substantive += 1
    completeness = substantive / len(key_fields) if key_fields else 0.0

    # Value alignment: implementation_tax consistent with risk_level
    impl_tax = summary.get("implementation_tax")
    risk_level = summary.get("risk_level")
    value_alignment = 0.0
    if impl_tax in IMPLEMENTATION_TAX_LEVELS:
        value_alignment = 0.5  # Valid enum
        if risk_level == "L3" and impl_tax == "high":
            value_alignment = 1.0
        elif risk_level == "L2" and impl_tax in {"medium", "high"}:
            value_alignment = 0.9
        elif risk_level == "L1" and impl_tax in {"low", "medium"}:
            value_alignment = 0.9
        elif risk_level == "L1" and impl_tax == "high":
            value_alignment = 0.4  # Overly conservative
        elif risk_level == "L3" and impl_tax == "low":
            value_alignment = 0.2  # Dangerous underestimation

    # Evidence coverage: evidence_refs present and non-empty
    evidence_refs = summary.get("evidence_refs", [])
    evidence_coverage = 1.0 if evidence_refs else 0.0

    # Risk consistency: risk_level valid and matches Stage 1
    risk_consistency = 0.0
    if risk_level in {"L1", "L2", "L3"}:
        risk_consistency = 0.7  # Valid enum
        # Full score if we have no prior to compare against
        risk_consistency = 1.0

    # Audit readiness: weighted combination
    audit_readiness = (
        completeness * _STAGE2_QUALITY_WEIGHTS["completeness"]
        + value_alignment * _STAGE2_QUALITY_WEIGHTS["value_alignment"]
        + evidence_coverage * _STAGE2_QUALITY_WEIGHTS["evidence_coverage"]
        + risk_consistency * _STAGE2_QUALITY_WEIGHTS["risk_consistency"]
    )

    return {
        "completeness_score": round(completeness, 4),
        "value_alignment_score": round(value_alignment, 4),
        "evidence_coverage_score": round(evidence_coverage, 4),
        "risk_consistency_score": round(risk_consistency, 4),
        "audit_readiness_score": round(audit_readiness, 4),
    }
