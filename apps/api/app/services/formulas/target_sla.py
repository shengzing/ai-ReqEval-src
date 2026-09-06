"""式(3)(3a) Target SLA back-deduction — risk floor + value-driven uplift.

Thesis §3.3.3 式(3)(3a):

    SLA_tgt,d = SLA_floor,d(R) + α_d · r,    r = (V_net − V_min) / (V_max − V_min)

    SLA_tgt = Σ_d w_d · SLA_tgt,d,   d ∈ {qual, eff, gov}

Where:
  * ``SLA_floor,d(R)`` — risk-graded per-dimension floor
  * ``r`` — net-value gain ratio, clamped to [0, 1]:
        r = min(1, max(0, (V_net − V_min) / (V_max − V_min)))
  * ``α_d`` — per-dimension allocation coefficient (Delphi prior)
  * ``w_d`` — three-dimension weights (L3 governance ≥ 0.3)

Key invariants (§3.3.3):
  * ``V_net ≤ V_min`` → ``r = 0`` → SLA_tgt degenerates to risk floor;
    at this point 式(5) hard constraint also fails.
  * Target SLA is back-deduced **once** from frozen V_net; it is never
    iteratively re-adjusted from Actual SLA ("先固定净价值、单次反推").
  * SLA_tgt is normalised to [0, 100].

Pure module — no FastAPI, repository, or LLM imports.
"""

from __future__ import annotations

from typing import Any, Optional

from .thresholds import (
    ALPHA_D_DEFAULT,
    SLA_FLOOR_BY_DIM_BY_RISK,
    SLA_FLOOR_BY_RISK,
    V_MAX_DEFAULT,
    V_MIN_BY_RISK,
    W_D_DEFAULT,
)


# ── Dimension identifiers ──────────────────────────────────────────────

DIM_QUAL = "qual"
DIM_EFF = "eff"
DIM_GOV = "gov"
ALL_DIMS: tuple[str, ...] = (DIM_QUAL, DIM_EFF, DIM_GOV)


# ═══════════════════════════════════════════════════════════════════════
# 式(3) gain ratio r
# ═══════════════════════════════════════════════════════════════════════


def compute_gain_ratio(
    *,
    net_value: Optional[float],
    v_min: Optional[float] = None,
    v_max: Optional[float] = None,
    risk_level: Optional[str] = None,
) -> dict[str, Any]:
    """Compute r = (V_net − V_min) / (V_max − V_min), clamped to [0, 1].

    If *v_min* or *v_max* is None, they are resolved from *risk_level*
    via ``V_MIN_BY_RISK`` / ``V_MAX_DEFAULT``.

    Returns ``{r, v_min, v_max, clamped, degenerate}`` where:
      * ``r`` — float in [0, 1]
      * ``clamped`` — True if r was truncated by min/max
      * ``degenerate`` — True if V_net ≤ V_min (r=0, SLA degenerates to floor)
    """
    # Resolve v_min / v_max
    if v_min is None and risk_level is not None:
        v_min = V_MIN_BY_RISK.get(risk_level)
    if v_max is None:
        v_max = V_MAX_DEFAULT

    if net_value is None or v_min is None or v_max is None:
        return {
            "r": 0.0,
            "v_min": v_min,
            "v_max": v_max,
            "clamped": True,
            "degenerate": True,
        }

    span = v_max - v_min
    if span <= 0:
        # Avoid division by zero — degenerate to floor
        return {
            "r": 0.0,
            "v_min": v_min,
            "v_max": v_max,
            "clamped": True,
            "degenerate": net_value <= v_min,
        }

    raw_r = (net_value - v_min) / span
    clamped = False
    if raw_r < 0:
        raw_r = 0.0
        clamped = True
    elif raw_r > 1:
        raw_r = 1.0
        clamped = True

    return {
        "r": round(raw_r, 4),
        "v_min": v_min,
        "v_max": v_max,
        "clamped": clamped,
        "degenerate": net_value <= v_min,
    }


# ═══════════════════════════════════════════════════════════════════════
# 式(3) per-dimension target SLA
# ═══════════════════════════════════════════════════════════════════════


def compute_target_sla_by_dim(
    *,
    risk_level: str,
    net_value: Optional[float],
    alpha_d: Optional[dict[str, float]] = None,
    sla_floor_d: Optional[dict[str, float]] = None,
    v_min: Optional[float] = None,
    v_max: Optional[float] = None,
) -> dict[str, Any]:
    """Compute 式(3) SLA_tgt,d = SLA_floor,d(R) + α_d · r per dimension.

    Returns a dict with:
      * ``target_sla_by_dim`` — {dim: {sla_floor, alpha, r, sla_tgt, capped}}
      * ``r`` — gain ratio (shared across dims)
      * ``risk_level`` — echo
    """
    # Resolve defaults
    if alpha_d is None:
        alpha_d = ALPHA_D_DEFAULT
    if sla_floor_d is None:
        sla_floor_d = SLA_FLOOR_BY_DIM_BY_RISK.get(risk_level, {})

    # Compute gain ratio
    r_result = compute_gain_ratio(
        net_value=net_value, v_min=v_min, v_max=v_max, risk_level=risk_level
    )
    r = r_result["r"]

    target_by_dim: dict[str, dict[str, Any]] = {}
    for dim in ALL_DIMS:
        floor = sla_floor_d.get(dim, 0.0)
        alpha = alpha_d.get(dim, 0.0)
        sla_tgt = floor + alpha * r
        capped = sla_tgt > 100.0
        if capped:
            sla_tgt = 100.0
        target_by_dim[dim] = {
            "sla_floor": floor,
            "alpha": alpha,
            "r": r,
            "sla_tgt": round(sla_tgt, 4),
            "capped": capped,
        }

    return {
        "target_sla_by_dim": target_by_dim,
        "r": r,
        "risk_level": risk_level,
        "gain_ratio": r_result,
    }


# ═══════════════════════════════════════════════════════════════════════
# 式(3a) aggregated target SLA
# ═══════════════════════════════════════════════════════════════════════


def compute_target_sla(
    *,
    risk_level: str,
    net_value: Optional[float],
    alpha_d: Optional[dict[str, float]] = None,
    sla_floor_d: Optional[dict[str, float]] = None,
    w_d: Optional[dict[str, float]] = None,
    v_min: Optional[float] = None,
    v_max: Optional[float] = None,
) -> dict[str, Any]:
    """Compute 式(3a) SLA_tgt = Σ_d w_d · SLA_tgt,d.

    Returns a dict with:
      * ``target_sla`` — float (normalised to [0, 100])
      * ``target_sla_by_dim`` — per-dimension breakdown
      * ``r`` — gain ratio
      * ``risk_level`` — echo
      * ``stability`` — ``"confirmed"`` when r well within [0,1] and
        not degenerate; ``"needs_confirmation"`` when clamped or near
        boundary
    """
    # Resolve w_d default
    if w_d is None:
        w_d = W_D_DEFAULT

    dim_result = compute_target_sla_by_dim(
        risk_level=risk_level,
        net_value=net_value,
        alpha_d=alpha_d,
        sla_floor_d=sla_floor_d,
        v_min=v_min,
        v_max=v_max,
    )

    target_sla = 0.0
    for dim in ALL_DIMS:
        w = w_d.get(dim, 0.0)
        sla_d = dim_result["target_sla_by_dim"][dim]["sla_tgt"]
        target_sla += w * sla_d

    target_sla = round(min(100.0, max(0.0, target_sla)), 4)

    # Stability annotation (§3.3.3 三档)
    r_info = dim_result["gain_ratio"]
    if r_info["degenerate"] or r_info["clamped"]:
        stability = "needs_confirmation"
    else:
        stability = "confirmed"

    return {
        "target_sla": target_sla,
        "target_sla_by_dim": dim_result["target_sla_by_dim"],
        "r": dim_result["r"],
        "risk_level": risk_level,
        "stability": stability,
        "v_min": r_info["v_min"],
        "v_max": r_info["v_max"],
        "formula": "SLA_tgt = Σ_d w_d · (SLA_floor,d(R) + α_d · r)",
    }


def resolve_floor_comprehensive(risk_level: str) -> Optional[float]:
    """Return the comprehensive SLA floor for a risk level.

    This is the single-number floor used by the legacy alignment path;
    the per-dimension floors are in ``SLA_FLOOR_BY_DIM_BY_RISK``.
    """
    return SLA_FLOOR_BY_RISK.get(risk_level)
