"""3D alignment decision service — risk_level × target_sla × actual_sla → decision.

This service implements the Build-Evaluate closure that DSR requires:
given a scenario's risk grade (L1/L2/L3 from Stage 1), the target SLA
(e3-value back-deduction from Stage 2), and the actual SLA (TTF probe
results from Stage 3), it outputs one of three project-level decisions:

* ``approve``        — risk is acceptable, actual meets target → 立项
* ``defer``          — risk is acceptable but actual is below target   → 暂缓立项
* ``reject``         — risk is too high, or actual is far below target → 不予立项

The decision is the *final* output of the four-stage evaluation chain.
It is consumed by:
* ``_build_stage_specific_recommendation`` in ``autoresearch_service.py``
  (to add a ``3d_alignment`` block to the recommendation context)
* the ``maybe_interrupt`` node in ``graph.py`` (to escalate to human
  review when alignment is ``defer`` or ``reject``)

Pure module — no FastAPI, repository, or model client imports.
"""

from __future__ import annotations

from typing import Any, Optional

from .formulas.hard_constraint import (
    HardConstraintInput,
    compute_g_hard,
)
from .formulas.decision import (
    VERDICT_GO,
    VERDICT_HOLD,
    VERDICT_NOGO,
    build_remediation_items,
    compute_decision,
    grade_gap,
    validate_exit_alternative,
)
from .formulas.net_value import compute_actor_net_value


# ── Decision enum values ──────────────────────────────────────────────

DECISION_APPROVE = "approve"            # 立项
DECISION_DEFER = "defer"                # 暂缓立项
DECISION_REJECT = "reject"              # 不予立项
DECISION_INSUFFICIENT = "insufficient"  # 维度缺失，无法决策

ALIGNMENT_DECISIONS = frozenset({
    DECISION_APPROVE,
    DECISION_DEFER,
    DECISION_REJECT,
    DECISION_INSUFFICIENT,
})


# ── Thesis verdict mapping (go/hold/nogo ↔ approve/defer/reject) ──────
#
# The thesis (§3.5.2 式(6)) uses go/hold/nogo as the decision vocabulary.
# The codebase historically used approve/defer/reject/insufficient.  We
# keep the legacy enum for backward compatibility with existing callers
# (graph.py maybe_interrupt, autoresearch_service.py) and add a mapping
# layer so new code can use the thesis vocabulary.

THESIS_VERDICT_MAP: dict[str, str] = {
    DECISION_APPROVE: "go",
    DECISION_DEFER: "hold",
    DECISION_REJECT: "nogo",
    DECISION_INSUFFICIENT: "nogo",
}


def decision_to_thesis_verdict(decision: str) -> str:
    """Map a legacy decision enum to the thesis go/hold/nogo vocabulary."""
    return THESIS_VERDICT_MAP.get(decision, "nogo")


# ── Decision thresholds (single source of truth) ─────────────────────
#
# Sign convention (matches the thesis Δ_sla and stage3_contract's
# gap_to_target_pct): gap = Actual SLA − Target SLA, in percentage
# points.  Positive = actual meets/exceeds target; negative = actual
# falls short of target.

# target_sla minimum by risk level — e3-value back-deduction policy.
# L3 (regulatory/safety critical) needs ≥95% target; L1 ≥85%; L2 in between.
TARGET_SLA_FLOOR_BY_RISK: dict[str, float] = {
    "L1": 85.0,
    "L2": 90.0,
    "L3": 95.0,
}

# gap_to_target_pct = Actual SLA − Target SLA, in percentage points.
# Non-negative values mean the actual result meets or exceeds target.
ACCEPTABLE_GAP_PCT = 5.0

# A negative gap beyond 20 percentage points is a fundamental mismatch
# that warrants walking away.
REJECTION_GAP_PCT = -20.0


# ── Core decision function ───────────────────────────────────────────


def compute_3d_alignment(
    *,
    risk_level: Optional[str],
    target_sla: Optional[float],
    actual_sla: Optional[float],
    gap_to_target_pct: Optional[float] = None,
    # ── 式(5)/(6) extended inputs (optional, default to legacy single-dim path) ──
    prohibited_hit: Optional[bool] = None,
    fatal_error_rate: Optional[float] = None,
    general_error_rate: Optional[float] = None,
    audit_completeness: Optional[float] = None,
    hitl_triggered: Optional[bool] = None,
    sample_compliant: Optional[bool] = None,
    net_value: Optional[float] = None,
    actor_benefits: Optional[dict[str, float]] = None,
    actor_costs: Optional[dict[str, float]] = None,
    sensitivity_confirmed_negative: bool = False,
    alternative_flow_configured: bool = False,
) -> dict[str, Any]:
    """Decide project status from the three evaluation dimensions.

    **Two-mode operation:**

    * **Legacy single-dim mode** (default): only ``risk_level``,
      ``target_sla``, ``actual_sla`` are provided.  Uses the original
      gap-based rules (floor check → reject, gap<−20 → reject,
      gap<−5 → defer, else → approve).  Preserved for backward
      compatibility with existing callers that have not yet been
      migrated to the full 式(5)/(6) pipeline.

    * **Full 式(5)/(6) mode** (when any extended input is non-None):
      Computes ``G_hard`` via 式(5), then ``verdict`` via 式(6), then
      maps to the legacy enum.  Per-actor net value and reciprocity
      checks run when actor_benefits/costs are provided.

    Returns a dict with:
      * ``decision`` — approve|defer|reject|insufficient (legacy enum)
      * ``verdict`` — go|hold|nogo (thesis enum, added in full mode)
      * ``rationale`` — Chinese-language one-liner explaining the decision
      * ``inputs`` — echo of the inputs for traceability
      * ``missing_dimensions`` — which of the three dimensions are not yet available
      * (full mode only) ``G_hard``, ``g_hard_components``, ``failed_terms``,
        ``remediation_items``, ``actor_net_value``, ``exit_alternative_required``
    """
    missing: list[str] = []
    if not risk_level:
        missing.append("risk_level")
    if target_sla is None:
        missing.append("target_sla")
    if actual_sla is None:
        missing.append("actual_sla")

    if missing:
        return {
            "decision": DECISION_INSUFFICIENT,
            "verdict": "nogo",
            "rationale": "三维对齐决策所需维度不足：{0}".format("、".join(missing)),
            "inputs": {
                "risk_level": risk_level,
                "target_sla": target_sla,
                "actual_sla": actual_sla,
                "gap_to_target_pct": gap_to_target_pct,
            },
            "missing_dimensions": missing,
        }

    # Cast to float for arithmetic; safe because None already filtered.
    target_sla_f = float(target_sla)
    actual_sla_f = float(actual_sla)

    # Compute gap if not provided: gap = Actual − Target (pp).
    if gap_to_target_pct is None:
        gap_to_target_pct = round(actual_sla_f - target_sla_f, 2)

    inputs = {
        "risk_level": risk_level,
        "target_sla": target_sla_f,
        "actual_sla": actual_sla_f,
        "gap_to_target_pct": gap_to_target_pct,
    }

    # ── Check if full 式(5)/(6) mode is requested ───────────────
    extended_provided = any(v is not None for v in (
        prohibited_hit, fatal_error_rate, general_error_rate,
        audit_completeness, hitl_triggered, sample_compliant, net_value,
    ))

    if extended_provided:
        return _compute_full_mode(
            risk_level=risk_level,
            target_sla_f=target_sla_f,
            gap_to_target_pct=gap_to_target_pct,
            inputs=inputs,
            prohibited_hit=prohibited_hit,
            fatal_error_rate=fatal_error_rate,
            general_error_rate=general_error_rate,
            audit_completeness=audit_completeness,
            hitl_triggered=hitl_triggered,
            sample_compliant=sample_compliant,
            net_value=net_value,
            actor_benefits=actor_benefits,
            actor_costs=actor_costs,
            sensitivity_confirmed_negative=sensitivity_confirmed_negative,
            alternative_flow_configured=alternative_flow_configured,
        )

    # ── Legacy single-dim decision rules (backward-compatible) ──
    # Rule 1: risk_level must be one of the contract values.
    floor = TARGET_SLA_FLOOR_BY_RISK.get(risk_level)
    if floor is None:
        return {
            "decision": DECISION_INSUFFICIENT,
            "verdict": "nogo",
            "rationale": "risk_level {0!r} 不在合同枚举中（L1/L2/L3），无法决策。".format(risk_level),
            "inputs": inputs,
            "missing_dimensions": ["risk_level"],
        }

    # Rule 2: target_sla must meet the floor for the risk level.
    if target_sla_f < floor:
        return {
            "decision": DECISION_REJECT,
            "verdict": "nogo",
            "rationale": (
                "目标 SLA（{0:.1f}）低于风险等级 {1} 的最低门槛（{2:.1f}），"
                "且实际 SLA（{3:.1f}）与之差距 {4:.1f}pp，"
                "建议不予立项。"
            ).format(target_sla_f, risk_level, floor, actual_sla_f, gap_to_target_pct),
            "inputs": inputs,
            "missing_dimensions": [],
        }

    # Rule 3: a large negative gap → reject.
    if gap_to_target_pct < REJECTION_GAP_PCT:
        return {
            "decision": DECISION_REJECT,
            "verdict": "nogo",
            "rationale": (
                "实际 SLA（{0:.1f}）与目标 SLA（{1:.1f}）差距 {2:.1f}pp，"
                "超过 {3:.1f}pp 红线，建议不予立项。"
            ).format(actual_sla_f, target_sla_f, gap_to_target_pct, REJECTION_GAP_PCT),
            "inputs": inputs,
            "missing_dimensions": [],
        }

    # Rule 4: a moderate negative gap → defer (需要优化后再立项).
    if gap_to_target_pct < -ACCEPTABLE_GAP_PCT:
        return {
            "decision": DECISION_DEFER,
            "verdict": "hold",
            "rationale": (
                "实际 SLA（{0:.1f}）与目标 SLA（{1:.1f}）差距 {2:.1f}pp，"
                "建议暂缓立项并补强探针。"
            ).format(actual_sla_f, target_sla_f, gap_to_target_pct),
            "inputs": inputs,
            "missing_dimensions": [],
        }

    # Rule 5: gap within tolerance, or actual exceeds target → approve.
    return {
        "decision": DECISION_APPROVE,
        "verdict": "go",
        "rationale": (
            "风险等级 {0} 与目标/实际 SLA 对齐良好（差距 {1:.1f}pp），"
            "建议立项。"
        ).format(risk_level, gap_to_target_pct),
        "inputs": inputs,
        "missing_dimensions": [],
    }


def _compute_full_mode(
    *,
    risk_level: str,
    target_sla_f: float,
    gap_to_target_pct: float,
    inputs: dict[str, Any],
    prohibited_hit: Optional[bool],
    fatal_error_rate: Optional[float],
    general_error_rate: Optional[float],
    audit_completeness: Optional[float],
    hitl_triggered: Optional[bool],
    sample_compliant: Optional[bool],
    net_value: Optional[float],
    actor_benefits: Optional[dict[str, float]],
    actor_costs: Optional[dict[str, float]],
    sensitivity_confirmed_negative: bool,
    alternative_flow_configured: bool,
) -> dict[str, Any]:
    """Full 式(5)/(6) decision path — G_hard conjunction + three-state."""
    # ── 式(5): G_hard ───────────────────────────────────────────
    hc_input = HardConstraintInput(
        risk_level=risk_level,
        prohibited_hit=prohibited_hit,
        fatal_error_rate=fatal_error_rate,
        general_error_rate=general_error_rate,
        audit_completeness=audit_completeness,
        hitl_triggered=hitl_triggered,
        sample_compliant=sample_compliant,
        net_value=net_value,
    )
    g_hard_result = compute_g_hard(hc_input)
    g_hard = g_hard_result["G_hard"]

    # ── 式(6): verdict ──────────────────────────────────────────
    dec_result = compute_decision(
        g_hard=g_hard,
        delta_sla=gap_to_target_pct,
        net_value=net_value,
        sensitivity_confirmed_negative=sensitivity_confirmed_negative,
        risk_level=risk_level,
        target_sla=target_sla_f,
        failed_terms=g_hard_result["failed_terms"],
    )
    verdict = dec_result["verdict"]

    # Map thesis verdict → legacy decision enum
    verdict_to_decision = {
        VERDICT_GO: DECISION_APPROVE,
        VERDICT_HOLD: DECISION_DEFER,
        VERDICT_NOGO: DECISION_REJECT,
    }
    decision = verdict_to_decision.get(verdict, DECISION_INSUFFICIENT)

    # ── Exit-AI alternative validation (§3.5.3) ───────────────
    exit_alt = validate_exit_alternative(verdict, alternative_flow_configured)

    # ── Per-actor net value (if provided) ───────────────────────
    actor_result = None
    actor_masking_flag = False
    if actor_benefits is not None and actor_costs is not None:
        actor_result = compute_actor_net_value(actor_benefits, actor_costs)
        actor_masking_flag = actor_result["aggregation_masking"]

    result: dict[str, Any] = {
        "decision": decision,
        "verdict": verdict,
        "rationale": dec_result["decision_rationale"],
        "inputs": inputs,
        "missing_dimensions": [],
        # 式(5) artifacts
        "G_hard": g_hard,
        "g_hard_components": g_hard_result["g_hard_components"],
        "failed_terms": g_hard_result["failed_terms"],
        # 式(6) artifacts
        "remediation_items": dec_result["remediation_items"],
        "dec_path": dec_result["dec_path"],
        "gap_grade": dec_result.get("gap_grade"),
        # §3.5.3 exit alternative
        "exit_alternative_required": exit_alt["exit_alternative_required"],
        "exit_alternative_note": exit_alt["exit_alternative_note"],
        # per-actor masking
        "actor_masking_flag": actor_masking_flag,
    }
    if actor_result is not None:
        result["actor_net_value"] = actor_result["actor_net_value"]
        result["masking_actors"] = actor_result["masking_actors"]
    return result


# ── Convenience helpers ──────────────────────────────────────────────


def should_interrupt_for_human(alignment: dict[str, Any]) -> bool:
    """Return True if the alignment decision requires human approval.

    Used by ``maybe_interrupt`` in graph.py to decide whether to
    request a HITL review.  Defer and Reject always require human
    judgment (they are blocking); Approve with a tight margin
    (within 2pp of target) is advisory; Insufficient dimensions are
    blocking because the next stage cannot proceed without a decision.
    """
    decision = alignment.get("decision")
    if decision in {DECISION_DEFER, DECISION_REJECT, DECISION_INSUFFICIENT}:
        return True
    if decision == DECISION_APPROVE:
        gap = alignment.get("inputs", {}).get("gap_to_target_pct", 0.0)
        return float(gap) < 2.0  # Tight approval — ask for confirmation
    # Unknown decision — fail safe: ask for human review
    return True


def decision_to_recommendation(alignment: dict[str, Any]) -> str:
    """Map an alignment decision to the recommendation level used by
    ``_build_stage_specific_recommendation``.

    * approve → "low" (advisory, may auto-accept)
    * defer → "medium" (requires HITL)
    * reject → "high" (blocking, must escalate)
    * insufficient → "medium" (continue evaluation)
    """
    return {
        DECISION_APPROVE: "low",
        DECISION_DEFER: "medium",
        DECISION_REJECT: "high",
        DECISION_INSUFFICIENT: "medium",
    }.get(alignment.get("decision", ""), "medium")


def decision_to_chinese(decision: str) -> str:
    """Return the Chinese label for an alignment decision enum."""
    return {
        DECISION_APPROVE: "立项",
        DECISION_DEFER: "暂缓立项",
        DECISION_REJECT: "不予立项",
        DECISION_INSUFFICIENT: "维度缺失",
    }.get(decision, decision)
