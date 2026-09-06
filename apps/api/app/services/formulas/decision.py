"""式(6) Decision engine — go/hold/nogo three-state decision.

Thesis §3.5.2 式(6):

    IF G_hard == 0:
        verdict = nogo  (不予立项)
    ELIF delta_sla < 0 OR net_value < 0:
        verdict = hold  (暂缓立项, 附补齐项清单)
        IF net_value < 0 AND sensitivity_confirmed_negative:
            verdict = nogo  (降级路径)
    ELSE:
        verdict = go    (立项)

Where:
  * ``G_hard`` — from 式(5) (seven-term conjunction)
  * ``delta_sla`` — Actual SLA − Target SLA (pp); ≥0 means meets target
  * ``net_value`` — from 式(2); ≥0 means value admission passes
  * ``sensitivity_confirmed_negative`` — from §3.3.4 sensitivity analysis

The gap-grading (§3.4.4) attaches as conditional sub-states on ``hold``
without changing the three-state decision space.  ``nogo`` requires an
exit-AI alternative plan (§3.5.3).

Pure module — no FastAPI, repository, or LLM imports.
"""

from __future__ import annotations

from typing import Any, Optional

from .thresholds import (
    E_CRIT_MAX_BY_RISK,
    GAP_GRADE_THRESHOLDS,
)

# ── Verdict enum (thesis go/hold/nogo) ────────────────────────────────

VERDICT_GO = "go"        # 立项
VERDICT_HOLD = "hold"    # 暂缓立项（补充论证）
VERDICT_NOGO = "nogo"    # 不予立项

ALL_VERDICTS = frozenset({VERDICT_GO, VERDICT_HOLD, VERDICT_NOGO})


# ── Gap grading (§3.4.4) ──────────────────────────────────────────────

GAP_GRADE_PASS = "达标"
GAP_GRADE_MICRO = "微差"
GAP_GRADE_SIGNIFICANT = "显著差"
GAP_GRADE_LARGE = "大差"
GAP_GRADE_SEVERE = "严重失配"


def grade_gap(
    delta_sla: float,
    target_sla: float,
    risk_level: Optional[str] = None,
) -> dict[str, Any]:
    """Grade the SLA gap per §3.4.4 five-tier table.

    ``delta_sla`` = Actual − Target (pp).  Positive = meets/exceeds.
    Relative gap = |Δ| / SLA_tgt (when delta < 0).
    L3 scenarios with relative gap > 5% escalate to hard constraint.

    Returns ``{gap_grade, relative_gap_pct, l3_escalation}``.
    """
    if delta_sla >= 0:
        return {
            "gap_grade": GAP_GRADE_PASS,
            "relative_gap_pct": 0.0,
            "l3_escalation": False,
        }

    # Negative gap — compute relative gap ratio
    if not target_sla or target_sla <= 0:
        rel = 0.0
    else:
        rel = abs(delta_sla) / target_sla

    if rel <= GAP_GRADE_THRESHOLDS["micro"]:
        grade = GAP_GRADE_MICRO
    elif rel <= GAP_GRADE_THRESHOLDS["significant"]:
        grade = GAP_GRADE_SIGNIFICANT
    elif rel <= GAP_GRADE_THRESHOLDS["large"]:
        grade = GAP_GRADE_LARGE
    else:
        grade = GAP_GRADE_SEVERE

    # L3 escalation: relative gap > 5% → hard constraint (§3.4.4)
    l3_escalation = risk_level == "L3" and rel > GAP_GRADE_THRESHOLDS["micro"]

    return {
        "gap_grade": grade,
        "relative_gap_pct": round(rel * 100, 2),
        "l3_escalation": l3_escalation,
    }


# ═══════════════════════════════════════════════════════════════════════
# 式(6) decision
# ═══════════════════════════════════════════════════════════════════════


def compute_decision(
    *,
    g_hard: bool,
    delta_sla: Optional[float],
    net_value: Optional[float],
    sensitivity_confirmed_negative: bool = False,
    risk_level: Optional[str] = None,
    target_sla: Optional[float] = None,
    failed_terms: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Compute 式(6) verdict = dec(G_hard, Δ_sla, V_net).

    Returns a dict with:
      * ``verdict`` — go | hold | nogo
      * ``decision_rationale`` — Chinese one-liner
      * ``remediation_items`` — list (non-empty when hold)
      * ``exit_alternative_required`` — bool (True when nogo)
      * ``actor_masking_flag`` — False here (set by caller from net_value)
      * ``gap_grade`` — from grade_gap
      * ``dec_path`` — which 式(6) branch fired
    """
    delta = delta_sla if delta_sla is not None else None
    nv = net_value

    # ── Branch 1: G_hard = 0 → nogo (式(6) 第一条) ───────────────
    if not g_hard:
        remediation = build_remediation_items(
            failed_terms=failed_terms or [],
            delta_sla=delta,
            target_sla=target_sla,
            risk_level=risk_level,
            g_hard_failed=True,
        )
        rationale = "硬约束未通过（G_hard=0），建议不予立项并补配退出 AI 替代方案。"
        return {
            "verdict": VERDICT_NOGO,
            "decision_rationale": rationale,
            "remediation_items": remediation,
            "exit_alternative_required": True,
            "actor_masking_flag": False,
            "gap_grade": grade_gap(delta or 0.0, target_sla or 100.0, risk_level) if delta is not None else None,
            "dec_path": "式(6)第一条 G_hard=0 → nogo",
        }

    # G_hard = 1 — check soft constraints (Δ_sla, V_net)
    # ── Branch 2: G_hard=1 AND (Δ<0 OR V_net<0) → hold (式(6) 第二条) ─
    delta_bad = delta is not None and delta < 0
    nv_bad = nv is not None and nv < 0

    if delta_bad or nv_bad:
        # Sub-branch: V_net<0 AND sensitivity confirmed negative → nogo (第四条)
        if nv_bad and sensitivity_confirmed_negative:
            rationale = (
                "净价值持续为负且经敏感性分析确认（stability=confirmed 且结论为负），"
                "建议不予立项。"
            )
            return {
                "verdict": VERDICT_NOGO,
                "decision_rationale": rationale,
                "remediation_items": build_remediation_items(
                    failed_terms=[],
                    delta_sla=delta,
                    target_sla=target_sla,
                    risk_level=risk_level,
                    nv_negative_confirmed=True,
                ),
                "exit_alternative_required": True,
                "actor_masking_flag": False,
                "gap_grade": grade_gap(delta or 0.0, target_sla or 100.0, risk_level) if delta is not None else None,
                "dec_path": "式(6)第四条 V_net<0 且 sensitivity confirmed → nogo",
            }

        # Standard hold
        remediation = build_remediation_items(
            failed_terms=[],
            delta_sla=delta,
            target_sla=target_sla,
            risk_level=risk_level,
            nv_negative=nv_bad,
        )
        rationale_parts = []
        if delta_bad:
            rationale_parts.append(f"实际 SLA 未达目标（Δ_sla={delta:.1f}pp）")
        if nv_bad:
            rationale_parts.append(f"净价值为负（V_net={nv:.1f}）")
        rationale = "；".join(rationale_parts) + "，建议暂缓立项并补充论证。"
        return {
            "verdict": VERDICT_HOLD,
            "decision_rationale": rationale,
            "remediation_items": remediation,
            "exit_alternative_required": False,
            "actor_masking_flag": False,
            "gap_grade": grade_gap(delta or 0.0, target_sla or 100.0, risk_level) if delta is not None else None,
            "dec_path": "式(6)第二条 Δ<0 或 V_net<0 → hold",
        }

    # ── Branch 3: G_hard=1 AND Δ≥0 AND V_net≥0 → go (式(6) 第一条) ──
    rationale = "硬约束全部通过且实际 SLA 达标、净价值非负，建议立项。"
    return {
        "verdict": VERDICT_GO,
        "decision_rationale": rationale,
        "remediation_items": [],
        "exit_alternative_required": False,
        "actor_masking_flag": False,
        "gap_grade": grade_gap(delta or 0.0, target_sla or 100.0, risk_level) if delta is not None else None,
        "dec_path": "式(6)第一条 G_hard=1 且 Δ≥0 且 V_net≥0 → go",
    }


# ═══════════════════════════════════════════════════════════════════════
# Remediation list builder (§3.5.2 hold 态附补齐项清单)
# ═══════════════════════════════════════════════════════════════════════


def build_remediation_items(
    *,
    failed_terms: list[dict],
    delta_sla: Optional[float] = None,
    target_sla: Optional[float] = None,
    risk_level: Optional[str] = None,
    g_hard_failed: bool = False,
    nv_negative: bool = False,
    nv_negative_confirmed: bool = False,
) -> list[dict[str, Any]]:
    """Build the 补齐项清单 attached to ``hold`` / ``nogo`` verdicts.

    Each item: ``{dim, action, urgency}``.
    """
    items: list[dict[str, Any]] = []

    # Hard-constraint failures
    for term in failed_terms:
        term_id = term.get("term") or term.get("description", "")
        desc = term.get("description", str(term_id))
        items.append({
            "dim": "hard_constraint",
            "action": f"补齐硬约束项：{desc}",
            "urgency": "critical",
        })

    # SLA gap
    if delta_sla is not None and delta_sla < 0 and target_sla:
        grade = grade_gap(delta_sla, target_sla, risk_level)
        gap_grade = grade["gap_grade"]
        action_map = {
            GAP_GRADE_MICRO: "微差：软约束缓议，补强事实一致性量规阈值",
            GAP_GRADE_SIGNIFICANT: "显著差：触发 sla_gap_l3 告警，L3 场景升级 HITL 复核",
            GAP_GRADE_LARGE: "大差：任务/模型重设计，提交 AutoResearch 候选",
            GAP_GRADE_SEVERE: "严重失配：倾向不予立项，经硬约束复核后判定",
        }
        items.append({
            "dim": "qual",
            "action": action_map.get(gap_grade, "补强 SLA 达标"),
            "urgency": "high" if gap_grade in (GAP_GRADE_SIGNIFICANT, GAP_GRADE_LARGE) else "critical",
        })

    # Net value negative
    if nv_negative and not nv_negative_confirmed:
        items.append({
            "dim": "value",
            "action": "净价值为负：补充价值来源证明或重新核算实施税参数",
            "urgency": "high",
        })
    if nv_negative_confirmed:
        items.append({
            "dim": "value",
            "action": "净价值经敏感性分析确认持续为负：考虑退出 AI 应用替代方案",
            "urgency": "critical",
        })

    return items


# ═══════════════════════════════════════════════════════════════════════
# Exit-AI alternative validator (§3.5.3)
# ═══════════════════════════════════════════════════════════════════════


def validate_exit_alternative(
    verdict: str,
    alternative_flow_configured: bool = False,
) -> dict[str, Any]:
    """Validate that nogo verdicts have an exit-AI alternative plan (§3.5.3).

    nogo without an alternative → escalate to "nogo + must configure
    alternative flow" (执行条件子态, not a fourth verdict).
    """
    required = verdict == VERDICT_NOGO and not alternative_flow_configured
    note = ""
    if verdict == VERDICT_NOGO:
        if alternative_flow_configured:
            note = "退出 AI 替代方案已配置（人工处置流程+业务负责人审批）。"
        else:
            note = "未配置退出 AI 替代方案，须补配人工替代流程后方可执行不予立项决议。"
    return {
        "exit_alternative_required": required,
        "exit_alternative_note": note,
        "verdict": verdict,
    }
