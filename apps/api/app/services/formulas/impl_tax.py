"""式(1) Implementation tax — seven-category itemised calculation.

Thesis §3.3.2 式(1):

    T_tax = Σ_k T_tax,k,  k ∈ {review, rework, audit, monitor, coord, integ, train}

Each category has its own pricing formula:

  * review  : T = N_review × t_review × c_hour × ρ_review(H)
  * rework  : T = N_task × p_rework × c_rework
  * audit   : T = N_audit × A_audit × c_audit
  * monitor : T = N_monitor × c_monitor
  * coord   : T = N_coord × c_coord
  * integ   : T = N_integ × c_integ
  * train   : T = N_train × c_train

where ρ_review(H) cascades with HITL intensity:
  none=0, standard=0.5, strict=1.0, mandatory=1.0

Per-actor attribution (§3.3.2 七项→value activity→归属 actor):
  review → 业务+风险/合规   (复核动作)
  rework → 业务+风险/合规   (修正动作)
  audit  → 风险/合规        (留痕动作)
  monitor→ 科技              (模型监控)
  coord  → 运营              (跨部门协同)
  integ  → 科技              (系统集成)
  train  → 风险/合规+运营    (培训)

Repetition-prevention rule (§3.3.2 重复计量防范):
  review = 复核动作(含签字、意见填写)
  rework = 复核后修正动作(重做或补录)
  audit  = 留痕记录动作(日志填写、归档)
  Three actions do not overlap; the same human work is not double-priced.

Pure module — no FastAPI, repository, or LLM imports.
"""

from __future__ import annotations

from typing import Any, Optional

from .thresholds import RHO_H_BY_HITL

# ── Seven category identifiers (§3.3.2) ───────────────────────────────

TAX_REVIEW = "review"
TAX_REWORK = "rework"
TAX_AUDIT = "audit"
TAX_MONITOR = "monitor"
TAX_COORD = "coord"
TAX_INTEG = "integ"
TAX_TRAIN = "train"

SEVEN_CATEGORIES: tuple[str, ...] = (
    TAX_REVIEW, TAX_REWORK, TAX_AUDIT,
    TAX_MONITOR, TAX_COORD, TAX_INTEG, TAX_TRAIN,
)

# ── Actor attribution (§3.3.2 七项→归属 actor) ────────────────────────

ACTOR_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    TAX_REVIEW: ("业务", "风险/合规"),
    TAX_REWORK: ("业务", "风险/合规"),
    TAX_AUDIT: ("风险/合规",),
    TAX_MONITOR: ("科技",),
    TAX_COORD: ("运营",),
    TAX_INTEG: ("科技",),
    TAX_TRAIN: ("风险/合规", "运营"),
}


# ═══════════════════════════════════════════════════════════════════════
# 式(1) implementation tax total
# ═══════════════════════════════════════════════════════════════════════


def compute_implementation_tax(
    *,
    items: list[dict[str, Any]],
    hitl_level: Optional[str] = None,
) -> dict[str, Any]:
    """Compute 式(1) T_tax = Σ_k T_tax,k.

    Each item in *items* represents one implementation-tax line entry:
        {
          "category": "review" | "rework" | "audit" | "monitor" | "coord" | "integ" | "train",
          "item_id": str (optional),
          "unit_cost": float,
          "quantity": float,
          "rho_H": float (optional; for review, auto-resolved from hitl_level if absent),
          "actor": str (optional; auto-resolved from ACTOR_BY_CATEGORY if absent),
          "source": str (optional; parameter provenance: 历史/德尔菲/审计清单/工程估工),
        }

    The generic formula per item is ``unit_cost × quantity``.  For the
    ``review`` category, the result is multiplied by ``rho_H`` (the HITL
    review ratio) — supplied either in the item dict or resolved from
    *hitl_level* via the ``RHO_H_BY_HITL`` cascade.

    Args:
        items: list of implementation-tax line items (七类).
        hitl_level: HITL intensity (``none``/``standard``/``strict``/
            ``mandatory``); used to auto-resolve ``rho_H`` for review
            items that do not specify it.

    Returns:
        Dict with:
          * ``implementation_tax_total`` — float
          * ``tax_by_category`` — {category: float}
          * ``tax_by_actor`` — {actor: float}
          * ``items`` — echo of input items with computed ``line_total``
          * ``missing_parameters`` — list of item_ids missing unit_cost/quantity
          * ``formula`` — human-readable formula string
    """
    tax_by_category: dict[str, float] = {cat: 0.0 for cat in SEVEN_CATEGORIES}
    tax_by_actor: dict[str, float] = {}
    missing: list[str] = []
    computed_items: list[dict[str, Any]] = []

    # Default rho_H from hitl_level (for review category fallback)
    default_rho = RHO_H_BY_HITL.get(hitl_level or "", 0.0) if hitl_level else None

    for item in items:
        category = item.get("category", "")
        item_id = item.get("item_id", category or "unknown")
        unit_cost = _num(item.get("unit_cost"))
        quantity = _num(item.get("quantity"))

        if unit_cost is None:
            missing.append(f"implementation_tax_items.{item_id}.unit_cost")
        if quantity is None:
            missing.append(f"implementation_tax_items.{item_id}.quantity")

        if unit_cost is None or quantity is None:
            computed_items.append({**item, "line_total": None})
            continue

        # Review category: apply rho_H
        rho: Optional[float] = None
        if category == TAX_REVIEW:
            rho = _num(item.get("rho_H"))
            if rho is None and default_rho is not None:
                rho = default_rho
            if rho is None:
                # No rho_H and no hitl_level — cannot compute review tax
                missing.append(f"implementation_tax_items.{item_id}.rho_H")
                computed_items.append({**item, "line_total": None})
                continue

        line_total = unit_cost * quantity
        if rho is not None:
            line_total *= rho
        line_total = round(line_total, 4)

        # Aggregate by category
        if category in tax_by_category:
            tax_by_category[category] = round(
                tax_by_category[category] + line_total, 4
            )
        else:
            tax_by_category[category] = line_total

        # Aggregate by actor
        actors = item.get("actor")
        if actors is None:
            actors_list = ACTOR_BY_CATEGORY.get(category, ())
        elif isinstance(actors, str):
            actors_list = (actors,)
        else:
            actors_list = tuple(actors)

        if actors_list:
            # Split line_total equally among attributed actors
            share = round(line_total / len(actors_list), 4)
            for actor in actors_list:
                tax_by_actor[actor] = round(
                    tax_by_actor.get(actor, 0.0) + share, 4
                )

        computed_items.append({**item, "line_total": line_total})

    total = round(sum(tax_by_category.values()), 4)

    return {
        "implementation_tax_total": total,
        "tax_by_category": tax_by_category,
        "tax_by_actor": tax_by_actor,
        "items": computed_items,
        "missing_parameters": sorted(set(missing)),
        "formula": "T_tax = Σ_k (unit_cost_k × quantity_k [× rho_H_k])",
    }


def _num(value: Any) -> Optional[float]:
    """Extract a float from a value, rejecting bool/None/str."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


# ── Category pricing formula descriptions (for traceability) ──────────

CATEGORY_FORMULAS: dict[str, str] = {
    TAX_REVIEW: "T_review = N_review × t_review × c_hour × ρ_review(H)",
    TAX_REWORK: "T_rework = N_task × p_rework × c_rework",
    TAX_AUDIT: "T_audit = N_audit × A_audit × c_audit",
    TAX_MONITOR: "T_monitor = N_monitor × c_monitor",
    TAX_COORD: "T_coord = N_coord × c_coord",
    TAX_INTEG: "T_integ = N_integ × c_integ",
    TAX_TRAIN: "T_train = N_train × c_train",
}
