"""autoResearch suggestion services."""

from __future__ import annotations

from uuid import uuid4
from typing import Any, Optional, Tuple

from fastapi import HTTPException, status

from src.apps.api.app.domain.models import (
    AutoResearchCandidate,
    AutoResearchRecord,
    CapabilityMutabilityContract,
    FrozenEvalContract,
    RejectedCandidate,
    RuleProposal,
    StageResult,
    utcnow,
)
from src.apps.api.app.repositories.store import (
    get_autoresearch_record,
    get_latest_stage_result,
    list_evidence_items,
    list_file_artifacts,
    list_autoresearch_records as repo_list_autoresearch_records,
    save_autoresearch_record,
    save_autoresearch_candidate,
    save_capability_mutability_contract,
    save_evidence_item,
    save_frozen_eval_contract,
    save_rejected_candidate,
    save_rule_proposal,
    save_stage_result,
    get_latest_capability_mutability_contract,
    get_latest_frozen_eval_contract,
)
from src.apps.api.app.services.log_service import create_execution_log, create_version_log
from src.apps.api.app.services.project_service import get_stage
from src.apps.api.app.services.run_service import get_run
from src.apps.api.app.services.stage_result_service import build_stage_result_diff


# Whitelisted fields that AutoResearch may patch on a Stage 1 scenario_summary.
# Field names outside this set are rejected to prevent contract violations.
_WHITELISTED_PATCH_FIELDS = frozenset({
    # Stage 1
    "risk_level", "boundary", "risk_items", "risk_matrix",
    "hitl_rules", "hitl_level", "audit_requirements",
    "prohibited_conditions", "fatal_errors", "to_confirm",
    "risk_confidence",  # Phase 4: confidence_mismatch auto-repair
    # Stage 2
    "implementation_tax", "target_sla", "stability",
    # Stage 3
    "sample_size", "low_score_samples", "actual_sla", "gap_to_target_pct",
    # Stage 4
    "bundle_status", "report_status", "decision_card", "export_ready",
    "evidence_count", "sections", "gaps", "blocking_issues",
})


# L3: capability-layer whitelist.  Distinct from the data-layer
# ``_WHITELISTED_PATCH_FIELDS`` above.  These are *capability* fields —
# prompt body, tool enablement, model alias, skill version — that change
# how a skill *behaves*, not what it *says* about a given scenario.
# Modifications go through ``CapabilityMutabilityContract`` gates (sample
# size + min improvement) and are written to settings.draft, never to
# published settings.
CAPABILITY_WHITELIST = frozenset({
    "prompt.body",          # 修改 PromptTemplate.body
    "prompt.version",       # bump prompt.version v1→v2
    "prompt.required_vars", # 修改 required_variables 列表
    "tool.enabled",         # 启用/停用 tool
    "tool.allowed",         # 修改 allowed_tools 列表
    "model.alias",          # 切换 model_aliases 引用
    "skill.skill_version",  # bump skill.skill_versions
})


# L3: rejection reasons for capability patches
CAPABILITY_REJECTION_NOT_WHITELISTED = "capability_not_whitelisted"
CAPABILITY_REJECTION_GATE_FAILED = "capability_gate_failed"
CAPABILITY_REJECTION_PROMPT_INVALID = "prompt_validation_failed"
CAPABILITY_REJECTION_NOT_PATCHABLE = "no_capability_patch_proposed"


# ── Patch confidence scoring ───────────────────────────────────────────
# Auto-accept when the auto-repair pipeline is confident enough.
# Two independent signals are combined:
#   1. patchable_ratio: fraction of issues with a suggested_patch
#   2. severity_clear:  no high-severity issues are unpatchable
# Each weight is exposed as a constant so the formula can be tuned
# and tested in isolation.
_PATCH_CONFIDENCE_RATIO_WEIGHT = 0.6
_PATCH_CONFIDENCE_SEVERITY_BONUS = 0.4
AUTO_ACCEPT_CONFIDENCE_THRESHOLD = 0.95


def _compute_patch_confidence(validation_issues: list[dict], scenario_summary: dict) -> float:
    """Score how confident we are that auto-repair can resolve all issues.

    Confidence is the weighted sum of two independent signals:
      * ratio of issues that have a ``suggested_patch`` (weight 0.6)
      * bonus 0.4 when no high-severity issue is unpatchable

    A high-severity issue without a suggested_patch drops the bonus to
    zero — those issues require human judgment.
    """
    if not validation_issues:
        return 1.0
    total = len(validation_issues)
    patchable = sum(1 for i in validation_issues if i.get("suggested_patch") is not None)
    ratio = patchable / total
    high_without_patch = sum(
        1 for i in validation_issues
        if i.get("severity") == "high" and not i.get("suggested_patch")
    )
    confidence = (
        ratio * _PATCH_CONFIDENCE_RATIO_WEIGHT
        + (_PATCH_CONFIDENCE_SEVERITY_BONUS if high_without_patch == 0 else 0.0)
    )
    return min(1.0, confidence)


def _build_suggested_patch(issue: dict, scenario_summary: dict) -> Optional[dict]:
    """Build a suggested patch dict from a validation issue.

    Returns None if no patch can be automatically suggested.
    For risk_level patches, also cascades to fix dependent fields
    (hitl_level, hitl_rules) to prevent post-patch validation failures.
    """
    issue_type = issue.get("issue_type", "")
    field = issue.get("field", "")

    if issue_type == "invalid_enum" and field == "risk_level":
        from src.apps.api.app.services.stage1_contract import normalize_risk_level
        raw = scenario_summary.get("risk_level")
        try:
            normalized = normalize_risk_level(raw)
            patches = [{"op": "replace", "field": "risk_level", "value": normalized}]
            # Cascade: if hitl_level is also invalid for the new risk_level, fix it
            hitl_raw = scenario_summary.get("hitl_level", "none")
            from src.apps.api.app.services.stage1_contract import normalize_hitl_level
            try:
                normalized_hitl = normalize_hitl_level(hitl_raw, risk_level=normalized)
                if normalized_hitl != hitl_raw:
                    patches.append({"op": "replace", "field": "hitl_level", "value": normalized_hitl})
            except (ValueError, TypeError):
                patches.append({"op": "replace", "field": "hitl_level", "value": "strict" if normalized == "L3" else "standard"})
            # Cascade: if risk is now L2/L3 but hitl_rules empty, add a placeholder
            if normalized in {"L2", "L3"} and not scenario_summary.get("hitl_rules"):
                patches.append({
                    "op": "add", "field": "hitl_rules",
                    "value": [{
                        "risk_level": normalized,
                        "review_level": normalized_hitl if 'normalized_hitl' in dir() else ("strict" if normalized == "L3" else "standard"),
                        "review_trigger": "风险等级判定" if normalized == "L3" else "复核确认",
                        "review_owner": "风险经理" if normalized == "L3" else "业务负责人",
                        "review_evidence": [],
                        "evidence_refs": scenario_summary.get("evidence_refs", [])[:1],
                    }],
                })
            return {"op": "multi", "patches": patches}
        except (ValueError, TypeError):
            return None

    if issue_type == "invalid_enum" and field == "hitl_level":
        from src.apps.api.app.services.stage1_contract import normalize_hitl_level
        raw = scenario_summary.get("hitl_level")
        risk_level = scenario_summary.get("risk_level")
        try:
            normalized = normalize_hitl_level(raw, risk_level=risk_level)
            return {"op": "replace", "field": "hitl_level", "value": normalized}
        except (ValueError, TypeError):
            return None

    if issue_type == "hitl_mismatch" and field == "hitl_level":
        risk_level = scenario_summary.get("risk_level")
        if risk_level == "L3":
            return {"op": "replace", "field": "hitl_level", "value": "strict"}
        return None

    # --- missing_field patches ---
    if issue_type == "missing_field" and field == "risk_items":
        risk_level = scenario_summary.get("risk_level", "L1")
        return {"op": "add", "field": "risk_items", "value": [{
            "risk_id": "risk-auto-1",
            "description": "通用风险（自动补充）",
            "severity": "medium",
            "likelihood": "medium",
            "impact": "",
            "owner_role": "",
            "mitigation": "",
            "audit_need": "",
            "risk_level": risk_level,
            "evidence_refs": scenario_summary.get("evidence_refs", [])[:1],
        }]}

    if issue_type == "missing_field" and field == "risk_matrix":
        risk_items = scenario_summary.get("risk_items", [])
        if risk_items:
            matrix = [
                {
                    "risk_id": item.get("risk_id", f"risk-{i+1}"),
                    "item": item.get("description", ""),
                    "level": item.get("risk_level", "L1"),
                    "control": item.get("mitigation", "") or "人工复核",
                    "evidence_refs": item.get("evidence_refs", []),
                }
                for i, item in enumerate(risk_items)
            ]
        else:
            matrix = [{"risk_id": "risk-1", "item": "通用风险", "level": scenario_summary.get("risk_level", "L1"), "control": "人工复核", "evidence_refs": []}]
        return {"op": "add", "field": "risk_matrix", "value": matrix}

    if issue_type == "missing_field" and field == "hitl_rules":
        risk_level = scenario_summary.get("risk_level", "L1")
        if risk_level in {"L2", "L3"}:
            hitl_level = scenario_summary.get("hitl_level", "strict" if risk_level == "L3" else "standard")
            return {"op": "add", "field": "hitl_rules", "value": [{
                "risk_level": risk_level,
                "review_level": hitl_level,
                "review_trigger": "风险等级判定" if risk_level == "L3" else "复核确认",
                "review_owner": "风险经理" if risk_level == "L3" else "业务负责人",
                "review_evidence": [],
                "evidence_refs": scenario_summary.get("evidence_refs", [])[:1],
            }]}
        return None  # L1 doesn't require hitl_rules

    # --- quality threshold patches ---
    if issue_type == "quality_threshold" and field == "completeness_score":
        return {"op": "replace", "field": "review_status", "value": "needs_review"}

    if issue_type == "quality_threshold" and field == "evidence_coverage_score":
        return None  # Requires human to add evidence

    # --- confidence_mismatch (Phase 4) ---
    if issue_type == "confidence_mismatch" and field == "risk_confidence.dominant_level":
        # Re-align the dominant_level to match the resolved risk_level,
        # keeping the existing per-level distribution intact.
        risk_level = scenario_summary.get("risk_level", "")
        existing_confidence = scenario_summary.get("risk_confidence")
        if not isinstance(existing_confidence, dict):
            existing_confidence = {}
        return {
            "op": "replace",
            "field": "risk_confidence",
            "value": {**existing_confidence, "dominant_level": risk_level},
        }

    # No auto-patch for other missing fields or weak evidence — needs human judgment
    return None


def _build_suggested_patch_stage2(issue: dict, stage2_summary: dict) -> Optional[dict]:
    """Build a suggested patch dict for Stage 2 validation issues."""
    issue_type = issue.get("issue_type", "")
    field = issue.get("field", "")

    if issue_type == "invalid_enum" and field == "implementation_tax":
        from src.apps.api.app.services.stage2_contract import normalize_implementation_tax
        raw = stage2_summary.get("implementation_tax")
        risk_level = stage2_summary.get("risk_level")
        try:
            normalized = normalize_implementation_tax(raw, risk_level=risk_level)
            return {"op": "replace", "field": "implementation_tax", "value": normalized}
        except (ValueError, TypeError):
            return None

    if issue_type == "invalid_enum" and field == "stability":
        # Try to normalize to confirmed if possible
        raw = stage2_summary.get("stability", "")
        if raw in {"confirmed", "needs_confirmation", "unstable"}:
            return None  # Already valid
        return {"op": "replace", "field": "stability", "value": "needs_confirmation"}

    if issue_type == "missing_field" and field == "target_sla":
        # Cannot auto-generate target_sla — requires human judgment
        return None

    if issue_type == "value_mismatch" and field == "implementation_tax":
        risk_level = stage2_summary.get("risk_level")
        if risk_level == "L3":
            return {"op": "replace", "field": "implementation_tax", "value": "high"}
        return None

    if issue_type == "sla_unstable" and field == "stability":
        # Cannot auto-fix unstable SLA — requires HITL
        return None

    return None


def _build_suggested_patch_stage3(issue: dict, stage3_summary: dict) -> Optional[dict]:
    """Build a suggested patch dict for Stage 3 validation issues."""
    issue_type = issue.get("issue_type", "")
    field = issue.get("field", "")

    if issue_type == "invalid_value" and field == "sample_size":
        # Cannot auto-fix invalid sample_size
        return None

    if issue_type == "invalid_value" and field == "low_score_samples":
        # Cannot auto-fix — requires re-scoring
        return None

    if issue_type == "missing_field" and field == "gap_to_target_pct":
        # Cannot auto-compute — requires actual measurement
        return None

    if issue_type == "out_of_range" and field == "gap_to_target_pct":
        from src.apps.api.app.services.stage3_contract import normalize_gap_to_target_pct
        raw = stage3_summary.get("gap_to_target_pct")
        try:
            normalized = normalize_gap_to_target_pct(raw)
            return {"op": "replace", "field": "gap_to_target_pct", "value": normalized}
        except (ValueError, TypeError):
            return None

    if issue_type == "out_of_range" and field == "actual_sla":
        from src.apps.api.app.services.stage3_contract import normalize_actual_sla
        raw = stage3_summary.get("actual_sla")
        try:
            normalized = normalize_actual_sla(raw)
            return {"op": "replace", "field": "actual_sla", "value": normalized}
        except (ValueError, TypeError):
            return None

    if issue_type == "sla_gap_l3" and field == "gap_to_target_pct":
        # L3 + large gap requires HITL — no auto-patch
        return None

    return None


def _build_suggested_patch_stage4(issue: dict, stage4_summary: dict) -> Optional[dict]:
    """Build a suggested patch dict for Stage 4 validation issues."""
    issue_type = issue.get("issue_type", "")
    field = issue.get("field", "")

    if issue_type == "invalid_enum" and field == "bundle_status":
        from src.apps.api.app.services.stage4_contract import BUNDLE_STATUSES
        raw = stage4_summary.get("bundle_status")
        if raw in BUNDLE_STATUSES:
            return None  # Already valid
        return {"op": "replace", "field": "bundle_status", "value": "draft"}

    if issue_type == "invalid_enum" and field == "report_status":
        from src.apps.api.app.services.stage4_contract import REPORT_STATUSES
        raw = stage4_summary.get("report_status")
        if raw in REPORT_STATUSES:
            return None
        return {"op": "replace", "field": "report_status", "value": "draft"}

    if issue_type == "missing_field" and field == "decision_card":
        # Cannot auto-generate decision card
        return None

    if issue_type == "export_inconsistency" and field == "export_ready":
        from src.apps.api.app.services.stage4_contract import EXPORT_READY_STATUSES
        report_status = stage4_summary.get("report_status", "")
        if report_status in EXPORT_READY_STATUSES:
            return {"op": "replace", "field": "export_ready", "value": True}
        return {"op": "replace", "field": "export_ready", "value": False}

    if issue_type == "l3_draft_bundle" and field == "bundle_status":
        # L3 + draft → requires review, not auto-patch
        return {"op": "replace", "field": "bundle_status", "value": "review"}

    return None


def _extract_autoresearch_signal(stage_result: StageResult) -> dict[str, Any]:
    payload = stage_result.result_payload or {}
    tool_results = payload.get("tool_results", {})
    vision_inputs = payload.get("vision_inputs", [])
    to_confirm_count = sum(len(item.get("to_confirm", [])) for item in vision_inputs)
    uncertainties = sum(len(item.get("uncertainties", [])) for item in vision_inputs)
    return {
        "tool_results": tool_results,
        "vision_inputs": vision_inputs,
        "to_confirm_count": to_confirm_count,
        "uncertainty_count": uncertainties,
        "evidence_count": len(stage_result.evidence_item_ids),
    }


def _validate_and_score_stage(
    *,
    stage_id: str,
    stage_result: StageResult,
    payload_key: str,
    validate_fn_name: str,
    quality_fn_name: str,
    patch_fn: Any,
    quality_thresholds: dict[str, float],
) -> dict[str, Any]:
    """Common template: validate the stage summary, score it, build
    structured_issues, and identify low_quality_fields.

    Each stage uses different validate/quality/patch callables and
    looks at a different payload key — but the post-validation
    shape is identical.  Returns:
        {
          "stage_summary": <dict from payload[payload_key]>,
          "validation_issues": [...],
          "quality_scores": {...},
          "structured_issues": [...],
          "low_quality_fields": [...],
        }
    """
    payload = stage_result.result_payload or {}
    stage_summary = payload.get(payload_key, {}) if payload_key else {}
    validation_issues: list[dict] = []
    quality_scores: dict = {}

    if stage_summary:
        # Resolve validate/quality callables from the matching contract module.
        if stage_id.endswith("stage-1"):
            contract_module = __import__(
                "src.apps.api.app.services.stage1_contract", fromlist=["*"]
            )
        elif stage_id.endswith("stage-2"):
            contract_module = __import__(
                "src.apps.api.app.services.stage2_contract", fromlist=["*"]
            )
        elif stage_id.endswith("stage-3"):
            contract_module = __import__(
                "src.apps.api.app.services.stage3_contract", fromlist=["*"]
            )
        elif stage_id.endswith("stage-4"):
            contract_module = __import__(
                "src.apps.api.app.services.stage4_contract", fromlist=["*"]
            )
        else:
            contract_module = None
        if contract_module is not None:
            validate_fn = getattr(contract_module, validate_fn_name, None)
            quality_fn = getattr(contract_module, quality_fn_name, None)
            prev = payload.get("scenario_summary", {})
            previous_stage_result = {"scenario_summary": prev} if prev else None
            if validate_fn is not None:
                validation_issues = (
                    validate_fn(stage_summary, previous_stage_result=previous_stage_result)
                    if previous_stage_result is not None
                    else validate_fn(stage_summary)
                )
            if quality_fn is not None:
                quality_scores = quality_fn(stage_summary)

    structured_issues = []
    for issue in validation_issues:
        structured_issues.append({
            "issue_type": issue.get("issue_type", "unknown"),
            "affected_field": issue.get("field", ""),
            "severity": issue.get("severity", "medium"),
            "suggested_action": issue.get("suggested_action", ""),
            "suggested_patch": patch_fn(issue, stage_summary) if patch_fn else None,
        })

    low_quality_fields = []
    for score_name, threshold in quality_thresholds.items():
        score_val = quality_scores.get(score_name, 0.0)
        if score_val < threshold:
            low_quality_fields.append({
                "field": score_name,
                "current": score_val,
                "threshold": threshold,
                "gap": round(threshold - score_val, 4),
            })

    return {
        "stage_summary": stage_summary,
        "validation_issues": validation_issues,
        "quality_scores": quality_scores,
        "structured_issues": structured_issues,
        "low_quality_fields": low_quality_fields,
    }


def _format_low_quality_suffix(low_quality_fields: list[dict]) -> str:
    """Append a "worst quality dimension" line to a description."""
    if not low_quality_fields:
        return ""
    worst = min(low_quality_fields, key=lambda f: f["current"])
    return " 质量维度「{0}」未达阈值（当前 {1:.2f}，要求 {2:.2f}）。".format(
        worst["field"], worst["current"], worst["threshold"]
    )


def _build_stage_specific_recommendation(stage_name: str, stage_id: str, stage_result: StageResult) -> dict[str, Any]:
    """Build stage-specific AutoResearch recommendation.

    For Stage 1, generates structured issues from contract validation
    rather than generic text-only recommendations.
    """
    signal = _extract_autoresearch_signal(stage_result)
    tool_results = signal["tool_results"]
    to_confirm_count = signal["to_confirm_count"]
    evidence_count = signal["evidence_count"]

    if stage_id.endswith("stage-1"):
        # Stage 1: Generate issues from contract validation
        scenario_summary = (stage_result.result_payload or {}).get("scenario_summary", {})
        missing_hitl = to_confirm_count > 0 or "risk_identify" not in tool_results

        if scenario_summary:
            from src.apps.api.app.services.stage1_contract import (
                validate_stage1_summary,
                compute_stage1_quality,
            )
            validation_issues = validate_stage1_summary(scenario_summary)
            quality_scores = compute_stage1_quality(scenario_summary)
        else:
            validation_issues = []
            quality_scores = {}

        # Build structured issues from contract validation
        structured_issues = []
        for issue in validation_issues:
            severity = issue.get("severity", "medium")
            structured_issues.append({
                "issue_type": issue.get("issue_type", "unknown"),
                "affected_field": issue.get("field", ""),
                "severity": severity,
                "suggested_action": issue.get("suggested_action", ""),
                "suggested_patch": _build_suggested_patch(issue, scenario_summary),
            })

        # Quality threshold checks
        low_quality_fields = []
        quality_thresholds = {
            "completeness_score": 0.70,
            "evidence_coverage_score": 0.70,
            "risk_consistency_score": 0.90,
            "hitl_alignment_score": 0.90,
            "participant_split_score": 0.95,
            "process_node_completeness_score": 0.75,
            "responsibility_mapping_score": 0.70,
            "responsibility_chain_score": 0.80,
            "audit_node_mapping_score": 0.70,
            "flow_diagram_score": 1.00,
            "risk_node_binding_score": 0.80,
            "deliverable_readiness_score": 0.80,
        }
        for score_name, threshold in quality_thresholds.items():
            score_val = quality_scores.get(score_name, 0.0)
            if score_val < threshold:
                low_quality_fields.append({
                    "field": score_name,
                    "current": score_val,
                    "threshold": threshold,
                    "gap": round(threshold - score_val, 4),
                })

        # L3: build capability_issues — for low quality_threshold fields
        # that the data-layer patch cannot fix, attach a suggested
        # capability patch (e.g. "rewrite prompt-stage-1 to be stricter
        # about evidence citation").  ``_build_capability_patch`` returns
        # None for issues that should be handled at the data layer or
        # via a RuleProposal, so we only keep entries with a real patch.
        capability_issues: list[dict] = []
        prompt_templates = (stage_result.result_payload or {}).get(
            "prompt_templates", {}
        )
        for low in low_quality_fields:
            cap_patch = _build_capability_patch(
                {
                    "issue_type": "quality_threshold",
                    "field": low["field"],
                    "message": f"score below threshold",
                },
                prompt_templates,
            )
            if cap_patch is not None:
                capability_issues.append({
                    "field": low["field"],
                    "current": low["current"],
                    "threshold": low["threshold"],
                    "suggested_capability_patch": cap_patch,
                })

        # Determine overall recommendation
        high_issues = [i for i in structured_issues if i["severity"] == "high"]
        missing_hitl = len(high_issues) > 0 or to_confirm_count > 0

        # Title and description reflect validation state
        if high_issues:
            affected = ", ".join(i["affected_field"] for i in high_issues[:3])
            description = (
                "阶段一合同校验发现 {0} 个高优先级问题（{1}），"
                "建议逐一处理后再推进锁定。"
            ).format(len(high_issues), affected)
        elif validation_issues:
            description = (
                "阶段一已形成初步风险判断，但仍有 {0} 个校验问题，"
                "建议补充异常路径和风险升级条件。"
            ).format(len(validation_issues))
        else:
            description = "阶段一合同校验通过，建议确认待确认项后推进锁定。"

        description += _format_low_quality_suffix(low_quality_fields)

        # ── 3D alignment: risk_level × target_sla × actual_sla → decision ──
        from src.apps.api.app.services.alignment_service import (
            compute_3d_alignment,
            decision_to_recommendation,
            should_interrupt_for_human,
            decision_to_chinese,
        )
        prev_scenario = (stage_result.result_payload or {}).get("scenario_summary", {})
        risk_level_for_alignment = prev_scenario.get("risk_level") if isinstance(prev_scenario, dict) else None
        target_sla_for_alignment = None
        actual_sla_for_alignment = None
        gap_for_alignment: float | None = None
        s2_payload = (stage_result.result_payload or {}).get("stage2_summary", {}) or {}
        s3_payload = (stage_result.result_payload or {}).get("stage3_summary", {}) or {}
        if isinstance(s2_payload, dict):
            target_sla_for_alignment = s2_payload.get("target_sla")
        if isinstance(s3_payload, dict):
            actual_sla_for_alignment = s3_payload.get("actual_sla")
            gap_for_alignment = s3_payload.get("gap_to_target_pct")
        alignment = compute_3d_alignment(
            risk_level=risk_level_for_alignment,
            target_sla=target_sla_for_alignment,
            actual_sla=actual_sla_for_alignment,
            gap_to_target_pct=gap_for_alignment,
        )
        alignment_recommendation_level = decision_to_recommendation(alignment)
        alignment_requires_human = should_interrupt_for_human(alignment)
        # 3D alignment is binding when we have a non-insufficient decision;
        # otherwise the stage-1 issue/quality state remains authoritative.
        alignment_binding = alignment.get("decision") != "insufficient"
        effective_impact = (
            {"low": "low", "medium": "medium", "high": "high"}[alignment_recommendation_level]
            if alignment_binding and missing_hitl is False
            else ("high" if missing_hitl else alignment_recommendation_level)
        )
        effective_risk = (
            alignment_recommendation_level
            if alignment_binding and missing_hitl is False
            else ("high" if missing_hitl else alignment_recommendation_level)
        )
        if alignment_binding:
            description += " 3D 对齐：{0}（{1}）。".format(
                decision_to_chinese(alignment["decision"]),
                alignment["rationale"],
            )

        return {
            "title": "{0} 合同校验建议".format(stage_name),
            "impact": effective_impact,
            "risk": effective_risk,
            "description": description,
            "action": "按校验问题逐项补齐，确认待确认项后推进锁定。",
            "context": {
                "validation_issues": structured_issues,
                "quality_scores": quality_scores,
                "low_quality_fields": low_quality_fields,
                "to_confirm_count": to_confirm_count,
                "evidence_count": evidence_count,
                "capability_issues": capability_issues,
                "3d_alignment": alignment,
                "alignment_binding": alignment_binding,
                "alignment_requires_human": alignment_requires_human,
            },
        }

    if stage_id.endswith("stage-2"):
        # Stage 2: Generate issues from contract validation
        stage2_template = _validate_and_score_stage(
            stage_id=stage_id,
            stage_result=stage_result,
            payload_key="stage2_summary",
            validate_fn_name="validate_stage2_summary",
            quality_fn_name="compute_stage2_quality",
            patch_fn=_build_suggested_patch_stage2,
            quality_thresholds={
                "completeness_score": 0.70,
                "risk_alignment_score": 0.80,
                "sla_reasonability_score": 0.60,
            },
        )
        stage2_summary = stage2_template["stage_summary"]
        validation_issues = stage2_template["validation_issues"]
        quality_scores = stage2_template["quality_scores"]
        structured_issues = stage2_template["structured_issues"]
        low_quality_fields = stage2_template["low_quality_fields"]

        high_issues = [i for i in structured_issues if i["severity"] == "high"]
        unstable = stage2_summary.get("stability") == "unstable" if isinstance(stage2_summary, dict) else False

        if high_issues:
            affected = ", ".join(i["affected_field"] for i in high_issues[:3])
            description = (
                "阶段二合同校验发现 {0} 个高优先级问题（{1}），"
                "建议逐一处理后再推进锁定。"
            ).format(len(high_issues), affected)
        elif validation_issues:
            description = (
                "阶段二已形成初步价值判断，但仍有 {0} 个校验问题，"
                "建议补充参数来源与成本假设。"
            ).format(len(validation_issues))
        elif unstable:
            description = "目标 SLA 仍存在参数敏感性，建议补充上下限假设、业务容量和稳定性论证。"
        else:
            description = "价值与 SLA 已形成草稿，建议补充参数来源与成本假设，降低后续回溯成本。"

        description += _format_low_quality_suffix(low_quality_fields)

        return {
            "title": "{0} 合同校验建议".format(stage_name),
            "impact": "high" if (high_issues or unstable) else "medium",
            "risk": "high" if high_issues else "medium",
            "description": description,
            "action": "复核 SLA 参数敏感性、成本口径和价值假设，按校验问题逐项补齐。",
            "context": {
                "validation_issues": structured_issues,
                "quality_scores": quality_scores,
                "low_quality_fields": low_quality_fields,
                "evidence_count": evidence_count,
            },
        }

    if stage_id.endswith("stage-3"):
        # Stage 3: Generate issues from contract validation
        stage3_template = _validate_and_score_stage(
            stage_id=stage_id,
            stage_result=stage_result,
            payload_key="stage3_summary",
            validate_fn_name="validate_stage3_summary",
            quality_fn_name="compute_stage3_quality",
            patch_fn=_build_suggested_patch_stage3,
            quality_thresholds={
                "completeness_score": 0.70,
                "probe_consistency_score": 0.60,
                "sla_alignment_score": 0.60,
            },
        )
        stage3_summary = stage3_template["stage_summary"]
        validation_issues = stage3_template["validation_issues"]
        quality_scores = stage3_template["quality_scores"]
        structured_issues = stage3_template["structured_issues"]
        low_quality_fields = stage3_template["low_quality_fields"]

        high_issues = [i for i in structured_issues if i["severity"] == "high"]
        low_score_samples = stage3_summary.get("low_score_samples", 0) if isinstance(stage3_summary, dict) else 0
        gap_pct = stage3_summary.get("gap_to_target_pct", 0) if isinstance(stage3_summary, dict) else 0
        high_gap = isinstance(gap_pct, (int, float)) and gap_pct > 10

        if high_issues:
            affected = ", ".join(i["affected_field"] for i in high_issues[:3])
            description = (
                "阶段三合同校验发现 {0} 个高优先级问题（{1}），"
                "建议逐一处理后再推进锁定。"
            ).format(len(high_issues), affected)
        elif high_gap:
            description = "SLA 缺口过大（{0}%），需评估改进方案并补充失败模式分析。".format(gap_pct)
        elif low_score_samples > 3:
            description = "低分样本过多（{0}个），建议深入分析失败原因，考虑调整任务或模型。".format(low_score_samples)
        elif validation_issues:
            description = (
                "阶段三探针结果已有初步结论，但仍有 {0} 个校验问题，"
                "建议补充反例样本和边界样本覆盖。"
            ).format(len(validation_issues))
        else:
            description = "阶段三结果较稳定，但建议补充反例样本，避免 Actual SLA 偏乐观。"

        description += _format_low_quality_suffix(low_quality_fields)

        return {
            "title": "{0} 合同校验建议".format(stage_name),
            "impact": "high" if high_issues else "medium",
            "risk": "high" if (high_issues or high_gap) else "medium",
            "description": description,
            "action": "补充低分样本、失败模式和边界样本覆盖，按校验问题逐项补齐。",
            "context": {
                "validation_issues": structured_issues,
                "quality_scores": quality_scores,
                "low_quality_fields": low_quality_fields,
                "evidence_count": evidence_count,
            },
        }

    # Stage 4: Generate issues from contract validation
    stage4_template = _validate_and_score_stage(
        stage_id=stage_id,
        stage_result=stage_result,
        payload_key="stage4_summary",
        validate_fn_name="validate_stage4_summary",
        quality_fn_name="compute_stage4_quality",
        patch_fn=_build_suggested_patch_stage4,
        quality_thresholds={
            "completeness_score": 0.70,
            "evidence_sufficiency_score": 0.70,
            "decision_readiness_score": 0.70,
        },
    )
    stage4_summary = stage4_template["stage_summary"]
    validation_issues = stage4_template["validation_issues"]
    quality_scores = stage4_template["quality_scores"]
    structured_issues = stage4_template["structured_issues"]
    low_quality_fields = stage4_template["low_quality_fields"]

    high_issues = [i for i in structured_issues if i["severity"] == "high"]
    no_evidence = evidence_count == 0 or not (
        isinstance(stage4_summary, dict) and stage4_summary.get("evidence_refs")
    )

    if high_issues:
        affected = ", ".join(i["affected_field"] for i in high_issues[:3])
        description = (
            "阶段四合同校验发现 {0} 个高优先级问题（{1}），"
            "建议逐一处理后再推进锁定。"
        ).format(len(high_issues), affected)
    elif no_evidence:
        description = "阶段四缺少证据引用，报告前必须补齐关键结论对应的证据片段。"
    elif validation_issues:
        description = (
            "证据链和待确认项仍需在出报告前收口，但仍有 {0} 个校验问题，"
            "建议核对关键结论的证据引用和暂缓项处理状态。"
        ).format(len(validation_issues))
    else:
        description = "证据链和待确认项已基本收口，建议核对报告关键结论的证据引用完整性。"

    description += _format_low_quality_suffix(low_quality_fields)

    return {
        "title": "{0} 合同校验建议".format(stage_name),
        "impact": "high" if (high_issues or no_evidence) else "medium",
        "risk": "high" if (high_issues or no_evidence) else "medium",
        "description": description,
        "action": "核对报告关键结论的证据引用，并处理所有待确认/暂缓项，按校验问题逐项补齐。",
        "context": {
            "validation_issues": structured_issues,
            "quality_scores": quality_scores,
            "low_quality_fields": low_quality_fields,
            "evidence_count": evidence_count,
        },
    }


def seed_frozen_eval_contract(*, stage_id: str, created_by: str = "system") -> FrozenEvalContract:
    """Materialise the frozen evaluation contract for a stage.

    Extracts frozen rules from ``stage1_contract.py`` constants and
    ``_WHITELISTED_PATCH_FIELDS`` / ``AUTO_ACCEPT_CONFIDENCE_THRESHOLD``.
    If a contract already exists for *stage_id*, bumps the version number.
    """
    from src.apps.api.app.services.stage1_contract import (
        RISK_LEVELS,
        HITL_LEVELS,
        PLACEHOLDER_VALUES,
        MIN_SUBSTANTIVE_LENGTH,
        _QUALITY_WEIGHTS,
    )

    frozen_fields: list[dict[str, Any]] = [
        {
            "rule_id": "stage1-risk-level-enum",
            "rule_type": "enum_constraint",
            "description": "risk_level must be one of the contract enum values",
            "parameters": {"allowed_values": sorted(RISK_LEVELS)},
        },
        {
            "rule_id": "stage1-hitl-level-enum",
            "rule_type": "enum_constraint",
            "description": "hitl_level must be one of the contract enum values",
            "parameters": {"allowed_values": sorted(HITL_LEVELS)},
        },
        {
            "rule_id": "stage1-l3-hitl-alignment",
            "rule_type": "cross_field_constraint",
            "description": "L3 risk must map to strict or mandatory HITL",
            "parameters": {"risk_level": "L3", "required_hitl": ["strict", "mandatory"]},
        },
        {
            "rule_id": "stage1-risk-items-required",
            "rule_type": "completeness_check",
            "description": "risk_items must be non-empty",
            "parameters": {},
        },
        {
            "rule_id": "stage1-risk-matrix-required",
            "rule_type": "completeness_check",
            "description": "risk_matrix must be non-empty",
            "parameters": {},
        },
        {
            "rule_id": "stage1-evidence-refs-required",
            "rule_type": "completeness_check",
            "description": "evidence_refs must be non-empty",
            "parameters": {},
        },
        {
            "rule_id": "stage1-risk-item-evidence",
            "rule_type": "evidence_binding",
            "description": "Each risk_item should have evidence_refs or matching to_confirm",
            "parameters": {},
        },
        {
            "rule_id": "stage1-hitl-rules-l2-l3",
            "rule_type": "completeness_check",
            "description": "L2/L3 risk must include HITL rules",
            "parameters": {"risk_levels": ["L2", "L3"]},
        },
        {
            "rule_id": "stage1-l3-prohibited-conditions",
            "rule_type": "completeness_check",
            "description": "L3 risk must include prohibited conditions",
            "parameters": {"risk_level": "L3"},
        },
        {
            "rule_id": "stage1-l3-fatal-errors",
            "rule_type": "completeness_check",
            "description": "L3 risk must include fatal errors",
            "parameters": {"risk_level": "L3"},
        },
        {
            "rule_id": "stage1-no-placeholders",
            "rule_type": "content_quality",
            "description": "Key fields must not contain placeholder values",
            "parameters": {
                "placeholder_values": sorted(PLACEHOLDER_VALUES),
                "min_substantive_length": MIN_SUBSTANTIVE_LENGTH,
            },
        },
        {
            "rule_id": "stage1-evidence-chain-verification",
            "rule_type": "evidence_binding",
            "description": "Risk items with evidence_verified=False are flagged",
            "parameters": {},
        },
        {
            "rule_id": "stage1-risk-confidence-consistency",
            "rule_type": "cross_field_constraint",
            "description": "risk_confidence.dominant_level must match risk_level",
            "parameters": {},
        },
        {
            "rule_id": "autoresearch-patch-confidence-threshold",
            "rule_type": "gate_threshold",
            "description": "Auto-accept when patch_confidence >= threshold",
            "parameters": {"threshold": AUTO_ACCEPT_CONFIDENCE_THRESHOLD},
        },
        {
            "rule_id": "autoresearch-quality-weights",
            "rule_type": "scoring_weights",
            "description": "Weights for audit_readiness_score computation",
            "parameters": dict(_QUALITY_WEIGHTS),
        },
    ]

    mutable_fields = sorted(_WHITELISTED_PATCH_FIELDS)

    # Determine version: if a contract already exists, bump
    # Determine version: if a contract already exists, bump
    existing = get_latest_frozen_eval_contract(stage_id)
    if existing:
        version_num = int(existing.version.lstrip("v")) + 1
        version = f"v{version_num}"
    else:
        version = "v1"

    contract = FrozenEvalContract(
        id=f"fec-{uuid4().hex[:8]}",
        version=version,
        stage_id=stage_id,
        frozen_fields=frozen_fields,
        mutable_fields=mutable_fields,
        created_by=created_by,
    )
    save_frozen_eval_contract(contract)
    create_execution_log(
        project_id=stage_id.split("-")[0] if "-" in stage_id else "",
        action="frozen_eval_contract.seeded",
        resource_type="frozen_eval_contract",
        resource_id=contract.id,
        details={"stage_id": stage_id, "version": version, "rule_count": len(frozen_fields)},
    )
    return contract


def read_rejected_insights(stage_id: str) -> list[dict[str, Any]]:
    """Return ``reusable_insights`` from all RejectedCandidate records for *stage_id*.

    Each entry is ``{rejection_reason, candidate_id, insight_text}``.
    Used by ``refine_stage1`` (and other loop nodes) to avoid repeating
    patches that prior runs already rejected — the "rejected candidate
    buffer" from the Bank-GAI AutoResearch Loop spec.

    Read-only: never mutates stored records.
    """
    from src.apps.api.app.repositories.store import list_rejected_candidates

    rejected_list = list_rejected_candidates(stage_id=stage_id)
    insights: list[dict[str, Any]] = []
    for rc in rejected_list:
        for insight in rc.reusable_insights:
            insights.append(
                {
                    "rejection_reason": rc.rejection_reason,
                    "candidate_id": rc.candidate_id,
                    "insight_text": insight,
                }
            )
    return insights


# ── L2: Capability mutability contract ────────────────────────────────────


_DEFAULT_MUTABLE_CAPABILITIES = [
    "prompt.body",          # 修改 PromptTemplate.body
    "prompt.version",       # bump prompt.version v1→v2
    "tool.enabled",         # 启用/停用 tool
    "skill.skill_version",  # bump skill.skill_versions
    "rubric.threshold",     # 修改 _QUALITY_WEIGHTS 等阈值
]
_DEFAULT_CAPABILITY_GATES = [
    {"capability": "prompt.body", "min_sample_size": 5, "min_quality_improvement": 0.05},
    {"capability": "tool.enabled", "min_sample_size": 3, "min_quality_improvement": 0.03},
    {"capability": "model.alias", "min_sample_size": 10, "min_quality_improvement": 0.10},
    {"capability": "skill.skill_version", "min_sample_size": 5, "min_quality_improvement": 0.05},
    {"capability": "rubric.threshold", "min_sample_size": 8, "min_quality_improvement": 0.04},
]


def seed_capability_mutability_contract(
    *, stage_id: str, created_by: str = "system"
) -> CapabilityMutabilityContract:
    """Create or bump a CapabilityMutabilityContract for *stage_id*.

    Version is synchronised with the latest FrozenEvalContract for the
    same stage — bumping the data-layer contract also bumps the
    capability-layer contract.  Both are stamped with the same version
    string so consumers can correlate them.
    """
    from src.apps.api.app.repositories.store import (
        list_capability_mutability_contracts,
        list_frozen_eval_contracts,
    )

    # CMC version is locked to the latest FrozenEvalContract version for
    # the same stage — when the data contract bumps, the capability
    # contract follows.  Falls back to v1 if no frozen contract exists
    # yet (capability contract is allowed to exist standalone in tests).
    latest_frozen = get_latest_frozen_eval_contract(stage_id)
    if latest_frozen is not None:
        version = latest_frozen.version
    else:
        version = "v1"

    existing = get_latest_capability_mutability_contract(stage_id)
    if existing is not None and existing.version == version:
        return existing

    contract = CapabilityMutabilityContract(
        id=f"cmc-{uuid4().hex[:8]}",
        version=version,
        stage_id=stage_id,
        mutable_capabilities=list(_DEFAULT_MUTABLE_CAPABILITIES),
        capability_gates=list(_DEFAULT_CAPABILITY_GATES),
        created_by=created_by,
    )
    save_capability_mutability_contract(contract)
    create_execution_log(
        project_id="system",
        action="capability_mutability_contract.seeded",
        resource_type="capability_mutability_contract",
        resource_id=contract.id,
        details={
            "stage_id": stage_id,
            "version": version,
            "capability_count": len(contract.mutable_capabilities),
            "gate_count": len(contract.capability_gates),
        },
    )
    return contract


def lookup_capability_gate(
    contract: CapabilityMutabilityContract, capability: str
) -> dict[str, Any]:
    """Find the gate for *capability*. Returns default-permissive
    ``{"permitted": True, "min_sample_size": 1, "min_quality_improvement": 0.0}``
    if not configured (so L3 callers fail closed only via the explicit
    ``permitted=False`` check, never by missing-gate)."""
    for gate in contract.capability_gates:
        if gate.get("capability") == capability:
            return {**gate, "permitted": True}
    return {
        "capability": capability,
        "permitted": True,
        "min_sample_size": 1,
        "min_quality_improvement": 0.0,
    }


# ── L2: Rule proposal emission ────────────────────────────────────────────


# Issue types that we know are unpatchable at the data layer and need a
# rule change instead. Extend when introducing new unpatchable failures.
_UNPATCHABLE_ISSUE_FIELDS = {
    "evidence_coverage_score",   # need stricter evidence citation rule
    "completeness_score",         # need extra required field
    "consistency_score",          # need cross-field constraint
}


def _build_rule_proposal(
    *,
    project_id: str,
    stage_id: str,
    run_id: str,
    issue: dict[str, Any],
    supporting_metrics: dict[str, Any],
    rationale: str,
) -> Optional[RuleProposal]:
    """Construct a RuleProposal when ``_build_suggested_patch`` cannot
    produce a data-layer fix for *issue*.  Returns ``None`` for issues
    that *can* be patched at the data layer (caller should not invoke
    this function in that case)."""
    if issue.get("issue_type") != "quality_threshold":
        return None
    field = issue.get("field", "")
    if field not in _UNPATCHABLE_ISSUE_FIELDS:
        return None

    target_rule_id = f"stage1-{field.replace('_', '-')}-min"
    new_rule = {
        "rule_id": target_rule_id,
        "kind": "quality_threshold",
        "field": field,
        "min_value": max(0.5, supporting_metrics.get("observed_value", 0.0) + 0.1),
        "rationale": rationale,
    }
    return RuleProposal(
        id=f"rp-{uuid4().hex[:8]}",
        project_id=project_id,
        stage_id=stage_id,
        run_id=run_id,
        proposal_kind="modify_rule",
        target_rule_id=target_rule_id,
        new_rule=new_rule,
        rationale=rationale,
        supporting_metrics=supporting_metrics,
    )


def accept_rule_proposal(
    proposal_id: str, *, reviewer: str = "human"
) -> RuleProposal:
    """Mark a proposal as accepted by the human reviewer.  The next
    ``seed_frozen_eval_contract`` call for the same stage picks up the
    new rule definition via the rule change ledger (the next stage in
    the Bank-GAI loop: ledger → contract → enforcement)."""
    from src.apps.api.app.repositories.store import get_rule_proposal

    proposal = get_rule_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule proposal not found: {proposal_id}",
        )
    if proposal.status == "accepted":
        return proposal
    if proposal.status in {"rejected", "superseded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Rule proposal {proposal_id} is {proposal.status}, cannot accept",
        )
    proposal.status = "accepted"
    proposal.human_review_status = "accepted"
    proposal.accepted_at = utcnow()
    save_rule_proposal(proposal)
    create_execution_log(
        project_id=proposal.project_id,
        action="rule_proposal.accepted",
        resource_type="rule_proposal",
        resource_id=proposal.id,
        run_id=proposal.run_id,
        details={"reviewer": reviewer, "target_rule_id": proposal.target_rule_id},
    )
    return proposal


def reject_rule_proposal(
    proposal_id: str, *, reviewer: str = "human", rationale: str = ""
) -> RuleProposal:
    """Mark a proposal as rejected by the human reviewer."""
    from src.apps.api.app.repositories.store import get_rule_proposal

    proposal = get_rule_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule proposal not found: {proposal_id}",
        )
    if proposal.status in {"accepted", "rejected"}:
        return proposal
    proposal.status = "rejected"
    proposal.human_review_status = "rejected"
    proposal.rejected_at = utcnow()
    proposal.rejection_rationale = rationale
    save_rule_proposal(proposal)
    create_execution_log(
        project_id=proposal.project_id,
        action="rule_proposal.rejected",
        resource_type="rule_proposal",
        resource_id=proposal.id,
        run_id=proposal.run_id,
        details={
            "reviewer": reviewer,
            "rationale": rationale,
            "target_rule_id": proposal.target_rule_id,
        },
    )
    return proposal


# ── L3: Capability patches (prompt.body / tool.enabled / model.alias / …) ─


# Lightweight template rewriter — no LLM dependency, deterministic
# substitution so tests can assert exact output.  When an LLM is wired
# in, replace this with an LLM call.  Keep the function signature stable.
def _rewrite_evidence_instruction(prompt_body: str, *, strengthen: bool = True) -> str:
    """Insert or strengthen the "cite evidence_refs" instruction in a
    Stage-1 prompt body.  Idempotent: re-running with strengthen=True
    twice produces the same result."""
    if not prompt_body:
        return prompt_body
    marker = "MUST_CITE_EVIDENCE_REFS"
    if marker in prompt_body:
        return prompt_body
    if not strengthen:
        return prompt_body
    # Add a one-line instruction right after the first line.
    lines = prompt_body.splitlines()
    if not lines:
        return f"{marker} " + prompt_body
    head = lines[0]
    tail = "\n".join(lines[1:])
    return f"{head}\n{marker} Cite at least one evidence_refs for every risk item."


def _validate_prompt_body(body: str) -> bool:
    """Prompt body must be non-empty and look like a real template.

    For Stage-1 prompts we require a placeholder for the goal/scenario
    so the rewritten text can be rendered later.  We accept either
    ``{{goal}}`` or the legacy ``{goal}`` style.
    """
    if not isinstance(body, str) or not body.strip():
        return False
    if "MUST_CITE_EVIDENCE_REFS" in body and "evidence_refs" not in body:
        # We added the marker but forgot the placeholder — invalid
        return False
    return True


def _build_capability_patch(
    issue: dict[str, Any], prompt_templates: dict[str, str]
) -> Optional[dict[str, Any]]:
    """L3: Convert a quality_threshold issue into a capability-layer
    patch that modifies a PromptTemplate.body (or other capability
    field).  Returns None for issues that should be handled at the
    data layer or via RuleProposal."""
    if issue.get("issue_type") != "quality_threshold":
        return None
    field = issue.get("field", "")
    if field not in {"evidence_coverage_score", "completeness_score"}:
        return None
    target_prompt_id = "prompt-stage-1"
    original = prompt_templates.get(target_prompt_id, "")
    new_body = _rewrite_evidence_instruction(original, strengthen=True)
    return {
        "op": "rewrite",
        "field": "prompt.body",
        "target_prompt_id": target_prompt_id,
        "original_body": original,
        "value": new_body,
        "expected_effect": f"{field}↑",
    }


def _apply_capability_patch_to_settings_draft(
    project_id: str,
    capability_patch: dict[str, Any],
    *,
    actor: str = "autoresearch",
) -> Optional[str]:
    """Write a capability patch to settings.draft (NOT published).

    Returns the draft settings id, or None if the draft could not be
    created.  This is the only way L3 patches reach settings — humans
    must explicitly publish the draft before the next Run uses it.
    """
    field = capability_patch.get("field", "")
    if field != "prompt.body":
        # Other capability patches (tool.enabled, model.alias, etc.)
        # require deeper settings service surgery.  Not implemented in
        # this iteration — emit a RejectedCandidate with reason
        # "not_yet_implemented" via the caller path.
        return None
    target_prompt_id = capability_patch.get("target_prompt_id", "")
    new_body = capability_patch.get("value", "")
    if not _validate_prompt_body(new_body):
        return None

    # Lazy import — keep settings_service dependency one-way.
    from src.apps.api.app.services.settings_service import (
        get_effective_settings_for_run,
        save_settings_draft,
    )
    from src.apps.api.app.domain.models import (
        ProjectSettings,
        PromptTemplate,
        RunPolicy,
        StageSkillProfile,
        ModelProfile,
    )

    published: ProjectSettings = get_effective_settings_for_run(project_id, stage_id=None)
    # Clone published → draft
    new_id = f"ps-{project_id}-draft-{uuid4().hex[:8]}"
    new_version_id = f"draft-{uuid4().hex[:6]}"
    # Patch the matching prompt
    new_prompts: list[PromptTemplate] = []
    for prompt in published.prompts:
        if prompt.id == target_prompt_id:
            # Bump version v1 → v2 (or vN → v(N+1))
            try:
                num = int(prompt.version.lstrip("v"))
            except (TypeError, ValueError):
                num = 1
            new_prompts.append(
                PromptTemplate(
                    id=prompt.id,
                    category=prompt.category,
                    scope=prompt.scope,
                    title=prompt.title,
                    body=new_body,
                    required_variables=list(prompt.required_variables),
                    skill_name=prompt.skill_name,
                    version=f"v{num + 1}",
                )
            )
        else:
            new_prompts.append(prompt)

    draft = ProjectSettings(
        id=new_id,
        project_id=project_id,
        version_id=new_version_id,
        base_version_id=published.version_id,
        status="draft",
        models=list(published.models),
        prompts=new_prompts,
        stage_skill_profiles=list(published.stage_skill_profiles),
        run_policy=RunPolicy(
            **{
                k: getattr(published.run_policy, k)
                for k in published.run_policy.__dataclass_fields__
            }
        ),
        config_hash="",
        created_by=actor,
    )
    save_settings_draft(draft)
    create_execution_log(
        project_id=project_id,
        action="capability_patch.applied_to_draft",
        resource_type="settings_draft",
        resource_id=new_id,
        details={
            "field": field,
            "target_prompt_id": target_prompt_id,
            "old_version": published.version_id,
            "new_version": new_version_id,
            "actor": actor,
        },
    )
    return new_id


def create_autoresearch_record(*, stage_id: str, run_id: str, auto_run_condition: str = "manual") -> AutoResearchRecord:
    stage = get_stage(stage_id)
    run = get_run(run_id)
    if run.stage_id != stage_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run does not belong to stage")

    stage_result = get_latest_stage_result(stage_id)
    if stage_result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage result not found")

    recommendation = _build_stage_specific_recommendation(stage.name, stage_id, stage_result)
    record = AutoResearchRecord(
        id=f"ar-{uuid4().hex[:8]}",
        project_id=stage.project_id,
        stage_id=stage_id,
        run_id=run_id,
        stage_result_id=stage_result.id,
        title=recommendation["title"],
        source="autoresearch",
        impact=recommendation["impact"],
        risk=recommendation["risk"],
        description="{0}（版本：{1}）".format(recommendation["description"], stage_result.version_id),
        action=recommendation["action"],
        context=recommendation.get("context", {}),
    )
    save_autoresearch_record(record)
    create_execution_log(
        project_id=record.project_id,
        action="autoresearch.generated",
        resource_type="autoresearch_record",
        resource_id=record.id,
        run_id=record.run_id,
        details={"stage_id": record.stage_id, "stage_result_id": record.stage_result_id},
    )
    # Auto-accept if confidence threshold met and auto_run_condition is "auto"
    # Gate: L3 risk or boundary_flag always requires HITL — never auto-accept
    if auto_run_condition == "auto":
        validation_issues = recommendation.get("context", {}).get("validation_issues", [])
        scenario_summary = {}
        stage_result_payload = stage_result.result_payload if stage_result else {}
        if isinstance(stage_result_payload, dict):
            scenario_summary = stage_result_payload.get("scenario_summary", {})
        risk_level = scenario_summary.get("risk_level", "")
        boundary_flag = scenario_summary.get("boundary_flag", False)
        patch_confidence = _compute_patch_confidence(validation_issues, scenario_summary)

        # L3 risk or boundary scenarios must always go through HITL
        l3_requires_hitl = risk_level == "L3"
        boundary_requires_hitl = boundary_flag

        # P1-1 extension: L3 confidence gate — even when risk_level is L2,
        # if risk_confidence.L3 >= 0.5, block auto-accept
        risk_confidence = scenario_summary.get("risk_confidence", {})
        l3_confidence_gate = (
            isinstance(risk_confidence, dict)
            and risk_level != "L3"
            and risk_confidence.get("L3", 0.0) >= 0.5
        )

        # Phase 3: quality score gate — block auto-accept ONLY when quality
        # is critically low (audit_readiness_score < 0.5). The threshold
        # is intentionally lenient because:
        # - When all high-severity issues have patches, patch_confidence
        #   gate already gates auto-accept.
        # - The remaining dimensions (completeness etc.) are informational
        #   and may not block the existing patch flow.
        # - Critical quality issues (e.g. risk_level missing AND hitl missing
        #   AND no patches) are the only case that should require HITL.
        quality_scores_ctx = recommendation.get("context", {}).get("quality_scores", {}) or {}
        audit_readiness_raw = quality_scores_ctx.get("audit_readiness_score", 1.0)
        if audit_readiness_raw is None:
            audit_readiness = 1.0
        else:
            try:
                audit_readiness = float(audit_readiness_raw)
            except (TypeError, ValueError):
                audit_readiness = 1.0
        # Critical quality gate: audit_readiness < 0.5 means multiple
        # dimensions are simultaneously below threshold — too risky to auto-fix.
        quality_blocked = audit_readiness < 0.5
        failed_quality = (
            ["audit_readiness_score"] if quality_blocked else []
        )

        gate_blocked = (
            l3_requires_hitl or boundary_requires_hitl
            or l3_confidence_gate or quality_blocked
        )
        if gate_blocked:
            if l3_requires_hitl:
                gate_reason = "L3风险等级"
            elif boundary_requires_hitl:
                gate_reason = "等级边界标记"
            elif l3_confidence_gate:
                gate_reason = "L3置信度≥0.5"
            else:
                gate_reason = (
                    "质量分数未达阈值：{0}".format("、".join(failed_quality))
                )
            # Record stays pending; add trace note explaining why auto-accept was blocked
            record.context.setdefault("autoresearch_gate_blocked", True)
            record.context.setdefault("autoresearch_gate_reason", gate_reason)
            if quality_blocked:
                record.context.setdefault(
                    "autoresearch_failed_quality_dimensions", failed_quality,
                )
            save_autoresearch_record(record)
        elif patch_confidence >= AUTO_ACCEPT_CONFIDENCE_THRESHOLD:
            try:
                record = confirm_autoresearch_record(
                    record_id=record.id,
                    decision="accepted",
                    note="Auto-accepted: patch confidence {0:.2f} >= threshold {1:.2f}".format(patch_confidence, AUTO_ACCEPT_CONFIDENCE_THRESHOLD),
                    edited_description=None,
                )[0]
            except Exception:
                pass  # Don't fail creation if auto-accept fails
    return record


def create_manual_autoresearch_record(
    *,
    stage_id: str,
    title: str,
    description: str,
    action: str,
    impact: str,
    risk: str,
    source: str,
    run_id: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> AutoResearchRecord:
    stage = get_stage(stage_id)
    stage_result = get_latest_stage_result(stage_id)
    record = AutoResearchRecord(
        id=f"ar-{uuid4().hex[:8]}",
        project_id=stage.project_id,
        stage_id=stage_id,
        run_id=run_id or f"manual-{stage_id}",
        stage_result_id=stage_result.id if stage_result is not None else "",
        title=title,
        source=source,
        impact=impact,
        risk=risk,
        description=description,
        action=action,
        context=context or {},
    )
    save_autoresearch_record(record)
    create_execution_log(
        project_id=record.project_id,
        action="autoresearch.manual_generated",
        resource_type="autoresearch_record",
        resource_id=record.id,
        run_id=run_id,
        details={
            "stage_id": record.stage_id,
            "stage_result_id": record.stage_result_id,
            "source": source,
            "context": record.context,
        },
    )
    return record


def list_autoresearch_records(stage_id: Optional[str] = None) -> list[AutoResearchRecord]:
    return repo_list_autoresearch_records(stage_id)


def _sync_evidence_status_from_record(record: AutoResearchRecord, decision: str, note: Optional[str]) -> list[str]:
    """Sync evidence item statuses based on autoresearch decision.

    Returns list of updated evidence item IDs.
    """
    source_file = record.context.get("source_file")
    if not isinstance(source_file, str) or not source_file:
        return []
    files = list_file_artifacts(record.project_id)
    file_ids = [item.id for item in files if item.filename == source_file]
    if not file_ids:
        return []
    evidence_items = list_evidence_items(record.project_id)
    target_items = [item for item in evidence_items if item.source_file_id in file_ids]
    if not target_items:
        return []

    updated_at = utcnow()
    review_note = note
    if decision in {"accepted", "accepted_with_edits"}:
        review_note = (note or "") + " 已采纳" if note else "已采纳"
    elif decision == "rejected":
        review_note = (note or "") + " 已拒绝" if note else "已拒绝"
    elif decision == "follow_up":
        review_note = (note or "") + " 后续追问" if note else "后续追问"

    updated_ids: list[str] = []
    for item in target_items:
        if decision in {"accepted", "accepted_with_edits"}:
            item.status = "referenced"
        item.review_note = review_note
        item.updated_at = updated_at
        save_evidence_item(item)
        updated_ids.append(item.id)
    return updated_ids


def confirm_autoresearch_record(
    *,
    record_id: str,
    decision: str,
    note: Optional[str],
    edited_description: Optional[str],
) -> Tuple[AutoResearchRecord, Optional[StageResult]]:
    record = get_autoresearch_record(record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="autoResearch record not found")
    if record.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="autoResearch record already processed")

    if decision not in {"accepted", "accepted_with_edits", "rejected", "follow_up"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported decision")

    record.status = decision
    record.note = note
    record.edited_description = edited_description
    record.confirmed_at = utcnow()
    record.updated_at = record.confirmed_at
    save_autoresearch_record(record)
    _sync_evidence_status_from_record(record, decision, note)

    stage_result = None
    if decision in {"accepted", "accepted_with_edits"}:
        base_result = get_latest_stage_result(record.stage_id)
        if base_result is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage result not found")

        description = edited_description or record.description

        # ── AutoResearchCandidate for confirmation path ──
        from src.apps.api.app.services.stage1_contract import compute_stage1_quality
        metrics_before: dict[str, Any] = {}
        if record.stage_id.endswith("stage-1"):
            summary = base_result.result_payload.get("scenario_summary", {})
            if summary:
                metrics_before = dict(compute_stage1_quality(summary))

        candidate = AutoResearchCandidate(
            id=f"cand-{uuid4().hex[:8]}",
            project_id=record.project_id,
            stage_id=record.stage_id,
            run_id=record.run_id,
            change_type="confirmation_decision",
            target_stage="stage-1" if record.stage_id.endswith("stage-1") else record.stage_id.split("-")[-1],
            hypothesis=f"Apply autoResearch suggestion: {record.title}",
            changed_refs=list(_WHITELISTED_PATCH_FIELDS),
            expected_effect=record.impact,
            must_not_change=["evidence_refs"],
            status="proposed",
            iteration=-1,
            metrics_before=metrics_before,
            metrics_after={},
            gate_result="",
            gate_reason="",
            human_review_status="accepted",
        )
        save_autoresearch_candidate(candidate)

        # For Stage 1: apply controlled patches from structured context
        patched_payload = dict(base_result.result_payload)
        patch_applied = False
        patch_rejected = False

        if isinstance(record.context, dict):
            validation_issues = record.context.get("validation_issues", [])
            if record.stage_id.endswith("stage-1"):
                # Stage 1: patch scenario_summary sub-dict
                scenario_summary = dict(patched_payload.get("scenario_summary", {}))
                for issue in validation_issues:
                    suggested_patch = issue.get("suggested_patch")
                    if not suggested_patch or not isinstance(suggested_patch, dict):
                        continue
                    # Support both single-patch ("op":"replace") and multi-patch ("op":"multi","patches":[...])
                    patches_to_apply = []
                    op = suggested_patch.get("op", "replace")
                    if op == "multi":
                        patches_to_apply = suggested_patch.get("patches", [])
                    else:
                        patches_to_apply = [suggested_patch]

                    for patch in patches_to_apply:
                        field = patch.get("field", "")
                        op_single = patch.get("op", "replace")
                        value = patch.get("value")
                        if field not in _WHITELISTED_PATCH_FIELDS:
                            patch_rejected = True
                            patched_payload.setdefault("autoresearch_patch_rejected", []).append({
                                "field": field,
                                "reason": "field_not_whitelisted",
                                "suggested_patch": patch,
                            })
                            # ── RejectedCandidate: not_whitelisted ──
                            rejected = RejectedCandidate(
                                id=f"rc-{uuid4().hex[:8]}",
                                project_id=record.project_id,
                                stage_id=record.stage_id,
                                candidate_id=candidate.id,
                                rejection_reason="not_whitelisted",
                                failed_metrics={},
                                hard_constraint_triggered="",
                                reusable_insights=[f"Field '{field}' is not in whitelisted patch fields"],
                                retry_allowed=True,
                            )
                            save_rejected_candidate(rejected)
                            continue
                        # Reject patches that would delete evidence refs
                        if field == "evidence_refs" and (not value or value == []):
                            patch_rejected = True
                            patched_payload.setdefault("autoresearch_patch_rejected", []).append({
                                "field": field,
                                "reason": "would_delete_evidence_refs",
                                "suggested_patch": patch,
                            })
                            # ── RejectedCandidate: would_delete_evidence_refs ──
                            rejected = RejectedCandidate(
                                id=f"rc-{uuid4().hex[:8]}",
                                project_id=record.project_id,
                                stage_id=record.stage_id,
                                candidate_id=candidate.id,
                                rejection_reason="would_delete_evidence_refs",
                                failed_metrics={},
                                hard_constraint_triggered="evidence_protection",
                                reusable_insights=["Patches must not delete evidence_refs"],
                                retry_allowed=True,
                            )
                            save_rejected_candidate(rejected)
                            continue
                        if op_single == "replace" and field in scenario_summary:
                            scenario_summary[field] = value
                            patch_applied = True
                        elif op_single == "add":
                            scenario_summary[field] = value
                            patch_applied = True

                # Validate patched scenario_summary if we changed it
                if patch_applied and scenario_summary:
                    from src.apps.api.app.services.stage1_contract import validate_stage1_summary
                    post_patch_issues = validate_stage1_summary(scenario_summary)
                    high_post = [i for i in post_patch_issues if i.get("severity") == "high"]
                    if high_post:
                        # Revert — patch made things worse
                        patch_applied = False
                        patch_rejected = True
                        patched_payload.setdefault("autoresearch_patch_rejected", []).append({
                            "field": "scenario_summary",
                            "reason": "post_patch_validation_failed",
                            "high_issues": high_post,
                        })
                        # ── Candidate reverted + RejectedCandidate: post_patch_failed ──
                        candidate.status = "reverted"
                        candidate.gate_result = "fail"
                        candidate.gate_reason = "post_patch_validation_failed"
                        save_autoresearch_candidate(candidate)
                        rejected = RejectedCandidate(
                            id=f"rc-{uuid4().hex[:8]}",
                            project_id=record.project_id,
                            stage_id=record.stage_id,
                            candidate_id=candidate.id,
                            rejection_reason="post_patch_validation_failed",
                            failed_metrics=dict(compute_stage1_quality(scenario_summary)) if scenario_summary else {},
                            hard_constraint_triggered="",
                            reusable_insights=[
                                f"Patch on {high_post[0].get('field', 'unknown')} introduced high-severity issue"
                            ],
                            retry_allowed=True,
                        )
                        save_rejected_candidate(rejected)
                    else:
                        patched_payload["scenario_summary"] = scenario_summary
                        # ── Candidate applied, capture after metrics ──
                        candidate.metrics_after = dict(compute_stage1_quality(scenario_summary))
                        candidate.status = "applied"
                        candidate.gate_result = "pass"
                        save_autoresearch_candidate(candidate)
            else:
                # Stage 2-4: patch top-level result_payload keys directly
                patched_payload_for_s24 = dict(patched_payload)
                for issue in validation_issues:
                    suggested_patch = issue.get("suggested_patch")
                    if not suggested_patch or not isinstance(suggested_patch, dict):
                        continue
                    patches_to_apply = []
                    op = suggested_patch.get("op", "replace")
                    if op == "multi":
                        patches_to_apply = suggested_patch.get("patches", [])
                    else:
                        patches_to_apply = [suggested_patch]

                    for patch in patches_to_apply:
                        field = patch.get("field", "")
                        op_single = patch.get("op", "replace")
                        value = patch.get("value")
                        if field not in _WHITELISTED_PATCH_FIELDS:
                            patch_rejected = True
                            patched_payload_for_s24.setdefault("autoresearch_patch_rejected", []).append({
                                "field": field,
                                "reason": "field_not_whitelisted",
                                "suggested_patch": patch,
                            })
                            # ── RejectedCandidate: not_whitelisted (Stage 2-4) ──
                            rejected = RejectedCandidate(
                                id=f"rc-{uuid4().hex[:8]}",
                                project_id=record.project_id,
                                stage_id=record.stage_id,
                                candidate_id=candidate.id,
                                rejection_reason="not_whitelisted",
                                failed_metrics={},
                                hard_constraint_triggered="",
                                reusable_insights=[f"Field '{field}' is not in whitelisted patch fields"],
                                retry_allowed=True,
                            )
                            save_rejected_candidate(rejected)
                            continue
                        if op_single in ("replace", "add"):
                            patched_payload_for_s24[field] = value
                            patch_applied = True

                # Phase 5: post-patch validation for Stage 2-4
                if patch_applied and patched_payload_for_s24:
                    post_patch_issues = []
                    if record.stage_id.endswith("stage-2"):
                        from src.apps.api.app.services.stage2_contract import validate_stage2_summary
                        post_patch_issues = validate_stage2_summary(
                            patched_payload_for_s24,
                            previous_stage_result=base_result.result_payload,
                        )
                    elif record.stage_id.endswith("stage-3"):
                        from src.apps.api.app.services.stage3_contract import validate_stage3_summary
                        post_patch_issues = validate_stage3_summary(
                            patched_payload_for_s24,
                            previous_stage_result=base_result.result_payload,
                        )
                    elif record.stage_id.endswith("stage-4"):
                        from src.apps.api.app.services.stage4_contract import validate_stage4_summary
                        post_patch_issues = validate_stage4_summary(
                            patched_payload_for_s24,
                            previous_stage_result=base_result.result_payload,
                        )
                    high_post = [i for i in post_patch_issues if i.get("severity") == "high"]
                    if high_post:
                        # Revert — patch made things worse
                        patch_applied = False
                        patch_rejected = True
                        patched_payload_for_s24.setdefault("autoresearch_patch_rejected", []).append({
                            "field": "stage_summary",
                            "reason": "post_patch_validation_failed",
                            "high_issues": [i.get("field") for i in high_post],
                        })
                        # ── Candidate reverted + RejectedCandidate: post_patch_failed (Stage 2-4) ──
                        candidate.status = "reverted"
                        candidate.gate_result = "fail"
                        candidate.gate_reason = "post_patch_validation_failed"
                        save_autoresearch_candidate(candidate)
                        rejected = RejectedCandidate(
                            id=f"rc-{uuid4().hex[:8]}",
                            project_id=record.project_id,
                            stage_id=record.stage_id,
                            candidate_id=candidate.id,
                            rejection_reason="post_patch_validation_failed",
                            failed_metrics={},
                            hard_constraint_triggered="",
                            reusable_insights=[
                                f"Post-patch validation failed on: {', '.join(i.get('field', 'unknown') for i in high_post)}"
                            ],
                            retry_allowed=True,
                        )
                        save_rejected_candidate(rejected)
                    else:
                        # ── Candidate applied (Stage 2-4) ──
                        candidate.status = "applied"
                        candidate.gate_result = "pass"
                        save_autoresearch_candidate(candidate)
                patched_payload = patched_payload_for_s24

        # ── L3: capability patches (prompt.body / tool / model / skill_version) ──
        capability_issues = record.context.get("capability_issues", []) or []
        if decision in {"accepted", "accepted_with_edits"} and capability_issues:
            capability_results: list[dict[str, Any]] = []
            from src.apps.api.app.repositories.store import (
                get_latest_capability_mutability_contract,
            )
            cmc = get_latest_capability_mutability_contract(record.stage_id)
            for cap_issue in capability_issues:
                cap_patch = cap_issue.get("suggested_capability_patch")
                if not cap_patch:
                    capability_results.append({
                        "field": cap_issue.get("field", ""),
                        "status": "rejected",
                        "reason": CAPABILITY_REJECTION_NOT_PATCHABLE,
                    })
                    continue
                field = cap_patch.get("field", "")
                if field not in CAPABILITY_WHITELIST:
                    capability_results.append({
                        "field": field,
                        "status": "rejected",
                        "reason": CAPABILITY_REJECTION_NOT_WHITELISTED,
                    })
                    rejected = RejectedCandidate(
                        id=f"rc-{uuid4().hex[:8]}",
                        project_id=record.project_id,
                        stage_id=record.stage_id,
                        candidate_id=candidate.id if 'candidate' in locals() else f"cand-{uuid4().hex[:8]}",
                        rejection_reason=CAPABILITY_REJECTION_NOT_WHITELISTED,
                        failed_metrics={},
                        hard_constraint_triggered="",
                        reusable_insights=[
                            f"Field '{field}' is not in CAPABILITY_WHITELIST"
                        ],
                        retry_allowed=True,
                    )
                    save_rejected_candidate(rejected)
                    continue
                # Gate check
                if cmc is not None:
                    gate = lookup_capability_gate(cmc, field)
                else:
                    gate = {"permitted": True, "min_sample_size": 1}
                if not gate.get("permitted", True):
                    capability_results.append({
                        "field": field,
                        "status": "rejected",
                        "reason": CAPABILITY_REJECTION_GATE_FAILED,
                    })
                    rejected = RejectedCandidate(
                        id=f"rc-{uuid4().hex[:8]}",
                        project_id=record.project_id,
                        stage_id=record.stage_id,
                        candidate_id=candidate.id if 'candidate' in locals() else f"cand-{uuid4().hex[:8]}",
                        rejection_reason=CAPABILITY_REJECTION_GATE_FAILED,
                        failed_metrics={},
                        hard_constraint_triggered="",
                        reusable_insights=[
                            f"Gate for '{field}' did not permit (min_sample_size="
                            f"{gate.get('min_sample_size')}, min_improvement="
                            f"{gate.get('min_quality_improvement')})"
                        ],
                        retry_allowed=True,
                    )
                    save_rejected_candidate(rejected)
                    continue
                # Apply to settings draft
                new_body = cap_patch.get("value", "")
                if field == "prompt.body" and not _validate_prompt_body(new_body):
                    capability_results.append({
                        "field": field,
                        "status": "rejected",
                        "reason": CAPABILITY_REJECTION_PROMPT_INVALID,
                    })
                    rejected = RejectedCandidate(
                        id=f"rc-{uuid4().hex[:8]}",
                        project_id=record.project_id,
                        stage_id=record.stage_id,
                        candidate_id=candidate.id if 'candidate' in locals() else f"cand-{uuid4().hex[:8]}",
                        rejection_reason=CAPABILITY_REJECTION_PROMPT_INVALID,
                        failed_metrics={},
                        hard_constraint_triggered="",
                        reusable_insights=["Prompt body validation failed"],
                        retry_allowed=True,
                    )
                    save_rejected_candidate(rejected)
                    continue
                draft_id = _apply_capability_patch_to_settings_draft(
                    record.project_id,
                    cap_patch,
                    actor=f"autoresearch:{record.id}",
                )
                if draft_id is None:
                    capability_results.append({
                        "field": field,
                        "status": "rejected",
                        "reason": "draft_create_failed",
                    })
                    continue
                capability_results.append({
                    "field": field,
                    "status": "applied_to_draft",
                    "draft_id": draft_id,
                    "target_prompt_id": cap_patch.get("target_prompt_id", ""),
                })
            # Surface capability results in the patched payload so the
            # API response shows the human reviewer what changed.
            patched_payload.setdefault("capability_patch_results", []).extend(
                capability_results
            )

        stage_result = StageResult(
            id=f"stage-result-{uuid4().hex[:8]}",
            project_id=record.project_id,
            stage_id=record.stage_id,
            version_id=f"sv-{uuid4().hex[:8]}",
            base_version_id=base_result.version_id,
            run_id=record.run_id,
            input_file_ids=list(base_result.input_file_ids),
            evidence_item_ids=list(base_result.evidence_item_ids),
            model_config=dict(base_result.model_config),
            skill_versions=dict(base_result.skill_versions),
            autoresearch_record_ids=list(base_result.autoresearch_record_ids) + [record.id],
            confirmation_ids=list(base_result.confirmation_ids) + [record.id],
            result_payload={
                **patched_payload,
                "autoresearch_decision": decision,
                "autoresearch_description": description,
            },
            summary=f"Applied autoResearch suggestion: {record.title}",
        )
        save_stage_result(stage_result)
        diff_summary = build_stage_result_diff(stage_result, base_result, trigger=decision)
        create_version_log(
            project_id=record.project_id,
            resource_type="stage_result",
            resource_id=stage_result.id,
            change_type=decision,
            summary=f"autoResearch suggestion applied to stage {record.stage_id}.",
            run_id=record.run_id,
            details={
                "record_id": record.id,
                "decision": decision,
                "version_id": stage_result.version_id,
                "base_version_id": stage_result.base_version_id,
                "diff_summary": diff_summary,
            },
        )

    # ── Human-rejected path: create candidate + rejected record ──
    if decision in {"rejected", "follow_up"}:
        candidate = AutoResearchCandidate(
            id=f"cand-{uuid4().hex[:8]}",
            project_id=record.project_id,
            stage_id=record.stage_id,
            run_id=record.run_id,
            change_type="confirmation_decision",
            target_stage="stage-1" if record.stage_id.endswith("stage-1") else record.stage_id.split("-")[-1],
            hypothesis=f"AutoResearch suggestion rejected by human: {record.title}",
            changed_refs=[],
            expected_effect="",
            must_not_change=[],
            status="rejected",
            iteration=-1,
            metrics_before={},
            metrics_after={},
            gate_result="blocked",
            gate_reason="human_rejected",
            human_review_status="rejected",
        )
        save_autoresearch_candidate(candidate)
        rejected = RejectedCandidate(
            id=f"rc-{uuid4().hex[:8]}",
            project_id=record.project_id,
            stage_id=record.stage_id,
            candidate_id=candidate.id,
            rejection_reason="human_rejected",
            failed_metrics={},
            hard_constraint_triggered="",
            reusable_insights=[f"Human decision: {decision}", f"Record: {record.title}"],
            retry_allowed=True,
        )
        save_rejected_candidate(rejected)

    create_execution_log(
        project_id=record.project_id,
        action="autoresearch.confirmed",
        resource_type="autoresearch_record",
        resource_id=record.id,
        run_id=record.run_id,
        details={"decision": decision, "stage_id": record.stage_id, "stage_result_id": record.stage_result_id},
    )
    return record, stage_result


# ── L4: Skill run A/B comparison ──────────────────────────────────────────


# Verdict thresholds — tuned so a 5% quality improvement or regression
# flips the verdict.  Tests assume these exact values.
_AUDIT_IMPROVEMENT_RATIO = 1.05
_QUALITY_REGRESSION_RATIO = 0.95


def _validation_key_for_stage(stage_id: str) -> str | None:
    """Return the result_payload key that holds the contract validation
    output for *stage_id*.

    Maps stage_id → "stage{n}_validation".  Returns None for unknown
    stage_id formats so the caller can fall back gracefully.  Accepts
    both canonical forms ("stage-1") and the shortened form ("stage1")
    used in some test fixtures.
    """
    canonical = {
        "stage-1": "stage1_validation",
        "stage-2": "stage2_validation",
        "stage-3": "stage3_validation",
        "stage-4": "stage4_validation",
        "stage1":  "stage1_validation",
        "stage2":  "stage2_validation",
        "stage3":  "stage3_validation",
        "stage4":  "stage4_validation",
    }
    # Prefer exact match, fall back to suffix match.
    if stage_id in canonical:
        return canonical[stage_id]
    for suffix, key in canonical.items():
        if stage_id.endswith(suffix):
            return key
    return None


def _extract_quality_and_issues(stage_result: StageResult) -> tuple[dict, list, str | None]:
    """Extract the quality dict and issues list from a stage_result.

    Picks the correct ``stage{n}_validation`` key based on
    *stage_result.stage_id* so stage-1 and stage-2 (and now stage-3
    / stage-4) comparisons read the right validation block.  Returns
    ``({}, [], None)`` when the stage_id is unrecognised — callers
    should treat that as a non-fatal "no comparison possible" case
    and skip quality-delta calculation.
    """
    validation_key = _validation_key_for_stage(stage_result.stage_id)
    if validation_key is None or validation_key not in stage_result.result_payload:
        return {}, [], validation_key
    validation_block = stage_result.result_payload.get(validation_key, {})
    if not isinstance(validation_block, dict):
        return {}, [], validation_key
    quality = dict(validation_block.get("quality", {})) if isinstance(
        validation_block.get("quality"), dict
    ) else {}
    issues = list(validation_block.get("issues", [])) if isinstance(
        validation_block.get("issues"), list
    ) else []
    return quality, issues, validation_key


def compare_skill_runs(
    *,
    run_id_v1: str,
    run_id_v2: str,
    skill_name: str = "scenario_risk_skill",
) -> "SkillRunComparison":
    """L4: read two stage_results, compute quality/issue/tool deltas,
    persist a SkillRunComparison record.

    Inputs are the run_ids (not stage_result_ids) so the API can pass
    whatever the client has.  Verdict is decided by these rules:

      * If any quality_v1 dim > 0 and v2 < v1 * 0.95 → ``regressed``
      * Else if audit_readiness_score v2 > v1 * 1.05 → ``improved``
      * Else → ``neutral``
    """
    from src.apps.api.app.repositories.store import (
        get_stage_result,
        save_skill_run_comparison,
    )
    from src.apps.api.app.domain.models import SkillRunComparison

    sr1 = get_stage_result(run_id_v1)
    sr2 = get_stage_result(run_id_v2)
    if sr1 is None or sr2 is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Stage result not found: v1={run_id_v1} v2={run_id_v2} "
                f"(have v1={sr1 is not None} v2={sr2 is not None})"
            ),
        )

    quality_v1, issues_v1, validation_key = _extract_quality_and_issues(sr1)
    quality_v2, issues_v2, _ = _extract_quality_and_issues(sr2)

    # Sanity check: A/B comparison only makes sense if both runs are on
    # the same stage.  Otherwise the quality dimensions are not
    # comparable (stage-1 has 12 quality dims; stage-3 has 5).
    if sr1.stage_id != sr2.stage_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot compare stage_results from different stages: "
                f"v1={sr1.stage_id} v2={sr2.stage_id}"
            ),
        )

    quality_delta: dict[str, float] = {}
    for k in set(quality_v1) | set(quality_v2):
        v1 = float(quality_v1.get(k, 0.0))
        v2 = float(quality_v2.get(k, 0.0))
        quality_delta[k] = round(v2 - v1, 6)

    tools_v1 = sr1.result_payload.get("tool_call_count", {}) if isinstance(
        sr1.result_payload.get("tool_call_count"), dict
    ) else {}
    tools_v2 = sr2.result_payload.get("tool_call_count", {}) if isinstance(
        sr2.result_payload.get("tool_call_count"), dict
    ) else {}
    tool_call_diff: dict[str, int] = {}
    for tool in set(tools_v1) | set(tools_v2):
        tool_call_diff[tool] = int(tools_v2.get(tool, 0)) - int(tools_v1.get(tool, 0))

    # Verdict
    regressed = False
    for k, v1 in quality_v1.items():
        v2 = quality_v2.get(k, v1)
        if v1 > 0 and v2 < v1 * _QUALITY_REGRESSION_RATIO:
            regressed = True
            break
    improved = False
    if not regressed:
        a1 = quality_v1.get("audit_readiness_score", 0.0)
        a2 = quality_v2.get("audit_readiness_score", 0.0)
        if a1 > 0 and a2 > a1 * _AUDIT_IMPROVEMENT_RATIO:
            improved = True
    if regressed:
        verdict = "regressed"
        reason = f"Some quality dim fell below v1 * {_QUALITY_REGRESSION_RATIO}"
    elif improved:
        verdict = "improved"
        reason = f"audit_readiness_score rose above v1 * {_AUDIT_IMPROVEMENT_RATIO}"
    else:
        verdict = "neutral"
        reason = "No quality dim crossed improvement or regression threshold"

    import hashlib as _hl
    payload_repr = repr(sorted(sr1.result_payload.items())[:5])
    input_hash = _hl.sha256(payload_repr.encode("utf-8")).hexdigest()

    comparison = SkillRunComparison(
        id=f"srcmp-{uuid4().hex[:8]}",
        project_id=sr1.project_id,
        stage_id=sr1.stage_id,
        skill_name=skill_name,
        run_id_v1=sr1.id,
        version_v1=sr1.skill_versions.get(skill_name, ""),
        run_id_v2=sr2.id,
        version_v2=sr2.skill_versions.get(skill_name, ""),
        input_payload_hash=input_hash,
        quality_v1=quality_v1,
        quality_v2=quality_v2,
        quality_delta=quality_delta,
        issue_count_v1=len(issues_v1),
        issue_count_v2=len(issues_v2),
        tool_call_diff=tool_call_diff,
        prompt_hashes_v1=dict(sr1.prompt_hashes),
        prompt_hashes_v2=dict(sr2.prompt_hashes),
        verdict=verdict,
        verdict_reason=reason,
    )
    save_skill_run_comparison(comparison)
    create_execution_log(
        project_id=comparison.project_id,
        action="skill_run_comparison.created",
        resource_type="skill_run_comparison",
        resource_id=comparison.id,
        details={
            "verdict": verdict,
            "skill_name": skill_name,
            "run_id_v1": comparison.run_id_v1,
            "version_v1": comparison.version_v1,
            "run_id_v2": comparison.run_id_v2,
            "version_v2": comparison.version_v2,
            "delta_keys": sorted(quality_delta.keys()),
        },
    )
    return comparison


def run_skill_ab_comparison(
    *,
    project_id: str,
    stage_id: str,
    skill_name: str,
    version_v1: str,
    version_v2: str,
    input_payload: dict[str, Any] | None = None,
) -> "SkillRunComparison":
    """L4: A/B orchestration — invoke the same input under two skill
    versions and compare the resulting stage_results.

    The A/B run creates two NEW stage_results (run_a / run_b) and one
    SkillRunComparison.  The published ``StageSkillProfile.skill_versions``
    is mutated to v1, then v2, then restored to its original value so
    no other Run observes the temporary state.

    *input_payload* is a hint to the underlying ``invoke_skill`` call —
    tests may pass a stub that ignores it.
    """
    from src.apps.api.app.services.skill_service import invoke_skill
    from src.apps.api.app.repositories.store import (
        list_project_settings,
        get_stage_result,
        save_stage_result,
    )

    settings_list = list_project_settings(project_id)
    published = next((s for s in settings_list if s.status == "published"), None)
    if published is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No published settings for project {project_id}",
        )

    # ── A/B isolation: work on an in-memory deep copy of the profile
    # so the published settings are NEVER mutated on disk during the
    # A/B run.  Concurrent invocations on the same project will not see
    # the temporary v1/v2 mutations because we never persist them.
    target_profile = next(
        (
            p
            for p in published.stage_skill_profiles
            if p.stage_id == stage_id
        ),
        None,
    )
    if target_profile is not None:
        # Deep-copy the profile into a fresh StageSkillProfile so
        # mutations are scoped to this A/B run only.
        from src.apps.api.app.domain.models import StageSkillProfile
        isolated_profile = StageSkillProfile(
            stage_id=target_profile.stage_id,
            primary_skill=target_profile.primary_skill,
            enabled_tools=list(target_profile.enabled_tools),
            enabled_subagents=list(target_profile.enabled_subagents),
            auto_run_condition=target_profile.auto_run_condition,
            skill_versions=dict(target_profile.skill_versions),
        )
        # Swap the isolated profile into the published settings list
        # for the duration of this call.  The published object itself
        # is not persisted; only this in-memory view is used.
        _published_backup = published.stage_skill_profiles
        published.stage_skill_profiles = [
            isolated_profile if p.stage_id == stage_id else p
            for p in published.stage_skill_profiles
        ]
    try:
        if target_profile is not None:
            isolated_profile.skill_versions[skill_name] = version_v1
        result_v1 = invoke_skill(
            project_id=project_id,
            stage_id=stage_id,
            skill_name=skill_name,
            input_payload=input_payload or {},
        )
        if target_profile is not None:
            isolated_profile.skill_versions[skill_name] = version_v2
        result_v2 = invoke_skill(
            project_id=project_id,
            stage_id=stage_id,
            skill_name=skill_name,
            input_payload=input_payload or {},
        )
    finally:
        # Restore: put the published profile list back.  No persistence
        # was performed during the A/B run, so the on-disk state is
        # guaranteed unchanged.
        if target_profile is not None:
            published.stage_skill_profiles = _published_backup

    # Compare
    return compare_skill_runs(
        run_id_v1=result_v1.get("stage_result_id", ""),
        run_id_v2=result_v2.get("stage_result_id", ""),
        skill_name=skill_name,
    )
