"""式(2) Net value + per-actor profitability + reciprocity check.

Thesis §3.3.3:

    式(2)  V_net = B_gross − C_ai − T_tax

    Per-actor: V_net,i = V_benefit,i − C_i  for i ∈ {科技,业务,风险/合规,运营}
               Constraint: ∀i, V_net,i ≥ 0  (anti "aggregated-ROI masking")

    Reciprocity (e3-value 互惠原则): every actor's value ports must be
    fully exchanged or not exchanged — no dangling ports.

Pure module — no FastAPI, repository, or LLM imports.
"""

from __future__ import annotations

from typing import Any, Optional

# ── Four-actor identifiers (§3.3.1, risk/compliance merged) ───────────

ACTORS: tuple[str, ...] = ("科技", "业务", "风险/合规", "运营")


# ═══════════════════════════════════════════════════════════════════════
# 式(2) ecosystem-level net value
# ═══════════════════════════════════════════════════════════════════════


def compute_net_value(
    *,
    gross_benefit: Optional[float] = None,
    ai_operating_cost: Optional[float] = None,
    implementation_tax_total: Optional[float] = None,
    gross_benefit_components: Optional[dict[str, float]] = None,
    ai_cost_components: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Compute 式(2) V_net = B_gross − C_ai − T_tax.

    Accepts either scalar values or sub-component dicts:
      * ``gross_benefit_components``: {B_labor, B_risk, B_incr}
      * ``ai_cost_components``: {C_token, C_infra, C_data, C_ops}

    If both scalar and components are given, the scalar takes precedence
    (it is assumed already aggregated). Returns ``net_value=None`` and
    ``break_even_met=False`` when inputs are missing — callers should
    treat None as "value model not yet populated" (Stage 2 unseeded run).

    Returns a dict with:
      * ``net_value`` — float | None
      * ``break_even_met`` — bool (net_value ≥ 0 when computable)
      * ``gross_benefit``, ``ai_operating_cost``, ``implementation_tax_total``
      * ``components`` — echo of sub-components if provided
      * ``formula`` — human-readable formula string
    """
    # Resolve gross_benefit
    b_gross = gross_benefit
    if b_gross is None and gross_benefit_components:
        b_gross = sum(float(v) for v in gross_benefit_components.values() if v is not None)

    # Resolve ai_operating_cost
    c_ai = ai_operating_cost
    if c_ai is None and ai_cost_components:
        c_ai = sum(float(v) for v in ai_cost_components.values() if v is not None)

    t_tax = implementation_tax_total

    net_value: Optional[float]
    if b_gross is None or c_ai is None or t_tax is None:
        net_value = None
        break_even = False
    else:
        net_value = round(float(b_gross) - float(c_ai) - float(t_tax), 4)
        break_even = net_value >= 0

    return {
        "net_value": net_value,
        "break_even_met": break_even,
        "gross_benefit": b_gross,
        "ai_operating_cost": c_ai,
        "implementation_tax_total": t_tax,
        "components": {
            "gross_benefit": gross_benefit_components or {},
            "ai_operating_cost": ai_cost_components or {},
        },
        "formula": "net_value = gross_benefit - ai_operating_cost - implementation_tax_total",
    }


# ═══════════════════════════════════════════════════════════════════════
# Per-actor net value (profitability-per-actor, §3.3.3)
# ═══════════════════════════════════════════════════════════════════════


def compute_actor_net_value(
    actor_benefits: dict[str, float],
    actor_costs: dict[str, float],
) -> dict[str, Any]:
    """Compute per-actor V_net,i = benefit_i − cost_i.

    Checks the profitability constraint ∀i, V_net,i ≥ 0 and flags
    "aggregated-ROI masking" when ecosystem-level net_value ≥ 0 but some
    actor has V_net,i < 0.

    Returns a dict with:
      * ``actor_net_value`` — list of per-actor dicts
      * ``aggregation_masking`` — bool (True if any actor net < 0)
      * ``masking_actors`` — list of actor names with net < 0
      * ``all_non_negative`` — bool (all actors V_net,i ≥ 0)
    """
    rows: list[dict[str, Any]] = []
    masking_actors: list[str] = []
    all_non_negative = True

    for actor in ACTORS:
        benefit = float(actor_benefits.get(actor, 0.0) or 0.0)
        cost = float(actor_costs.get(actor, 0.0) or 0.0)
        net = round(benefit - cost, 4)
        ge_zero = net >= 0
        if not ge_zero:
            all_non_negative = False
            masking_actors.append(actor)
        rows.append({
            "actor": actor,
            "benefit_i": benefit,
            "cost_i": cost,
            "net_value_i": net,
            "ge_zero": ge_zero,
        })

    return {
        "actor_net_value": rows,
        "aggregation_masking": len(masking_actors) > 0,
        "masking_actors": masking_actors,
        "all_non_negative": all_non_negative,
    }


def build_actor_net_value_table(
    actor_benefits: dict[str, float],
    actor_costs: dict[str, float],
) -> dict[str, Any]:
    """Build the formatted 逐actor净效用核算表.

    Output shape (§3.3.3): ``|主体|benefit_i|cost_i|net_value_i|是否≥0|``.
    """
    result = compute_actor_net_value(actor_benefits, actor_costs)
    table_rows = []
    for row in result["actor_net_value"]:
        table_rows.append({
            "主体": row["actor"],
            "benefit_i": row["benefit_i"],
            "cost_i": row["cost_i"],
            "net_value_i": row["net_value_i"],
            "是否≥0": row["ge_zero"],
        })
    return {
        "table": table_rows,
        "aggregation_masking": result["aggregation_masking"],
        "masking_actors": result["masking_actors"],
        "all_non_negative": result["all_non_negative"],
        "columns": ["主体", "benefit_i", "cost_i", "net_value_i", "是否≥0"],
    }


# ═══════════════════════════════════════════════════════════════════════
# Reciprocity check (e3-value 互惠原则, §3.3.3)
# ═══════════════════════════════════════════════════════════════════════


def check_reciprocity(
    value_ports: list[dict[str, Any]],
    value_exchanges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check e3-value reciprocity: no dangling ports.

    Each actor's in-ports must have a corresponding source exchange,
    and out-ports a corresponding destination exchange.  A "dangling
    port" (in-port with no source exchange, or out-port with no
    destination exchange) is a reciprocity violation.

    Args:
        value_ports: list of ``{port_id, actor, direction(in|out), ...}``
        value_exchanges: list of ``{exchange_id, from_actor, to_actor, ...}``

    Returns:
        ``{reciprocity_violations, violation_count, passed}``
    """
    # Build a set of (actor, direction) pairs that have at least one
    # exchange touching them on the correct side.
    in_covered: set[tuple[str, str]] = set()   # (actor, port_id)
    out_covered: set[tuple[str, str]] = set()

    for ex in value_exchanges:
        from_actor = ex.get("from_actor")
        to_actor = ex.get("to_actor")
        if from_actor:
            out_covered.add((from_actor, ex.get("exchange_id", "")))
        if to_actor:
            in_covered.add((to_actor, ex.get("exchange_id", "")))

    violations: list[dict[str, Any]] = []
    for port in value_ports:
        actor = port.get("actor")
        direction = port.get("direction")
        port_id = port.get("port_id", "")
        if direction == "in":
            covered = any(
                ex.get("to_actor") == actor
                for ex in value_exchanges
            )
            if not covered:
                violations.append({
                    "actor": actor,
                    "port_id": port_id,
                    "port_type": "in",
                    "reason": "in-port has no source exchange (dangling)",
                })
        elif direction == "out":
            covered = any(
                ex.get("from_actor") == actor
                for ex in value_exchanges
            )
            if not covered:
                violations.append({
                    "actor": actor,
                    "port_id": port_id,
                    "port_type": "out",
                    "reason": "out-port has no destination exchange (dangling)",
                })

    return {
        "reciprocity_violations": violations,
        "violation_count": len(violations),
        "passed": len(violations) == 0,
    }


# ═══════════════════════════════════════════════════════════════════════
# 式(§3.3.4) Sensitivity analysis with conclusion_flip
# ═══════════════════════════════════════════════════════════════════════


def compute_sensitivity(
    *,
    params: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute sensitivity analysis with conclusion_flip (§3.3.4).

    Each param in *params*:
        {
          "param": str,           # parameter name
          "baseline": float,      # baseline value
          "low": float,           # low perturbation value
          "high": float,          # high perturbation value
          "low_net": float,       # net_value at low (caller computes)
          "high_net": float,      # net_value at high (caller computes)
          "regulatory_floor": bool, # whether param has regulatory floor
        }

    The caller is responsible for computing ``low_net`` and ``high_net``
    by re-running ``compute_net_value`` with each perturbed parameter.
    This function only evaluates the conclusion_flip criterion.

    Returns:
      * ``sensitivity_table`` — list of param result dicts
      * ``stability`` — ``"confirmed"`` / ``"unstable"``
      * ``flip_triggered`` — bool (True if any param causes flip)
      * ``flip_params`` — list of param names that triggered flip
    """
    table: list[dict[str, Any]] = []
    flip_params: list[str] = []

    for p in params:
        name = p.get("param", "")
        baseline = _num(p.get("baseline"))
        low = _num(p.get("low"))
        high = _num(p.get("high"))
        low_net = _num(p.get("low_net"))
        high_net = _num(p.get("high_net"))

        if low_net is None or high_net is None:
            table.append({
                "param": name,
                "baseline": baseline,
                "low": low,
                "high": high,
                "low_net": low_net,
                "high_net": high_net,
                "conclusion_flip": None,
                "regulatory_floor": p.get("regulatory_floor", False),
            })
            continue

        # conclusion_flip: sign change across [low, high]
        flip = (low_net <= 0 <= high_net) or (high_net <= 0 <= low_net)
        if flip:
            flip_params.append(name)

        table.append({
            "param": name,
            "baseline": baseline,
            "low": low,
            "high": high,
            "low_net": round(low_net, 4),
            "high_net": round(high_net, 4),
            "conclusion_flip": flip,
            "regulatory_floor": p.get("regulatory_floor", False),
        })

    flip_triggered = len(flip_params) > 0
    if flip_triggered:
        stability = "unstable"
    else:
        stability = "confirmed"

    return {
        "sensitivity_table": table,
        "stability": stability,
        "flip_triggered": flip_triggered,
        "flip_params": flip_params,
    }


def _num(value: Any) -> Optional[float]:
    """Extract a float from a value, rejecting bool/None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
