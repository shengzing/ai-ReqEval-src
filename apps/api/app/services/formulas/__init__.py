"""Formula tool package — pure-function implementations of thesis formulas (1)-(7).

Each module corresponds to a numbered formula in the thesis (§3.3-§3.5):

- ``impl_tax``        → 式(1)  implementation tax total (seven categories)
- ``net_value``        → 式(2)  net value + per-actor + reciprocity check
- ``target_sla``       → 式(3)(3a) target SLA derivation
- ``actual_sla``       → 式(4)  actual SLA aggregation (three-dim weighted)
- ``hard_constraint``  → 式(5)  G_hard seven-term conjunction
- ``decision``         → 式(6)  go/hold/nogo three-state decision
- ``retro_gap``        → 式(7)  retrospective gap

All modules are pure functions with no FastAPI, repository, or LLM
dependencies — they are the single source of truth for formula
calculations, shared by the tool layer, contract layer, and alignment
service.  Parameters marked "initial reference value, pending M2-M4
empirical calibration" must not be presented as confirmed case results.
"""

from __future__ import annotations

from .thresholds import (
    A_AUDIT_MIN_BY_RISK,
    ALPHA_D_DEFAULT,
    CRITICAL_AUDIT_FIELDS,
    E_CRIT_MAX_BY_RISK,
    RHO_H_BY_HITL,
    SLA_FLOOR_BY_DIM_BY_RISK,
    SLA_FLOOR_BY_RISK,
    V_MAX_DEFAULT,
    V_MIN_BY_RISK,
    W_D_DEFAULT,
    AuditField,
)
from .hard_constraint import compute_g_hard
from .net_value import (
    build_actor_net_value_table,
    check_reciprocity,
    compute_actor_net_value,
    compute_net_value,
    compute_sensitivity,
)
from .decision import (
    build_remediation_items,
    compute_decision,
    grade_gap,
    validate_exit_alternative,
)
from .impl_tax import compute_implementation_tax
from .target_sla import (
    compute_gain_ratio,
    compute_target_sla,
    compute_target_sla_by_dim,
    resolve_floor_comprehensive,
)
from .actual_sla import (
    compute_actual_sla,
    compute_error_rates,
)
from .retro_gap import compute_retro_gap

__all__ = [
    # thresholds
    "A_AUDIT_MIN_BY_RISK",
    "ALPHA_D_DEFAULT",
    "CRITICAL_AUDIT_FIELDS",
    "E_CRIT_MAX_BY_RISK",
    "RHO_H_BY_HITL",
    "SLA_FLOOR_BY_DIM_BY_RISK",
    "SLA_FLOOR_BY_RISK",
    "V_MAX_DEFAULT",
    "V_MIN_BY_RISK",
    "W_D_DEFAULT",
    "AuditField",
    # formula (5)
    "compute_g_hard",
    # formula (2)
    "compute_net_value",
    "compute_actor_net_value",
    "check_reciprocity",
    "build_actor_net_value_table",
    "compute_sensitivity",
    # formula (6)
    "compute_decision",
    "build_remediation_items",
    "grade_gap",
    "validate_exit_alternative",
    # formula (1)
    "compute_implementation_tax",
    # formula (3)(3a)
    "compute_gain_ratio",
    "compute_target_sla",
    "compute_target_sla_by_dim",
    "resolve_floor_comprehensive",
    # formula (4)
    "compute_actual_sla",
    "compute_error_rates",
    # formula (7)
    "compute_retro_gap",
]
