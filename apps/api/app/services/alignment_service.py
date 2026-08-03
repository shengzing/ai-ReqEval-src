"""3D alignment decision service — risk_level × target_sla × actual_sla → decision.

This service implements the Build-Evaluate closure that DSR requires:
given a scenario's risk grade (L1/L2/L3 from Stage 1), the target SLA
(e3-value back-deduction from Stage 2), and the actual SLA (TTF probe
results from Stage 3), it outputs one of three project-level decisions:

* ``approve``        — risk is acceptable, target is met by actual → 立项
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


# ── Decision thresholds (single source of truth) ─────────────────────

# target_sla minimum by risk level — e3-value back-deduction policy.
# L3 (regulatory/safety critical) needs ≥95% target; L1 ≥85%; L2 in between.
TARGET_SLA_FLOOR_BY_RISK: dict[str, float] = {
    "L1": 85.0,
    "L2": 90.0,
    "L3": 95.0,
}

# gap_to_target_pct below which Actual SLA is considered "meeting target".
# 5 percentage points tolerance: a small probe jitter is acceptable.
ACCEPTABLE_GAP_PCT = 5.0

# gap_to_target_pct above which we recommend reject even for L1.
# A 20-point gap is a fundamental mismatch that warrants walking away.
REJECTION_GAP_PCT = 20.0


# ── Core decision function ───────────────────────────────────────────


def compute_3d_alignment(
    *,
    risk_level: Optional[str],
    target_sla: Optional[float],
    actual_sla: Optional[float],
    gap_to_target_pct: Optional[float] = None,
) -> dict[str, Any]:
    """Decide project status from the three evaluation dimensions.

    Returns a dict with:
      * ``decision`` — one of ``approve``/``defer``/``reject``/``insufficient``
      * ``rationale`` — Chinese-language one-liner explaining the decision
      * ``inputs`` — echo of the inputs (risk_level, target_sla,
        actual_sla, gap_to_target_pct) for traceability
      * ``missing_dimensions`` — which of the three dimensions are
        not yet available (used by the caller to decide whether the
        decision is binding)
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

    # Compute gap if not provided.
    if gap_to_target_pct is None:
        gap_to_target_pct = round(target_sla_f - actual_sla_f, 2)

    inputs = {
        "risk_level": risk_level,
        "target_sla": target_sla_f,
        "actual_sla": actual_sla_f,
        "gap_to_target_pct": gap_to_target_pct,
    }

    # ── Decision rules ───────────────────────────────────────────
    # Rule 1: risk_level must be one of the contract values.
    floor = TARGET_SLA_FLOOR_BY_RISK.get(risk_level)
    if floor is None:
        return {
            "decision": DECISION_INSUFFICIENT,
            "rationale": "risk_level {0!r} 不在合同枚举中（L1/L2/L3），无法决策。".format(risk_level),
            "inputs": inputs,
            "missing_dimensions": ["risk_level"],
        }

    # Rule 2: target_sla must meet the floor for the risk level.
    if target_sla_f < floor:
        return {
            "decision": DECISION_REJECT,
            "rationale": (
                "目标 SLA（{0:.1f}）低于风险等级 {1} 的最低门槛（{2:.1f}），"
                "且实际 SLA（{3:.1f}）与之差距 {4:.1f}pp，"
                "建议不予立项。"
            ).format(target_sla_f, risk_level, floor, actual_sla_f, gap_to_target_pct),
            "inputs": inputs,
            "missing_dimensions": [],
        }

    # Rule 3: large gap → reject.
    if gap_to_target_pct > REJECTION_GAP_PCT:
        return {
            "decision": DECISION_REJECT,
            "rationale": (
                "实际 SLA（{0:.1f}）与目标 SLA（{1:.1f}）差距 {2:.1f}pp，"
                "超过 {3:.1f}pp 红线，建议不予立项。"
            ).format(actual_sla_f, target_sla_f, gap_to_target_pct, REJECTION_GAP_PCT),
            "inputs": inputs,
            "missing_dimensions": [],
        }

    # Rule 4: small gap → defer (需要优化后再立项).
    if gap_to_target_pct > ACCEPTABLE_GAP_PCT:
        return {
            "decision": DECISION_DEFER,
            "rationale": (
                "实际 SLA（{0:.1f}）与目标 SLA（{1:.1f}）差距 {2:.1f}pp，"
                "建议暂缓立项并补强探针。"
            ).format(actual_sla_f, target_sla_f, gap_to_target_pct),
            "inputs": inputs,
            "missing_dimensions": [],
        }

    # Rule 5: gap within tolerance → approve.
    return {
        "decision": DECISION_APPROVE,
        "rationale": (
            "风险等级 {0} 与目标/实际 SLA 对齐良好（差距 {1:.1f}pp），"
            "建议立项。"
        ).format(risk_level, gap_to_target_pct),
        "inputs": inputs,
        "missing_dimensions": [],
    }


# ── Convenience helpers ──────────────────────────────────────────────


def should_interrupt_for_human(alignment: dict[str, Any]) -> bool:
    """Return True if the alignment decision requires human approval.

    Used by ``maybe_interrupt`` in graph.py to decide whether to
    request a HITL review.  Defer and Reject always require human
    judgment (they are blocking); Approve with a tight margin
    (<2pp) is advisory; Insufficient dimensions are blocking because
    the next stage cannot proceed without a decision.
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
