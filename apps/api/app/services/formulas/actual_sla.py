"""式(4) Actual SLA aggregation + error-rate/audit-completeness fields.

Thesis §3.4.4 式(4):

    SLA_act = Σ_d w_d · SLA_act,d,  d ∈ {qual, eff, gov}

Where each ``SLA_act,d`` is computed from the per-dimension Rubric scoring
items, 4-tier normalized (0 / 0.33 / 0.67 / 1.0) weighted aggregation,
then ×100 to express as a percentage.  Efficiency scores are reverse-
normalized (1 − normalized_time) before weighting so all three dims
point "higher is better".

§3.4.4 also defines:

    fatal_error_rate   = fatal_count / total_samples          (硬约束 = 0)
    general_error_rate = general_count / total_samples        (≤ e_crit_max(R))
    audit_completeness = filled_fields / required_fields      (≥ A_audit_min(R))

Gap grading is delegated to ``decision.grade_gap`` (§3.4.4 five-tier
table + L3 escalation) — kept there because the decision module owns
the gap-grade vocabulary.

Pure module — no FastAPI, repository, or LLM imports.  Parameters
marked "初始参考值" are Delphi priors pending M2-M4 empirical
calibration; they must not be presented as confirmed case results.
"""

from __future__ import annotations

from typing import Any, Optional

from .thresholds import (
    A_AUDIT_MIN_BY_RISK,
    CRITICAL_AUDIT_FIELDS,
    E_CRIT_MAX_BY_RISK,
    GAP_GRADE_THRESHOLDS,
    W_D_DEFAULT,
)

# ── Dimension identifiers (mirror target_sla) ─────────────────────────

DIM_QUAL = "qual"
DIM_EFF = "eff"
DIM_GOV = "gov"
ALL_DIMS: tuple[str, ...] = (DIM_QUAL, DIM_EFF, DIM_GOV)

# ── 4-tier grade scale (§3.4.4) ───────────────────────────────────────

GRADE_SCALE: dict[str, float] = {
    "0": 0.0,
    "0.33": 0.33,
    "0.67": 0.67,
    "1.0": 1.0,
}

DEFAULT_GRADE: float = 0.0  # missing/unknown rubric items score 0


# ═══════════════════════════════════════════════════════════════════════
# 式(4) Actual SLA aggregation
# ═══════════════════════════════════════════════════════════════════════


def compute_actual_sla(
    *,
    rubric_scores: list[dict[str, Any]],
    w_d: Optional[dict[str, float]] = None,
    atomic_tasks: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Compute 式(4) SLA_act = Σ_d w_d · SLA_act,d.

    Each entry in *rubric_scores*:
        {
          "sample_id": str,
          "task_id": str,
          "dim": "qual" | "eff" | "gov",
          "item": str (rubric item name, e.g. "事实一致性"),
          "grade": "0" | "0.33" | "0.67" | "1.0" | float,
          "weight": float (optional, per-item weight within dim),
          "reverse_normalize": bool (optional; True for efficiency items),
        }

    The aggregation proceeds per dimension:
      1. Group items by (sample_id, dim) → weighted mean grade ∈ [0, 1]
      2. For efficiency dim, reverse-normalize: score = 1 − mean_time
         (caller may pre-reverse by setting grade=1−raw; or set
         ``reverse_normalize=True`` and pass raw normalized time)
      3. Average across samples within each dim → SLA_act,d
      4. SLA_act,d × 100 → percentage
      5. SLA_act = Σ_d w_d · SLA_act,d

    Args:
        rubric_scores: list of per-sample per-dimension rubric item scores.
        w_d: three-dimension weights (default W_D_DEFAULT; L3 w_gov ≥ 0.3).
        atomic_tasks: optional atomic-task list — used only for task-level
            breakdown; if provided, each task's per-dim score is included
            in the result.

    Returns:
        ``{actual_sla, actual_sla_by_dim, score_distribution, per_task, missing}``
    """
    if w_d is None:
        w_d = W_D_DEFAULT

    if not rubric_scores:
        return {
            "actual_sla": 0.0,
            "actual_sla_by_dim": {d: 0.0 for d in ALL_DIMS},
            "score_distribution": {"high": 0, "medium": 0, "low": 0},
            "per_task": [],
            "missing": ["rubric_scores"],
            "formula": "SLA_act = Σ_d w_d · SLA_act,d",
        }

    # ── Phase 1: group items by (sample_id, dim) → weighted mean ──
    sample_dim_scores: dict[tuple[str, str], float] = {}
    for item in rubric_scores:
        sample_id = item.get("sample_id", "")
        dim = item.get("dim", "")
        if dim not in ALL_DIMS:
            continue
        grade = _resolve_grade(item.get("grade"))
        weight = _num(item.get("weight")) or 1.0
        reverse = bool(item.get("reverse_normalize", False))
        if reverse:
            grade = 1.0 - grade
        key = (sample_id, dim)
        # Accumulate weighted sum via rolling mean
        prev = sample_dim_scores.get(key)
        if prev is None:
            sample_dim_scores[key] = grade * weight
        else:
            # Simple weighted mean: we store (sum_grade*weight, sum_weight)
            # using a tuple proxy is messy — use a list of (sum_gw, sum_w)
            sample_dim_scores[key] = prev  # placeholder, handled below
    # Re-aggregate properly with weighted means
    sample_dim_agg: dict[tuple[str, str], list[float]] = {k: [] for k in sample_dim_scores}
    sample_dim_w: dict[tuple[str, str], list[float]] = {k: [] for k in sample_dim_scores}
    for item in rubric_scores:
        sample_id = item.get("sample_id", "")
        dim = item.get("dim", "")
        if dim not in ALL_DIMS:
            continue
        grade = _resolve_grade(item.get("grade"))
        weight = _num(item.get("weight")) or 1.0
        if bool(item.get("reverse_normalize", False)):
            grade = 1.0 - grade
        key = (sample_id, dim)
        sample_dim_agg[key].append(grade * weight)
        sample_dim_w[key].append(weight)

    # ── Phase 2: per-sample per-dim score = Σ(gw) / Σ(w) ──
    sample_dim_final: dict[tuple[str, str], float] = {}
    for key in sample_dim_agg:
        sw = sum(sample_dim_w[key]) or 1.0
        sg = sum(sample_dim_agg[key])
        sample_dim_final[key] = round(sg / sw, 4) if sw else 0.0

    # ── Phase 3: average across samples within each dim → SLA_act,d ──
    samples = sorted({s for (s, _d) in sample_dim_final})
    actual_sla_by_dim: dict[str, dict[str, Any]] = {}
    score_dist = {"high": 0, "medium": 0, "low": 0}
    for dim in ALL_DIMS:
        dim_scores = [v for (s, d), v in sample_dim_final.items() if d == dim]
        if dim_scores:
            mean_score = sum(dim_scores) / len(dim_scores)
        else:
            mean_score = 0.0
        sla_d = round(mean_score * 100, 2)  # ×100 → percentage
        # Score distribution bucketing (per-sample mean)
        for v in dim_scores:
            if v >= 0.67:
                score_dist["high"] += 1
            elif v >= 0.33:
                score_dist["medium"] += 1
            else:
                score_dist["low"] += 1
        actual_sla_by_dim[dim] = {
            "sla_act_d": sla_d,
            "sample_count": len(dim_scores),
            "mean_grade": round(mean_score, 4),
        }

    # ── Phase 4: SLA_act = Σ_d w_d · SLA_act,d ──
    actual_sla = 0.0
    for dim in ALL_DIMS:
        w = w_d.get(dim, 0.0)
        sla_d = actual_sla_by_dim[dim]["sla_act_d"]
        actual_sla += w * sla_d
    actual_sla = round(min(100.0, max(0.0, actual_sla)), 2)

    # ── Per-task breakdown (optional) ──
    # Aggregate directly by (task_id, dim) from rubric items, independent of
    # the sample-level aggregation above — a task's dim score is the weighted
    # mean of its own items across all samples.
    per_task: list[dict[str, Any]] = []
    if atomic_tasks:
        task_ids = {t.get("task_id") for t in atomic_tasks if t.get("task_id")}
        for tid in sorted(task_ids):
            task_dim_agg: dict[str, list[float]] = {d: [] for d in ALL_DIMS}
            task_dim_w: dict[str, list[float]] = {d: [] for d in ALL_DIMS}
            for item in rubric_scores:
                if item.get("task_id") != tid:
                    continue
                dim = item.get("dim", "")
                if dim not in ALL_DIMS:
                    continue
                grade = _resolve_grade(item.get("grade"))
                weight = _num(item.get("weight")) or 1.0
                if bool(item.get("reverse_normalize", False)):
                    grade = 1.0 - grade
                task_dim_agg[dim].append(grade * weight)
                task_dim_w[dim].append(weight)
            task_dim_sla: dict[str, float] = {}
            for dim in ALL_DIMS:
                sw = sum(task_dim_w[dim]) or 1.0
                sg = sum(task_dim_agg[dim])
                if not task_dim_agg[dim]:
                    task_dim_sla[dim] = None
                else:
                    task_dim_sla[dim] = round((sg / sw) * 100, 2)
            per_task.append({"task_id": tid, "actual_sla_by_dim": task_dim_sla})

    return {
        "actual_sla": actual_sla,
        "actual_sla_by_dim": actual_sla_by_dim,
        "score_distribution": score_dist,
        "per_task": per_task,
        "sample_count": len(samples),
        "missing": [],
        "formula": "SLA_act = Σ_d w_d · SLA_act,d",
    }


# ═══════════════════════════════════════════════════════════════════════
# Error-rate & audit-completeness fields (§3.4.4/§3.5.2)
# ═══════════════════════════════════════════════════════════════════════


def compute_error_rates(
    *,
    samples: list[dict[str, Any]],
    risk_level: Optional[str] = None,
) -> dict[str, Any]:
    """Compute fatal/general error rates + audit completeness (§3.4.4/§3.5.2).

    Each sample in *samples*:
        {
          "sample_id": str,
          "fatal_count": int (default 0),
          "general_count": int (default 0),
          "audit_fields_complete": dict[str, bool] | int,
              (field_id → bool, or count of complete fields)
        }

    Returns:
        ``{fatal_error_rate, general_error_rate, audit_completeness,
        critical_field_completeness, fatal_violation, general_violation,
        audit_violation, missing}``

    Hard-constraint thresholds (from §3.5.2 式(5)):
      * fatal_error_rate == 0  (any fatal → nogo)
      * general_error_rate ≤ e_crit_max(R)
      * audit_completeness ≥ A_audit_min(R)
    """
    if not samples:
        return {
            "fatal_error_rate": 0.0,
            "general_error_rate": 0.0,
            "audit_completeness": 0.0,
            "critical_field_completeness": 0.0,
            "fatal_violation": False,
            "general_violation": False,
            "audit_violation": False,
            "missing": ["samples"],
        }

    total = len(samples)
    total_fatal = sum(int(s.get("fatal_count", 0) or 0) for s in samples)
    total_general = sum(int(s.get("general_count", 0) or 0) for s in samples)

    fatal_rate = round(total_fatal / total, 4) if total else 0.0
    general_rate = round(total_general / total, 4) if total else 0.0

    # Audit completeness — aggregate across samples
    audit_completeness, critical_completeness = _compute_audit_completeness(samples)

    # Threshold checks
    e_crit_max = E_CRIT_MAX_BY_RISK.get(risk_level or "") if risk_level else None
    a_audit_min = A_AUDIT_MIN_BY_RISK.get(risk_level or "") if risk_level else None

    fatal_violation = total_fatal > 0
    general_violation = (
        e_crit_max is not None and general_rate > e_crit_max
    )
    audit_violation = (
        a_audit_min is not None and audit_completeness < a_audit_min
    )

    return {
        "fatal_error_rate": fatal_rate,
        "general_error_rate": general_rate,
        "audit_completeness": round(audit_completeness, 4),
        "critical_field_completeness": round(critical_completeness, 4),
        "fatal_violation": fatal_violation,
        "general_violation": general_violation,
        "audit_violation": audit_violation,
        "e_crit_max": e_crit_max,
        "a_audit_min": a_audit_min,
        "missing": [],
    }


def _compute_audit_completeness(
    samples: list[dict[str, Any]],
) -> tuple[float, float]:
    """Compute overall + critical-field audit completeness.

    Returns (overall_completeness, critical_completeness) as fractions [0, 1].
    Critical fields are defined in CRITICAL_AUDIT_FIELDS (§3.2.4).
    """
    critical_ids = {f.field_id for f in CRITICAL_AUDIT_FIELDS}

    total_required = 0
    total_filled = 0
    crit_required = 0
    crit_filled = 0

    for s in samples:
        fields = s.get("audit_fields_complete")
        if isinstance(fields, dict):
            for field_id, filled in fields.items():
                is_filled = bool(filled)
                total_required += 1
                if is_filled:
                    total_filled += 1
                if field_id in critical_ids:
                    crit_required += 1
                    if is_filled:
                        crit_filled += 1
        elif isinstance(fields, (int, float)):
            # Scalar: count of complete fields — assume 8 total (default scenario)
            n = int(fields)
            total_required += 8
            total_filled += n
            crit_required += len(critical_ids)
            crit_filled += min(n, len(critical_ids))

    overall = (total_filled / total_required) if total_required else 0.0
    critical = (crit_filled / crit_required) if crit_required else 0.0
    return overall, critical


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _resolve_grade(grade: Any) -> float:
    """Resolve a rubric grade to its float value in [0, 1].

    Accepts the 4-tier scale ("0"/"0.33"/"0.67"/"1.0") or a float.
    Unknown strings default to 0.
    """
    if grade is None:
        return DEFAULT_GRADE
    if isinstance(grade, (int, float)) and not isinstance(grade, bool):
        g = float(grade)
        return max(0.0, min(1.0, g))
    s = str(grade).strip()
    if s in GRADE_SCALE:
        return GRADE_SCALE[s]
    try:
        g = float(s)
        return max(0.0, min(1.0, g))
    except ValueError:
        return DEFAULT_GRADE


def _num(value: Any) -> Optional[float]:
    """Extract a float from a value, rejecting bool/None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
