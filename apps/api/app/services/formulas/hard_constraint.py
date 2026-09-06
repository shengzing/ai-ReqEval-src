"""式(5) Hard-constraint conjunction — G_hard seven-term check.

Thesis §3.5.2 式(5):

    G_hard = (P=0)                              # 禁入条件未命中
           AND (e_fatal = 0)                    # 致命错误率为零
           AND (e_general ≤ e_crit_max(R))      # 一般错误率不超阈值
           AND (A_audit ≥ A_audit_min(R))       # 总体审计完整率达标
           AND (U_hitl = 1)                     # HITL 应触发时已触发
           AND (S_sample = 1)                   # 样本已脱敏且来源明确
           AND (V_net ≥ V_min(R))               # 净价值不低于最低可接受值

All seven terms must hold simultaneously for ``G_hard = 1``; any single
failure sets ``G_hard = 0`` and is recorded in ``failed_terms``.

Pure module — no FastAPI, repository, or LLM imports.
"""

from __future__ import annotations

from typing import Any, Optional

from .thresholds import (
    A_AUDIT_MIN_BY_RISK,
    E_CRIT_MAX_BY_RISK,
    V_MIN_BY_RISK,
)

# ── Term identifiers (align with thesis 式(5) symbols) ─────────────────

TERM_PROHIBITED = "prohibited_hit"          # P
TERM_FATAL = "fatal_error_rate"             # e_fatal
TERM_GENERAL = "general_error_rate"          # e_general
TERM_AUDIT = "audit_completeness"            # A_audit
TERM_HITL = "hitl_triggered"                 # U_hitl
TERM_SAMPLE = "sample_compliant"             # S_sample
TERM_NET_VALUE = "net_value"                 # V_net


class HardConstraintInput:
    """Input bundle for 式(5). Each attribute maps to one conjunction term.

    All numeric fields default to ``None`` (treated as a failed term when
    the input is missing).  Callers should supply explicit values from
    Stage 1/2/3 outputs.
    """

    def __init__(
        self,
        *,
        risk_level: str,
        prohibited_hit: Optional[bool] = None,
        fatal_error_rate: Optional[float] = None,
        general_error_rate: Optional[float] = None,
        audit_completeness: Optional[float] = None,
        hitl_triggered: Optional[bool] = None,
        sample_compliant: Optional[bool] = None,
        net_value: Optional[float] = None,
    ) -> None:
        self.risk_level = risk_level
        self.prohibited_hit = prohibited_hit
        self.fatal_error_rate = fatal_error_rate
        self.general_error_rate = general_error_rate
        self.audit_completeness = audit_completeness
        self.hitl_triggered = hitl_triggered
        self.sample_compliant = sample_compliant
        self.net_value = net_value


def _term_prohibited(inp: HardConstraintInput) -> bool:
    """P=0 means no prohibited condition was hit."""
    return inp.prohibited_hit is False


def _term_fatal(inp: HardConstraintInput) -> bool:
    """e_fatal=0: zero fatal errors (independent hard veto)."""
    return inp.fatal_error_rate is not None and inp.fatal_error_rate == 0.0


def _term_general(inp: HardConstraintInput) -> bool:
    """e_general ≤ e_crit_max(R)."""
    ceiling = E_CRIT_MAX_BY_RISK.get(inp.risk_level)
    if ceiling is None or inp.general_error_rate is None:
        return False
    return inp.general_error_rate <= ceiling


def _term_audit(inp: HardConstraintInput) -> bool:
    """A_audit ≥ A_audit_min(R) (overall completeness floor).

    Note: critical-field completeness (=100%) is a separate field-level
    requirement checked elsewhere; this is the overall floor.
    """
    floor = A_AUDIT_MIN_BY_RISK.get(inp.risk_level)
    if floor is None or inp.audit_completeness is None:
        return False
    return inp.audit_completeness >= floor


def _term_hitl(inp: HardConstraintInput) -> bool:
    """U_hitl=1: HITL triggered at the required intensity.

    For L1 mapped to ``none`` the "should-trigger set" is empty, so
    U_hitl is always 1 (not a veto) — represented by ``True`` here.
    """
    return inp.hitl_triggered is True


def _term_sample(inp: HardConstraintInput) -> bool:
    """S_sample=1: sample desensitized and source clear."""
    return inp.sample_compliant is True


def _term_net_value(inp: HardConstraintInput) -> bool:
    """V_net ≥ V_min(R) (disaster floor, may be ≤ 0)."""
    floor = V_MIN_BY_RISK.get(inp.risk_level)
    if floor is None or inp.net_value is None:
        return False
    return inp.net_value >= floor


# Ordered term list — order matches thesis 式(5) symbols D1→D6.
_TERMS: list[tuple[str, str, Any]] = [
    (TERM_PROHIBITED, "禁入条件未命中 P=0", _term_prohibited),
    (TERM_FATAL, "致命错误率 e_fatal=0", _term_fatal),
    (TERM_GENERAL, "一般错误率 e_general≤e_crit_max(R)", _term_general),
    (TERM_AUDIT, "审计完整率 A_audit≥A_audit_min(R)", _term_audit),
    (TERM_HITL, "HITL 应触发时已触发 U_hitl=1", _term_hitl),
    (TERM_SAMPLE, "样本已脱敏且来源明确 S_sample=1", _term_sample),
    (TERM_NET_VALUE, "净价值不低于最低可接受值 V_net≥V_min(R)", _term_net_value),
]


def compute_g_hard(inp: HardConstraintInput) -> dict[str, Any]:
    """Evaluate 式(5) and return ``G_hard`` + per-term detail.

    Returns a dict with:
      * ``G_hard`` — bool (True only if all seven terms pass)
      * ``failed_terms`` — list of failed term dicts
        ``{term, description, value, threshold, passed}``
      * ``g_hard_components`` — per-term pass/fail map (all seven)
      * ``risk_level`` — echo
    """
    failed_terms: list[dict[str, Any]] = []
    components: dict[str, dict[str, Any]] = {}

    for term_id, description, check_fn in _TERMS:
        passed = check_fn(inp)
        components[term_id] = {
            "description": description,
            "passed": passed,
            "value": _extract_value(inp, term_id),
            "threshold": _extract_threshold(inp, term_id),
        }
        if not passed:
            failed_terms.append(components[term_id].copy())

    g_hard = len(failed_terms) == 0
    return {
        "G_hard": g_hard,
        "failed_terms": failed_terms,
        "g_hard_components": components,
        "risk_level": inp.risk_level,
    }


def _extract_value(inp: HardConstraintInput, term_id: str) -> Any:
    """Extract the input value for a term (for traceability)."""
    mapping = {
        TERM_PROHIBITED: inp.prohibited_hit,
        TERM_FATAL: inp.fatal_error_rate,
        TERM_GENERAL: inp.general_error_rate,
        TERM_AUDIT: inp.audit_completeness,
        TERM_HITL: inp.hitl_triggered,
        TERM_SAMPLE: inp.sample_compliant,
        TERM_NET_VALUE: inp.net_value,
    }
    return mapping.get(term_id)


def _extract_threshold(inp: HardConstraintInput, term_id: str) -> Any:
    """Extract the applicable threshold for a term (for traceability)."""
    if term_id == TERM_GENERAL:
        return E_CRIT_MAX_BY_RISK.get(inp.risk_level)
    if term_id == TERM_AUDIT:
        return A_AUDIT_MIN_BY_RISK.get(inp.risk_level)
    if term_id == TERM_NET_VALUE:
        return V_MIN_BY_RISK.get(inp.risk_level)
    # Boolean terms have no numeric threshold.
    return None
