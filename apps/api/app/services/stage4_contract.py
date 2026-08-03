"""Stage 4 contract validation and normalization helpers.

Stage 4 (Post-Implementation / Report & Export) validates:
- bundle_status valid enum
- evidence_count >= 3 (minimum for decision support)
- report_status valid enum
- decision_card present and structured
- export_ready boolean consistency
- evidence_refs presence
- risk_level propagation from Stage 1

Pure module — no FastAPI, repository, or model client imports.
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
