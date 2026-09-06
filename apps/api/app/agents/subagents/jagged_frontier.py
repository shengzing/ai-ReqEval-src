"""P3-2 jagged-frontier — frontier in/out SLA stratification + alert (§3.4.3).

Thesis §3.4.3 (Dell'Acqua et al. 2026, DOI 10.1287/orsc.2025.21838):
GenAI capability follows a "jagged frontier" — tasks inside the
frontier (low non-routine + low interdependence) are executed well,
while tasks outside (high non-routine + high interdependence) see a
sharp accuracy drop (≈19pp lower in the original consulting study,
which is a theoretical inspiration, not a directly-migrated empirical
conclusion for this thesis scenario).

This Sub-agent stratifies atomic tasks into frontier-in vs frontier-out
by the dual-axis annotation from P2-1, computes separate Actual SLA
for each stratum, and raises a jagged-frontier alert when:

  * frontier_out sample share < 40% (§3.4.3: ≥40% oversampling to
    expose mismatch); or
  * frontier_out_sla < frontier_in_sla by more than 5pp (§3.4.3).

Even when the overall Actual SLA meets target, a frontier alert forces
a "task-difficulty-sensitive" annotation in §3.5 and a hold for
deliberation.

Mounted on the existing Stage 3 Skill — NOT a standalone 9-Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.apps.api.app.services.formulas import compute_actual_sla
from src.apps.api.app.services.formulas.actual_sla import ALL_DIMS

# ── Frontier thresholds (§3.4.3) ──────────────────────────────────────

# Dual-axis cutoff: tasks with non_routine ≥ 4 AND interdependence ≥ 4
# are "frontier-out" (high non-routine + high dependence).
FRONTIER_NON_ROUTINE_CUTOFF: int = 4
FRONTIER_INTERDEPENDENCE_CUTOFF: int = 4

# Frontier-out sample share: ≥ 40% (§3.4.3 oversampling requirement)
FRONTIER_OUT_MIN_SHARE: float = 0.40

# Frontier SLA gap alert: > 5pp (§3.4.3)
FRONTIER_GAP_ALERT_PP: float = 5.0


@dataclass
class JaggedFrontierResult:
    """Output of the jagged-frontier Sub-agent.

    Attributes:
        frontier_in_tasks: task_ids classified as frontier-in.
        frontier_out_tasks: task_ids classified as frontier-out.
        frontier_in_sla: Actual SLA for frontier-in stratum (None if no
            samples).
        frontier_out_sla: Actual SLA for frontier-out stratum.
        frontier_gap_pp: frontier_in_sla − frontier_out_sla (pp).
        frontier_alert: bool — True when gap > 5pp or out-share < 40%.
        out_share: fraction of samples assigned to frontier-out tasks.
        strata_breakdown: per-stratum {actual_sla, sample_count, tasks}.
        review_status: "complete" | "partial" | "empty".
        extraction_notes: human-readable notes.
    """

    frontier_in_tasks: list[str] = field(default_factory=list)
    frontier_out_tasks: list[str] = field(default_factory=list)
    frontier_in_sla: Optional[float] = None
    frontier_out_sla: Optional[float] = None
    frontier_gap_pp: Optional[float] = None
    frontier_alert: bool = False
    out_share: float = 0.0
    strata_breakdown: dict[str, Any] = field(default_factory=dict)
    review_status: str = "empty"
    extraction_notes: list[str] = field(default_factory=list)


def analyze_jagged_frontier(
    *,
    atomic_tasks: list[dict] | None = None,
    rubric_scores: list[dict] | None = None,
    samples: list[dict] | None = None,
    w_d: dict[str, float] | None = None,
) -> JaggedFrontierResult:
    """Stratify tasks into frontier-in/out + compute per-stratum SLA.

    Args:
        atomic_tasks: from P2-1, each with non_routine/interdependence.
        rubric_scores: merged rubric scores from P3-1 probe-scorer.
        samples: probe samples (for sample-count + task linkage).
        w_d: three-dimension weights (default W_D_DEFAULT).

    Returns:
        JaggedFrontierResult with frontier alert flag.
    """
    notes: list[str] = []

    if not atomic_tasks or not rubric_scores:
        return JaggedFrontierResult(
            review_status="empty",
            extraction_notes=["No atomic_tasks or rubric_scores provided."],
        )

    # ── Classify tasks into frontier-in / frontier-out ──
    in_tasks: list[str] = []
    out_tasks: list[str] = []
    task_stratum: dict[str, str] = {}

    for task in atomic_tasks:
        tid = task.get("task_id", "")
        if not tid:
            continue
        nr = task.get("non_routine")
        idp = task.get("interdependence")
        if (
            isinstance(nr, (int, float))
            and isinstance(idp, (int, float))
            and nr >= FRONTIER_NON_ROUTINE_CUTOFF
            and idp >= FRONTIER_INTERDEPENDENCE_CUTOFF
        ):
            out_tasks.append(tid)
            task_stratum[tid] = "out"
        else:
            in_tasks.append(tid)
            task_stratum[tid] = "in"

    # ── Partition rubric scores by stratum ──
    in_scores: list[dict[str, Any]] = []
    out_scores: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []

    for score in rubric_scores:
        tid = score.get("task_id", "")
        stratum = task_stratum.get(tid)
        if stratum == "out":
            out_scores.append(score)
        elif stratum == "in":
            in_scores.append(score)
        else:
            unclassified.append(score)

    # ── Compute per-stratum Actual SLA (式(4)) ──
    in_result = compute_actual_sla(rubric_scores=in_scores, w_d=w_d) if in_scores else None
    out_result = compute_actual_sla(rubric_scores=out_scores, w_d=w_d) if out_scores else None

    in_sla = in_result["actual_sla"] if in_result else None
    out_sla = out_result["actual_sla"] if out_result else None

    # ── Frontier gap (pp) ──
    gap_pp: Optional[float] = None
    if in_sla is not None and out_sla is not None:
        gap_pp = round(in_sla - out_sla, 2)

    # ── Out-share (fraction of samples in frontier-out tasks) ──
    total_samples = len({s.get("sample_id") for s in rubric_scores if s.get("sample_id")})
    out_samples = len({s.get("sample_id") for s in out_scores if s.get("sample_id")})
    out_share = round(out_samples / total_samples, 4) if total_samples else 0.0

    # ── Alert conditions ──
    alert = False
    alert_reasons: list[str] = []

    if gap_pp is not None and gap_pp > FRONTIER_GAP_ALERT_PP:
        alert = True
        alert_reasons.append(
            f"前沿外 SLA 低于前沿内 {gap_pp}pp (> {FRONTIER_GAP_ALERT_PP}pp 阈值)"
        )

    if total_samples > 0 and out_share < FRONTIER_OUT_MIN_SHARE:
        alert = True
        alert_reasons.append(
            f"前沿外样本占比 {out_share:.0%} < {FRONTIER_OUT_MIN_SHARE:.0%} 下限"
        )

    if alert:
        notes.append(
            "jagged frontier 告警：" + "；".join(alert_reasons)
            + "。即使整体达标也须在 §3.5 标注任务难度敏感并暂缓论证。"
        )

    # ── Review status ──
    if in_sla is not None and out_sla is not None:
        review_status = "complete"
    elif in_sla is not None or out_sla is not None:
        review_status = "partial"
    else:
        review_status = "empty"

    strata_breakdown = {
        "in": {
            "actual_sla": in_sla,
            "sample_count": len({s.get("sample_id") for s in in_scores if s.get("sample_id")}),
            "tasks": in_tasks,
        },
        "out": {
            "actual_sla": out_sla,
            "sample_count": len({s.get("sample_id") for s in out_scores if s.get("sample_id")}),
            "tasks": out_tasks,
        },
        "unclassified_count": len(unclassified),
    }

    return JaggedFrontierResult(
        frontier_in_tasks=in_tasks,
        frontier_out_tasks=out_tasks,
        frontier_in_sla=in_sla,
        frontier_out_sla=out_sla,
        frontier_gap_pp=gap_pp,
        frontier_alert=alert,
        out_share=out_share,
        strata_breakdown=strata_breakdown,
        review_status=review_status,
        extraction_notes=notes,
    )
