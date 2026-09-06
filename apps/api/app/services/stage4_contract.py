"""Stage 4 contract validation and normalization helpers.

Stage 4 (Post-Implementation / Report & Export) validates:
- bundle_status valid enum
- evidence_count >= 3 (minimum for decision support)
- report_status valid enum
- decision_card present and structured
- export_ready boolean consistency
- evidence_refs presence
- risk_level propagation from Stage 1
- 式(5)-(7) decision artifacts: G_hard/verdict/remediation_items/
  actor_net_value masking/exit_alternative/retro_gap (P4 validators)

Pure module — no FastAPI, repository, or model client imports.
Threshold/verdict constants are mirrored locally to avoid cross-module
coupling in the contract layer; the formulas package remains the single
source of truth for computation.
"""

from __future__ import annotations

from typing import Any

# ── Contract enum values ──────────────────────────────────────────────

BUNDLE_STATUSES = {"draft", "review", "locked", "approved"}
"""Valid evidence bundle statuses."""

REPORT_STATUSES = {"draft", "review", "approved", "published"}
"""Valid report statuses."""

MIN_EVIDENCE_COUNT = 3
"""Minimum evidence items required for a decision."""

EXPORT_READY_STATUSES = {"approved", "published"}
"""Report statuses that permit export."""

# ── Thesis verdict vocabulary (§3.5.2 式(6)) ─────────────────────────
# Local mirror of formulas/decision.py ALL_VERDICTS — the formulas
# package is the single source of truth; this mirror keeps the contract
# layer pure (no cross-module coupling).
THESIS_VERDICT_GO = "go"      # 立项
THESIS_VERDICT_HOLD = "hold"  # 暂缓立项（附补齐项清单）
THESIS_VERDICT_NOGO = "nogo"  # 不予立项（须配退出 AI 替代方案）
THESIS_VERDICTS = frozenset({THESIS_VERDICT_GO, THESIS_VERDICT_HOLD, THESIS_VERDICT_NOGO})

# 式(6) decision branches (dec_path) — substring markers, because
# compute_decision produces full sentences like
# "式(6)第二条 Δ<0 或 V_net<0 → hold" and registry.py may append
# suffixes (e.g. " (fusion hard-failures)") or emit a "fallback"
# string when inputs are insufficient.  We match on the branch marker
# substring so all legitimate variants validate.
DEC_PATH_BRANCH_FIRST = "式(6)第一条"    # G_hard=0 → nogo OR G_hard=1 且 Δ≥0 且 V_net≥0 → go
DEC_PATH_BRANCH_SECOND = "式(6)第二条"   # G_hard=1 且 (Δ<0 或 V_net<0) → hold
DEC_PATH_BRANCH_FOURTH = "式(6)第四条"   # G_hard=1 且 V_net<0 且 sensitivity confirmed → nogo
DEC_PATH_FALLBACK = "fallback"            # insufficient inputs for 式(6)
_DEC_PATH_BRANCHES = frozenset({
    DEC_PATH_BRANCH_FIRST, DEC_PATH_BRANCH_SECOND, DEC_PATH_BRANCH_FOURTH,
})

# remediation_items urgency vocabulary — must include "critical" because
# build_remediation_items emits it for hard-constraint failures, severe
# gaps, and sensitivity-confirmed-negative net value.
REMEDIATION_URGENCIES = frozenset({"critical", "high", "medium", "low"})

# ── Validation ────────────────────────────────────────────────────────


def validate_stage4_summary(summary: dict, *, previous_stage_result: dict | None = None) -> list[dict]:
    """Validate a Stage 4 summary dict.

    Returns a list of issue dicts (empty if valid).  Each issue has:
      issue_type, field, severity, message, suggested_action.

    Does **not** mutate the input.
    """
    issues: list[dict] = []

    # 1. bundle_status must be valid enum
    bundle_status = summary.get("bundle_status")
    if bundle_status not in BUNDLE_STATUSES:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "bundle_status",
            "severity": "high",
            "message": f"bundle_status must be {BUNDLE_STATUSES}, got {bundle_status!r}",
            "suggested_action": "Set bundle_status from evidence_bundle tool output",
        })

    # 2. evidence_count must be >= MIN_EVIDENCE_COUNT
    evidence_count = summary.get("evidence_count")
    if evidence_count is None:
        issues.append({
            "issue_type": "missing_field",
            "field": "evidence_count",
            "severity": "high",
            "message": "evidence_count is missing",
            "suggested_action": "Set evidence_count from evidence_bundle tool output",
        })
    elif not isinstance(evidence_count, int) or evidence_count < MIN_EVIDENCE_COUNT:
        issues.append({
            "issue_type": "insufficient_evidence",
            "field": "evidence_count",
            "severity": "medium" if isinstance(evidence_count, int) and evidence_count > 0 else "high",
            "message": f"evidence_count must be >= {MIN_EVIDENCE_COUNT}, got {evidence_count!r}",
            "suggested_action": "Collect more evidence items from preceding stages",
        })

    # 3. report_status must be valid enum
    report_status = summary.get("report_status")
    if report_status not in REPORT_STATUSES:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "report_status",
            "severity": "high",
            "message": f"report_status must be {REPORT_STATUSES}, got {report_status!r}",
            "suggested_action": "Set report_status from report_generate tool output",
        })

    # 4. decision_card must be present and structured
    decision_card = summary.get("decision_card")
    if decision_card is None:
        issues.append({
            "issue_type": "missing_field",
            "field": "decision_card",
            "severity": "high",
            "message": "decision_card is missing",
            "suggested_action": "Generate decision_card from report_generate tool output",
        })
    elif isinstance(decision_card, dict):
        # Check key sub-fields
        if not decision_card.get("recommendation"):
            issues.append({
                "issue_type": "incomplete_decision_card",
                "field": "decision_card.recommendation",
                "severity": "medium",
                "message": "decision_card missing recommendation",
                "suggested_action": "Add recommendation to decision_card (proceed|pivot|pause|abandon)",
            })
        if not decision_card.get("confidence"):
            issues.append({
                "issue_type": "incomplete_decision_card",
                "field": "decision_card.confidence",
                "severity": "medium",
                "message": "decision_card missing confidence score",
                "suggested_action": "Add confidence score to decision_card",
            })

    # 5. export_ready must be consistent with report_status
    export_ready = summary.get("export_ready")
    if export_ready is True and report_status not in EXPORT_READY_STATUSES:
        issues.append({
            "issue_type": "export_inconsistency",
            "field": "export_ready",
            "severity": "high",
            "message": f"export_ready=True but report_status is {report_status!r} (not approved/published)",
            "suggested_action": "Set export_ready=False until report is approved or published",
        })
    if export_ready is False and report_status in EXPORT_READY_STATUSES:
        issues.append({
            "issue_type": "export_inconsistency",
            "field": "export_ready",
            "severity": "medium",
            "message": f"export_ready=False but report_status is {report_status!r} (approved/published)",
            "suggested_action": "Set export_ready=True when report is approved/published",
        })

    # 6. evidence_refs must be non-empty
    evidence_refs = summary.get("evidence_refs", [])
    if not evidence_refs:
        issues.append({
            "issue_type": "weak_evidence",
            "field": "evidence_refs",
            "severity": "medium",
            "message": "Stage 4 summary has no evidence references",
            "suggested_action": "Bind evidence items from all preceding stages",
        })

    # 7. risk_level must be present
    risk_level = summary.get("risk_level")
    if risk_level not in {"L1", "L2", "L3"}:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "risk_level",
            "severity": "high",
            "message": f"risk_level must be L1|L2|L3, got {risk_level!r}",
            "suggested_action": "Propagate risk_level from Stage 1 scenario_summary",
        })
    elif previous_stage_result:
        prev_risk = (previous_stage_result.get("scenario_summary") or {}).get("risk_level", "")
        if prev_risk and risk_level != prev_risk:
            issues.append({
                "issue_type": "risk_level_mismatch",
                "field": "risk_level",
                "severity": "high",
                "message": f"Stage 4 risk_level {risk_level!r} does not match Stage 1 risk_level {prev_risk!r}",
                "suggested_action": "Align risk_level with Stage 1 or document escalation reason",
            })

    # 8. L3 risk with draft bundle requires attention
    if risk_level == "L3" and bundle_status == "draft":
        issues.append({
            "issue_type": "l3_draft_bundle",
            "field": "bundle_status",
            "severity": "high",
            "message": "L3 scenario evidence bundle is still in draft status",
            "suggested_action": "Lock and review evidence bundle before proceeding to report",
        })

    # 9. sections must be present in report
    sections = summary.get("sections")
    if sections is not None and isinstance(sections, list) and len(sections) == 0:
        issues.append({
            "issue_type": "empty_sections",
            "field": "sections",
            "severity": "medium",
            "message": "Report has no sections defined",
            "suggested_action": "Add report sections covering risk assessment, SLA results, and recommendations",
        })

    # 10-17. 式(5)-(7) decision artifacts (P4 validators)
    # These fields are optional (❌ in data-contract §7.1 default None/[]),
    # but when present must satisfy the §7.3 cross-field constraints.
    issues.extend(_validate_stage4_formula_artifacts(summary))

    return issues


# ── 式(5)-(7) decision-artifact validation ────────────────────────────


def _validate_stage4_formula_artifacts(summary: dict) -> list[dict]:
    """Validate 式(5)-(7) decision artifacts and §7.3 cross-field constraints.

    Checks (P4):
      10. G_hard is bool when present; g_hard_components is dict when present
      11. verdict ∈ {go, hold, nogo} when present; dec_path matches a
          式(6) branch marker (substring) or the fallback marker
      12. G_hard=0 → verdict=nogo + exit_alternative_required=True (§7.3)
      13. verdict=hold → remediation_items non-empty (§7.3)
      14. verdict=nogo → exit_alternative_required=True (§3.5.3)
      15. remediation_items schema when present ({dim, action, urgency})
      16. actor_net_value masking: net_value_i<0 → masking_actors non-empty +
          actor_masking_flag=True (§5.1 aggregation_masking)
      17. retro_gap schema when present (式(7) {gap, needs_revision})
    """
    issues: list[dict] = []

    # 10. G_hard — 式(5) seven-term conjunction result
    g_hard = summary.get("G_hard")
    g_hard_components = summary.get("g_hard_components")
    if g_hard is not None:
        if not isinstance(g_hard, bool):
            issues.append({
                "issue_type": "invalid_value",
                "field": "G_hard",
                "severity": "high",
                "message": f"G_hard must be bool (式(5) 合取结果), got {type(g_hard).__name__}",
                "suggested_action": "Recompute G_hard via compute_g_hard",
            })
    if g_hard_components is not None and not isinstance(g_hard_components, dict):
        issues.append({
            "issue_type": "invalid_value",
            "field": "g_hard_components",
            "severity": "medium",
            "message": "g_hard_components must be dict (七项明细)",
            "suggested_action": "Recompute g_hard_components via compute_g_hard",
        })

    # 11. verdict — 式(6) go/hold/nogo
    verdict = summary.get("verdict")
    if verdict is not None and verdict not in THESIS_VERDICTS:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "verdict",
            "severity": "high",
            "message": f"verdict must be {set(THESIS_VERDICTS)} (论文口径), got {verdict!r}",
            "suggested_action": "Recompute verdict via compute_decision",
        })

    dec_path = summary.get("dec_path")
    if dec_path is not None and isinstance(dec_path, str):
        # dec_path is a full sentence from compute_decision (e.g.
        # "式(6)第二条 Δ<0 或 V_net<0 → hold") possibly with a registry
        # suffix.  Match on the branch-marker substring, or the
        # "fallback" marker when inputs were insufficient for 式(6).
        is_branch = any(marker in dec_path for marker in _DEC_PATH_BRANCHES)
        is_fallback = DEC_PATH_FALLBACK in dec_path
        if not (is_branch or is_fallback):
            issues.append({
                "issue_type": "invalid_value",
                "field": "dec_path",
                "severity": "low",
                "message": f"dec_path {dec_path!r} does not match any 式(6) branch marker ({set(_DEC_PATH_BRANCHES)}) or fallback",
                "suggested_action": "Check compute_decision dec_path mapping",
            })

    # 12. G_hard=0 → verdict=nogo + exit_alternative_required=True (§7.3 第一条硬约束否决)
    exit_alt_required = summary.get("exit_alternative_required")
    if g_hard is False:
        if verdict is not None and verdict != THESIS_VERDICT_NOGO:
            issues.append({
                "issue_type": "verdict_inconsistency",
                "field": "verdict",
                "severity": "high",
                "message": f"G_hard=False (硬约束否决) but verdict={verdict!r} (should be nogo)",
                "suggested_action": "G_hard=0 → verdict=nogo per 式(6) 第一条",
            })
        if exit_alt_required is not True:
            issues.append({
                "issue_type": "exit_alternative_inconsistency",
                "field": "exit_alternative_required",
                "severity": "high",
                "message": "G_hard=False but exit_alternative_required is not True (§3.5.3 nogo 须配替代方案)",
                "suggested_action": "Set exit_alternative_required=True when verdict=nogo",
            })

    # 13. verdict=hold → remediation_items non-empty (§7.3)
    remediation_items = summary.get("remediation_items")
    if verdict == THESIS_VERDICT_HOLD and not remediation_items:
        issues.append({
            "issue_type": "missing_remediation",
            "field": "remediation_items",
            "severity": "high",
            "message": "verdict=hold but remediation_items is empty/missing (§7.3: hold 必附补齐项清单)",
            "suggested_action": "Populate remediation_items via build_remediation_items",
        })

    # 14. verdict=nogo → exit_alternative_required=True (§3.5.3)
    if verdict == THESIS_VERDICT_NOGO and exit_alt_required is not True:
        issues.append({
            "issue_type": "exit_alternative_inconsistency",
            "field": "exit_alternative_required",
            "severity": "high",
            "message": "verdict=nogo but exit_alternative_required is not True (§3.5.3)",
            "suggested_action": "Configure exit-AI alternative or document reason",
        })

    # 15. remediation_items schema when present
    if isinstance(remediation_items, list):
        for i, item in enumerate(remediation_items):
            if not isinstance(item, dict):
                continue
            if not item.get("action"):
                issues.append({
                    "issue_type": "incomplete_remediation",
                    "field": f"remediation_items[{i}].action",
                    "severity": "medium",
                    "message": f"remediation_items[{i}] missing action",
                    "suggested_action": "Add concrete remediation action",
                })
            urgency = item.get("urgancy") or item.get("urgency")
            if urgency is not None and urgency not in REMEDIATION_URGENCIES:
                issues.append({
                    "issue_type": "invalid_enum",
                    "field": f"remediation_items[{i}].urgency",
                    "severity": "low",
                    "message": f"remediation urgency {urgency!r} not in {set(REMEDIATION_URGENCIES)}",
                    "suggested_action": "Use high/medium/low",
                })

    # 16. actor_net_value masking (§5.1 aggregation_masking)
    actor_net_value = summary.get("actor_net_value")
    masking_actors = summary.get("masking_actors")
    actor_masking_flag = summary.get("actor_masking_flag")
    if isinstance(actor_net_value, list) and actor_net_value:
        negative_actors = [
            a.get("actor", f"<{i}>") for i, a in enumerate(actor_net_value)
            if isinstance(a, dict) and isinstance(a.get("net_value_i"), (int, float))
            and a["net_value_i"] < 0
        ]
        if negative_actors and not masking_actors:
            issues.append({
                "issue_type": "masking_inconsistency",
                "field": "masking_actors",
                "severity": "medium",
                "message": f"actor_net_value has negative members {negative_actors} but masking_actors is empty",
                "suggested_action": "Populate masking_actors from compute_actor_net_value",
            })
        if negative_actors and actor_masking_flag is not True:
            issues.append({
                "issue_type": "masking_inconsistency",
                "field": "actor_masking_flag",
                "severity": "medium",
                "message": "actor_net_value has negative members but actor_masking_flag is not True (aggregation masking)",
                "suggested_action": "Set actor_masking_flag=True when any net_value_i<0",
            })

    # 17. retro_gap schema — 式(7) 开环预留
    retro_gap = summary.get("retro_gap")
    if retro_gap is not None:
        if not isinstance(retro_gap, dict):
            issues.append({
                "issue_type": "invalid_value",
                "field": "retro_gap",
                "severity": "medium",
                "message": "retro_gap must be a dict (式(7) {gap, needs_revision})",
                "suggested_action": "Recompute retro_gap via compute_retro_gap",
            })
        else:
            if "gap" not in retro_gap:
                issues.append({
                    "issue_type": "missing_field",
                    "field": "retro_gap.gap",
                    "severity": "medium",
                    "message": "retro_gap missing gap (式(7) 绝对偏差)",
                    "suggested_action": "Set retro_gap.gap = sla_act_probe - sla_act_retro",
                })
            if "needs_revision" not in retro_gap:
                issues.append({
                    "issue_type": "missing_field",
                    "field": "retro_gap.needs_revision",
                    "severity": "medium",
                    "message": "retro_gap missing needs_revision (|gap|>3pp → True)",
                    "suggested_action": "Set retro_gap.needs_revision from compute_retro_gap",
                })

    return issues


# ── Quality scoring ────────────────────────────────────────────────────

_STAGE4_QUALITY_WEIGHTS = {
    "completeness": 0.20,
    "evidence_sufficiency": 0.25,
    "decision_readiness": 0.25,
    "risk_consistency": 0.15,
    "export_readiness": 0.15,
}


def compute_stage4_quality(summary: dict) -> dict:
    """Compute quality scores for a Stage 4 summary.

    Returns a dict with six float scores in [0, 1]:
      completeness_score, evidence_sufficiency_score, decision_readiness_score,
      risk_consistency_score, export_readiness_score, audit_readiness_score

    Does **not** mutate the input.
    """
    # Completeness: fraction of key fields present
    key_fields = [
        "bundle_status", "evidence_count", "report_status",
        "decision_card", "export_ready", "risk_level", "evidence_refs",
    ]
    present = 0
    for field in key_fields:
        val = summary.get(field)
        if val is not None and val != "" and val != []:
            present += 1
    completeness = present / len(key_fields) if key_fields else 0.0

    # Evidence sufficiency: evidence_count relative to MIN_EVIDENCE_COUNT
    evidence_count = summary.get("evidence_count")
    if isinstance(evidence_count, int) and evidence_count > 0:
        evidence_sufficiency = min(1.0, evidence_count / MIN_EVIDENCE_COUNT)
    else:
        evidence_sufficiency = 0.0

    # Decision readiness: decision_card completeness + report_status
    decision_card = summary.get("decision_card")
    decision_readiness = 0.0
    report_status = summary.get("report_status")
    if isinstance(decision_card, dict):
        has_rec = bool(decision_card.get("recommendation"))
        has_conf = bool(decision_card.get("confidence"))
        if has_rec and has_conf:
            decision_readiness = 0.8
        elif has_rec or has_conf:
            decision_readiness = 0.4
    if report_status in {"approved", "published"}:
        decision_readiness = min(1.0, decision_readiness + 0.2)

    # Risk consistency
    risk_level = summary.get("risk_level")
    risk_consistency = 1.0 if risk_level in {"L1", "L2", "L3"} else 0.0

    # Export readiness
    export_ready = summary.get("export_ready")
    bundle_status = summary.get("bundle_status")
    export_readiness = 0.0
    if export_ready is True:
        export_readiness = 1.0
    elif bundle_status in {"locked", "approved"}:
        export_readiness = 0.5

    # Audit readiness: weighted combination
    audit_readiness = (
        completeness * _STAGE4_QUALITY_WEIGHTS["completeness"]
        + evidence_sufficiency * _STAGE4_QUALITY_WEIGHTS["evidence_sufficiency"]
        + decision_readiness * _STAGE4_QUALITY_WEIGHTS["decision_readiness"]
        + risk_consistency * _STAGE4_QUALITY_WEIGHTS["risk_consistency"]
        + export_readiness * _STAGE4_QUALITY_WEIGHTS["export_readiness"]
    )

    return {
        "completeness_score": round(completeness, 4),
        "evidence_sufficiency_score": round(evidence_sufficiency, 4),
        "decision_readiness_score": round(decision_readiness, 4),
        "risk_consistency_score": round(risk_consistency, 4),
        "export_readiness_score": round(export_readiness, 4),
        "audit_readiness_score": round(audit_readiness, 4),
    }
