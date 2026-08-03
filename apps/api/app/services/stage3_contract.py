"""Stage 3 contract validation and normalization helpers.

Stage 3 (Business Viability / Sample Probing) validates:
- sample_size > 0
- low_score_samples within valid range
- gap_to_target_pct range and consistency with target_sla
- actual_sla validity
- evidence_refs presence
- risk_level propagation from Stage 1

Pure module — no FastAPI, repository, or model client imports.
"""

from __future__ import annotations

from typing import Any

# ── Contract constraints ─────────────────────────────────────────────

MIN_SAMPLE_SIZE = 1
MAX_SAMPLE_SIZE = 10000
MIN_GAP_PCT = -100  # actual can exceed target
MAX_GAP_PCT = 100
ACTUAL_SLA_RANGE = (0.0, 100.0)

# ── Normalization ─────────────────────────────────────────────────────


def normalize_sample_size(value: object) -> int:
    """Normalize a sample_size value to a positive int.

    Raises ``ValueError`` if non-positive or out of reasonable range.
    """
    if value is None:
        raise ValueError("sample_size is None; cannot normalize")

    try:
        num = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Cannot normalize sample_size: {value!r}")

    if not (MIN_SAMPLE_SIZE <= num <= MAX_SAMPLE_SIZE):
        raise ValueError(f"sample_size {num} out of range [{MIN_SAMPLE_SIZE}, {MAX_SAMPLE_SIZE}]")

    return num


def normalize_gap_to_target_pct(value: object) -> int:
    """Normalize a gap_to_target_pct value to an int in [-100, 100].

    Accepts percentage strings ("6%"), plain numbers, or ints.
    Raises ``ValueError`` if out of range or unparseable.
    """
    if value is None:
        raise ValueError("gap_to_target_pct is None; cannot normalize")

    if isinstance(value, (int, float)):
        num = int(value)
    else:
        text = str(value).strip().replace("%", "")
        try:
            num = int(float(text))
        except ValueError:
            raise ValueError(f"Cannot normalize gap_to_target_pct: {value!r}")

    if not (MIN_GAP_PCT <= num <= MAX_GAP_PCT):
        raise ValueError(f"gap_to_target_pct {num} out of range [{MIN_GAP_PCT}, {MAX_GAP_PCT}]")

    return num


def normalize_actual_sla(value: object) -> float:
    """Normalize an actual_sla value to a float in [0, 100]."""
    if value is None:
        raise ValueError("actual_sla is None; cannot normalize")

    if isinstance(value, (int, float)):
        num = float(value)
    else:
        text = str(value).strip().replace("%", "")
        try:
            num = float(text)
        except ValueError:
            raise ValueError(f"Cannot normalize actual_sla: {value!r}")

    if not (ACTUAL_SLA_RANGE[0] <= num <= ACTUAL_SLA_RANGE[1]):
        raise ValueError(f"actual_sla {num} out of range {ACTUAL_SLA_RANGE}")

    return round(num, 2)


# ── Validation ────────────────────────────────────────────────────────


def validate_stage3_summary(summary: dict, *, previous_stage_result: dict | None = None) -> list[dict]:
    """Validate a Stage 3 summary dict.

    Returns a list of issue dicts (empty if valid).  Each issue has:
      issue_type, field, severity, message, suggested_action.

    Does **not** mutate the input.
    """
    issues: list[dict] = []

    # 1. sample_size must be present and > 0
    sample_size = summary.get("sample_size")
    if sample_size is None:
        issues.append({
            "issue_type": "missing_field",
            "field": "sample_size",
            "severity": "high",
            "message": "sample_size is missing",
            "suggested_action": "Set sample_size from sample_score tool output",
        })
    elif not isinstance(sample_size, int) or sample_size < MIN_SAMPLE_SIZE:
        issues.append({
            "issue_type": "invalid_value",
            "field": "sample_size",
            "severity": "high",
            "message": f"sample_size must be >= {MIN_SAMPLE_SIZE}, got {sample_size!r}",
            "suggested_action": "Generate sample scores with valid sample count",
        })

    # 2. low_score_samples must be valid (>= 0, <= sample_size)
    low_score_samples = summary.get("low_score_samples")
    if low_score_samples is None:
        issues.append({
            "issue_type": "missing_field",
            "field": "low_score_samples",
            "severity": "medium",
            "message": "low_score_samples is missing",
            "suggested_action": "Set low_score_samples from sample_score tool output",
        })
    elif isinstance(sample_size, int) and isinstance(low_score_samples, int):
        if low_score_samples < 0:
            issues.append({
                "issue_type": "invalid_value",
                "field": "low_score_samples",
                "severity": "high",
                "message": f"low_score_samples must be >= 0, got {low_score_samples}",
                "suggested_action": "Correct low_score_samples count",
            })
        elif low_score_samples > sample_size:
            issues.append({
                "issue_type": "invalid_value",
                "field": "low_score_samples",
                "severity": "high",
                "message": f"low_score_samples ({low_score_samples}) exceeds sample_size ({sample_size})",
                "suggested_action": "Correct low_score_samples to be <= sample_size",
            })

    # 3. gap_to_target_pct must be present and valid
    gap = summary.get("gap_to_target_pct")
    if gap is None:
        issues.append({
            "issue_type": "missing_field",
            "field": "gap_to_target_pct",
            "severity": "medium",
            "message": "gap_to_target_pct is missing",
            "suggested_action": "Compute gap_to_target_pct from actual_sla_summary tool output",
        })
    elif isinstance(gap, (int, float)) and not (MIN_GAP_PCT <= gap <= MAX_GAP_PCT):
        issues.append({
            "issue_type": "out_of_range",
            "field": "gap_to_target_pct",
            "severity": "high",
            "message": f"gap_to_target_pct must be in [{MIN_GAP_PCT}, {MAX_GAP_PCT}], got {gap}",
            "suggested_action": "Recompute gap between actual and target SLA",
        })

    # 4. actual_sla must be valid if present
    actual_sla = summary.get("actual_sla")
    if actual_sla is not None and isinstance(actual_sla, (int, float)):
        if not (ACTUAL_SLA_RANGE[0] <= actual_sla <= ACTUAL_SLA_RANGE[1]):
            issues.append({
                "issue_type": "out_of_range",
                "field": "actual_sla",
                "severity": "high",
                "message": f"actual_sla must be in {ACTUAL_SLA_RANGE}, got {actual_sla}",
                "suggested_action": "Recompute actual SLA from sample scores",
            })

    # 5. Large gap for L3 scenarios requires attention
    risk_level = summary.get("risk_level")
    if risk_level == "L3" and isinstance(gap, (int, float)) and gap > 5:
        issues.append({
            "issue_type": "sla_gap_l3",
            "field": "gap_to_target_pct",
            "severity": "high",
            "message": f"L3 scenario has SLA gap of {gap}%, exceeding 5% threshold; requires HITL review",
            "suggested_action": "Escalate for HITL review — L3 scenarios with SLA gaps need domain expert sign-off",
        })

    # 6. Probe consistency: low_score_samples ratio should not be extreme
    if isinstance(sample_size, int) and isinstance(low_score_samples, int) and sample_size > 0:
        ratio = low_score_samples / sample_size
        if ratio > 0.5:
            issues.append({
                "issue_type": "high_failure_rate",
                "field": "low_score_samples",
                "severity": "medium",
                "message": f"Low-score ratio {ratio:.0%} exceeds 50%; consider redesigning task or model",
                "suggested_action": "Analyze root causes of low scores and consider task redesign",
            })

    # 7. evidence_refs must be non-empty
    evidence_refs = summary.get("evidence_refs", [])
    if not evidence_refs:
        issues.append({
            "issue_type": "weak_evidence",
            "field": "evidence_refs",
            "severity": "medium",
            "message": "Stage 3 summary has no evidence references",
            "suggested_action": "Bind evidence items from sample scoring and SLA measurement",
        })

    # 8. risk_level must be present
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
                "message": f"Stage 3 risk_level {risk_level!r} does not match Stage 1 risk_level {prev_risk!r}",
                "suggested_action": "Align risk_level with Stage 1 or document escalation reason",
            })

    # 9. stability must be valid if present
    stability = summary.get("stability")
    if stability is not None and stability not in {"confirmed", "needs_confirmation", "unstable"}:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "stability",
            "severity": "medium",
            "message": f"stability must be confirmed|needs_confirmation|unstable, got {stability!r}",
            "suggested_action": "Set stability from actual_sla_summary tool output",
        })

    return issues


# ── Quality scoring ────────────────────────────────────────────────────

_STAGE3_QUALITY_WEIGHTS = {
    "completeness": 0.20,
    "probe_consistency": 0.25,
    "evidence_coverage": 0.25,
    "risk_consistency": 0.15,
    "sla_alignment": 0.15,
}


def compute_stage3_quality(summary: dict) -> dict:
    """Compute quality scores for a Stage 3 summary.

    Returns a dict with six float scores in [0, 1]:
      completeness_score, probe_consistency_score, evidence_coverage_score,
      risk_consistency_score, sla_alignment_score, audit_readiness_score

    Does **not** mutate the input.
    """
    # Completeness: fraction of key fields present
    key_fields = [
        "sample_size", "low_score_samples", "gap_to_target_pct",
        "actual_sla", "risk_level", "evidence_refs",
    ]
    present = 0
    for field in key_fields:
        val = summary.get(field)
        if val is not None and val != "" and val != []:
            present += 1
    completeness = present / len(key_fields) if key_fields else 0.0

    # Probe consistency: low_score_samples ratio reasonable
    probe_consistency = 0.5  # Default moderate score
    sample_size = summary.get("sample_size")
    low_score_samples = summary.get("low_score_samples")
    if isinstance(sample_size, int) and isinstance(low_score_samples, int) and sample_size > 0:
        ratio = low_score_samples / sample_size
        if ratio <= 0.1:
            probe_consistency = 1.0
        elif ratio <= 0.3:
            probe_consistency = 0.8
        elif ratio <= 0.5:
            probe_consistency = 0.6
        else:
            probe_consistency = 0.3

    # Evidence coverage
    evidence_refs = summary.get("evidence_refs", [])
    evidence_coverage = 1.0 if evidence_refs else 0.0

    # Risk consistency: risk_level valid
    risk_level = summary.get("risk_level")
    risk_consistency = 1.0 if risk_level in {"L1", "L2", "L3"} else 0.0

    # SLA alignment: gap within acceptable range
    gap = summary.get("gap_to_target_pct")
    sla_alignment = 0.5  # Default
    if isinstance(gap, (int, float)):
        if gap <= 0:
            sla_alignment = 1.0  # Meeting or exceeding target
        elif gap <= 5:
            sla_alignment = 0.9
        elif gap <= 10:
            sla_alignment = 0.7
        elif gap <= 20:
            sla_alignment = 0.4
        else:
            sla_alignment = 0.2

    # Audit readiness: weighted combination
    audit_readiness = (
        completeness * _STAGE3_QUALITY_WEIGHTS["completeness"]
        + probe_consistency * _STAGE3_QUALITY_WEIGHTS["probe_consistency"]
        + evidence_coverage * _STAGE3_QUALITY_WEIGHTS["evidence_coverage"]
        + risk_consistency * _STAGE3_QUALITY_WEIGHTS["risk_consistency"]
        + sla_alignment * _STAGE3_QUALITY_WEIGHTS["sla_alignment"]
    )

    return {
        "completeness_score": round(completeness, 4),
        "probe_consistency_score": round(probe_consistency, 4),
        "evidence_coverage_score": round(evidence_coverage, 4),
        "risk_consistency_score": round(risk_consistency, 4),
        "sla_alignment_score": round(sla_alignment, 4),
        "audit_readiness_score": round(audit_readiness, 4),
    }
