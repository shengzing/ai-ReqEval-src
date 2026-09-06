"""Stage 3 contract validation and normalization helpers.

Stage 3 (Business Viability / Sample Probing) validates:
- sample_size > 0
- low_score_samples within valid range
- gap_to_target_pct range and consistency with target_sla
- actual_sla validity
- evidence_refs presence
- risk_level propagation from Stage 1
- 式(4) structural fields: atomic_tasks, rubric, actual_sla_by_dim
- error-rate hard constraints: fatal=0, general≤e_crit_max(R), audit≥A_audit_min(R)
- gap_grade five-tier + L3 escalation (§3.4.4)

Pure module — no FastAPI, repository, or model client imports.
Threshold constants are mirrored locally to avoid cross-module coupling
in the contract layer; the formulas package remains the single source of
truth for computation.
"""

from __future__ import annotations

from typing import Any

# ── Contract constraints ─────────────────────────────────────────────

MIN_SAMPLE_SIZE = 1
MAX_SAMPLE_SIZE = 10000
MIN_GAP_PCT = -100  # actual can exceed target
MAX_GAP_PCT = 100
ACTUAL_SLA_RANGE = (0.0, 100.0)

# ── Error-rate thresholds (mirror of formulas/thresholds.py §3.5.2) ──
# Local mirror to keep the contract layer pure; the formulas package is
# the single source of truth for computation.  These are initial
# reference values pending M2-M4 empirical calibration.
E_CRIT_MAX_BY_RISK: dict[str, float] = {
    "L1": 0.15,
    "L2": 0.10,
    "L3": 0.05,
}
A_AUDIT_MIN_BY_RISK: dict[str, float] = {
    "L1": 0.70,
    "L2": 0.85,
    "L3": 0.95,
}

# ── Gap grade vocabulary (§3.4.4) ─────────────────────────────────────
GAP_GRADE_PASS = "达标"
GAP_GRADE_MICRO = "微差"
GAP_GRADE_SIGNIFICANT = "显著差"
GAP_GRADE_LARGE = "大差"
GAP_GRADE_SEVERE = "严重失配"
_VALID_GAP_GRADES = {
    GAP_GRADE_PASS, GAP_GRADE_MICRO, GAP_GRADE_SIGNIFICANT,
    GAP_GRADE_LARGE, GAP_GRADE_SEVERE,
}

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

    # 5. Negative gap beyond 5pp for L3 scenarios requires attention.
    # gap_to_target_pct = Actual SLA - Target SLA; negative means under target.
    risk_level = summary.get("risk_level")
    if risk_level == "L3" and isinstance(gap, (int, float)) and gap < -5:
        issues.append({
            "issue_type": "sla_gap_l3",
            "field": "gap_to_target_pct",
            "severity": "high",
            "message": f"L3 scenario has an under-target SLA gap of {abs(gap):.1f}pp, exceeding 5pp; requires HITL review",
            "suggested_action": "Escalate for HITL review — L3 scenarios with under-target SLA gaps need domain expert sign-off",
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

    # ── 式(4) structural fields (P2-7) ──
    issues.extend(_validate_stage3_formula_artifacts(summary, risk_level))

    return issues


def _validate_stage3_formula_artifacts(
    summary: dict, risk_level: Any
) -> list[dict]:
    """Validate 式(4) structural artifacts and error-rate hard constraints.

    Checks (P2-7):
      10. atomic_tasks presence + field schema
      11. rubric three-dimension structure + hard-constraint items
      12. actual_sla_by_dim three-dim breakdown
      13. fatal_error_rate == 0 (硬约束: any fatal → nogo)
      14. general_error_rate ≤ e_crit_max(R)
      15. audit_completeness ≥ A_audit_min(R)
      16. gap_grade five-tier + L3 escalation consistency
    """
    issues: list[dict] = []

    # 10. atomic_tasks — optional but when present must be non-empty list
    atomic_tasks = summary.get("atomic_tasks")
    if atomic_tasks is not None:
        if not isinstance(atomic_tasks, list) or not atomic_tasks:
            issues.append({
                "issue_type": "invalid_value",
                "field": "atomic_tasks",
                "severity": "medium",
                "message": "atomic_tasks is present but empty or not a list",
                "suggested_action": "Run atomic_task_decomposer to produce atomic tasks",
            })
        else:
            # Check each task has the required dual-axis + sla_dim fields
            required = ("task_id", "non_routine", "interdependence", "sla_dim")
            for task in atomic_tasks:
                if not isinstance(task, dict):
                    continue
                tid = task.get("task_id", "<unknown>")
                missing = [f for f in required if f not in task or task[f] is None]
                if missing:
                    issues.append({
                        "issue_type": "missing_field",
                        "field": f"atomic_tasks.{tid}",
                        "severity": "medium",
                        "message": f"atomic task {tid} missing fields: {missing}",
                        "suggested_action": f"Complete {missing} for task {tid}",
                    })

    # 11. rubric — three-dimension structure
    rubric = summary.get("rubric")
    if rubric is not None:
        if not isinstance(rubric, dict):
            issues.append({
                "issue_type": "invalid_value",
                "field": "rubric",
                "severity": "medium",
                "message": "rubric is not a dict",
                "suggested_action": "Run rubric_designer to produce three-dim rubric",
            })
        else:
            for dim in ("qual", "eff", "gov"):
                items = rubric.get(dim)
                if items is None:
                    continue  # optional per-dim
                if not isinstance(items, list):
                    issues.append({
                        "issue_type": "invalid_value",
                        "field": f"rubric.{dim}",
                        "severity": "low",
                        "message": f"rubric.{dim} is not a list",
                        "suggested_action": f"Re-run rubric_designer for {dim} dimension",
                    })

    # 12. actual_sla_by_dim — three-dim breakdown
    actual_sla_by_dim = summary.get("actual_sla_by_dim")
    if actual_sla_by_dim is not None:
        if not isinstance(actual_sla_by_dim, dict):
            issues.append({
                "issue_type": "invalid_value",
                "field": "actual_sla_by_dim",
                "severity": "low",
                "message": "actual_sla_by_dim is not a dict",
                "suggested_action": "Recompute actual SLA via compute_actual_sla",
            })

    # 13. fatal_error_rate — 硬约束: must be 0 (§3.4.4/§3.5.2)
    fatal_error_rate = summary.get("fatal_error_rate")
    if fatal_error_rate is not None and isinstance(fatal_error_rate, (int, float)):
        if fatal_error_rate > 0:
            issues.append({
                "issue_type": "fatal_violation",
                "field": "fatal_error_rate",
                "severity": "critical",
                "message": f"fatal_error_rate={fatal_error_rate} > 0; 硬约束违反，任何致命错误强制 nogo",
                "suggested_action": "Eliminate fatal errors before proceeding; HITL mandatory review",
            })

    # 14. general_error_rate ≤ e_crit_max(R)
    general_error_rate = summary.get("general_error_rate")
    if (
        general_error_rate is not None
        and isinstance(general_error_rate, (int, float))
        and isinstance(risk_level, str)
    ):
        e_crit_max = E_CRIT_MAX_BY_RISK.get(risk_level)
        if e_crit_max is not None and general_error_rate > e_crit_max:
            issues.append({
                "issue_type": "general_error_exceeded",
                "field": "general_error_rate",
                "severity": "high",
                "message": f"general_error_rate={general_error_rate} > e_crit_max({risk_level})={e_crit_max}",
                "suggested_action": "Reduce general errors or escalate HITL review",
            })

    # 15. audit_completeness ≥ A_audit_min(R)
    audit_completeness = summary.get("audit_completeness")
    if (
        audit_completeness is not None
        and isinstance(audit_completeness, (int, float))
        and isinstance(risk_level, str)
    ):
        a_audit_min = A_AUDIT_MIN_BY_RISK.get(risk_level)
        if a_audit_min is not None and audit_completeness < a_audit_min:
            issues.append({
                "issue_type": "audit_completeness_below_floor",
                "field": "audit_completeness",
                "severity": "high",
                "message": f"audit_completeness={audit_completeness} < A_audit_min({risk_level})={a_audit_min}",
                "suggested_action": "Fill missing audit fields to meet completeness floor",
            })

    # 16. gap_grade — five-tier vocabulary + L3 escalation
    gap_grade = summary.get("gap_grade")
    if gap_grade is not None:
        if gap_grade not in _VALID_GAP_GRADES:
            issues.append({
                "issue_type": "invalid_enum",
                "field": "gap_grade",
                "severity": "medium",
                "message": f"gap_grade must be one of {_VALID_GAP_GRADES}, got {gap_grade!r}",
                "suggested_action": "Set gap_grade from grade_gap output",
            })
        elif risk_level == "L3" and gap_grade in (GAP_GRADE_SIGNIFICANT, GAP_GRADE_LARGE, GAP_GRADE_SEVERE):
            # L3 + gap_grade ≥ 显著差 → sla_gap_l3 escalation (§3.4.4)
            issues.append({
                "issue_type": "sla_gap_l3",
                "field": "gap_grade",
                "severity": "high",
                "message": f"L3 gap_grade={gap_grade} triggers sla_gap_l3 escalation to hard constraint",
                "suggested_action": "HITL review required — L3 scenarios with significant+ gap need domain expert sign-off",
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
    # gap = Actual SLA - Target SLA (pp): >=0 meets target, <0 under target.
    gap = summary.get("gap_to_target_pct")
    sla_alignment = 0.5  # Default
    if isinstance(gap, (int, float)):
        if gap >= 0:
            sla_alignment = 1.0  # Meeting or exceeding target
        elif gap >= -5:
            sla_alignment = 0.9
        elif gap >= -10:
            sla_alignment = 0.7
        elif gap >= -20:
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
