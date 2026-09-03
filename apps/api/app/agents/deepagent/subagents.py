"""Sub-agent review logic with structured output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class SubagentResult:
    name: str
    summary: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    review_status: str = "pass"  # "pass" | "warning" | "fail"
    suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal review handlers
# ---------------------------------------------------------------------------

def _review_risk(
    *,
    goal: str,
    stage_name: str,
    tool_results: dict[str, Any] | None = None,
    previous_stage_result: dict[str, Any] | None = None,
    llm_client: Any = None,
) -> SubagentResult:
    """Stage 1 risk review: validate scenario_summary via stage1_contract.

    When ``llm_client`` is configured, also asks the LLM for a second-opinion
    review (``review_risk_semantic``) and merges any ``additional_issues`` into
    the rule-based issue list.  Unconfigured / LLM-failed runs produce
    byte-identical output to the pre-upgrade baseline.
    """
    tool_results = tool_results or {}
    risk_output = tool_results.get("risk_identify", {})
    doc_output = tool_results.get("document_parse", {})
    vision_output = tool_results.get("vision_parse", {})

    issues: list[dict[str, Any]] = []
    suggestions: list[str] = []

    # Assemble a candidate scenario_summary from tool outputs
    from src.apps.api.app.services.stage1_contract import (
        validate_stage1_summary,
        compute_stage1_quality,
        normalize_risk_level,
        normalize_hitl_level,
    )

    # Build minimal summary for validation
    risk_level_raw = risk_output.get("risk_level", "L1")
    hitl_level_raw = risk_output.get("hitl_level", "none")
    try:
        risk_level = normalize_risk_level(risk_level_raw)
    except ValueError:
        risk_level = "L1"
        issues.append({
            "issue_type": "invalid_enum",
            "field": "risk_level",
            "severity": "high",
            "message": f"无效风险等级 '{risk_level_raw}'，已降级为 L1",
        })

    try:
        hitl_level = normalize_hitl_level(hitl_level_raw, risk_level=risk_level)
    except ValueError:
        hitl_level = "none"
        issues.append({
            "issue_type": "invalid_enum",
            "field": "hitl_level",
            "severity": "high",
            "message": f"无效 HITL 等级 '{hitl_level_raw}'",
        })

    scenario_summary = {
        "scenario_name": doc_output.get("scenario_name_candidates", [""])[0] if doc_output.get("scenario_name_candidates") else goal[:24],
        "scenario_type": doc_output.get("scenario_type", ""),
        "boundary": doc_output.get("boundary", {"in_scope": [], "out_of_scope": [], "preconditions": [], "data_boundary": []}),
        "sop_summary": doc_output.get("sop_summary", ""),
        "participants": doc_output.get("participants", []),
        "process_nodes": doc_output.get("process_node_candidates", []),
        "risk_items": risk_output.get("risk_items", []),
        "risk_level": risk_level,
        "hitl_level": hitl_level,
        "risk_matrix": risk_output.get("risk_matrix", []),
        "hitl_rules": risk_output.get("hitl_rules", []),
        "audit_requirements": list(doc_output.get("audit_requirements", [])) + list(risk_output.get("audit_requirements", [])),
        "prohibited_conditions": risk_output.get("prohibited_conditions", []),
        "fatal_errors": risk_output.get("fatal_errors", []),
        "evidence_refs": list(doc_output.get("evidence_refs", [])) + list(risk_output.get("evidence_refs", [])),
        "to_confirm": list(risk_output.get("to_confirm", [])) + list(vision_output.get("to_confirm", [])),
        "confidence": risk_output.get("confidence", {"overall": 0.5}),
        "review_status": "draft",
    }

    # Run contract validation
    validation_issues = validate_stage1_summary(scenario_summary)
    if validation_issues:
        issues.extend(validation_issues)
        for issue in validation_issues:
            desc = issue.get("message", str(issue))
            suggestions.append(desc)

    # Compute quality
    quality = compute_stage1_quality(scenario_summary)
    audit_score = quality.get("audit_readiness_score", 0.0)

    # Flag low quality
    if quality.get("completeness", 1.0) < 0.70:
        suggestions.append("场景摘要完整性低于 70%，建议补充关键输入")
    if quality.get("evidence_coverage", 1.0) < 0.70:
        suggestions.append("证据覆盖率低于 70%，建议上传更多材料")

    # Check L3 + mandatory keyword → HITL should be strict/mandatory
    if risk_level == "L3" and hitl_level in ("none", "standard"):
        issues.append({
            "issue_type": "hitl_mismatch",
            "field": "hitl_level",
            "severity": "high",
            "message": f"L3 风险等级应搭配 strict/mandatory HITL，当前为 {hitl_level}",
        })
        suggestions.append("将 HITL 等级提升为 strict 或 mandatory")

    # ── LLM second-opinion (optional) ──────────────────────────────
    # When an LLM client is provided, ask for additional issues that the
    # rule-based contract validation may have missed.  The merge is
    # additive — existing issues are preserved.  When the LLM is
    # unconfigured or returns an empty result, this branch is a no-op.
    llm_review_added = 0
    if llm_client is not None:
        from src.apps.api.app.agents.risk_semantic import review_risk_semantic

        review = review_risk_semantic(
            scenario_summary,
            issues,
            llm_client=llm_client,
        )
        if review.source == "llm":
            for extra in review.additional_issues:
                issues.append(extra)
                llm_review_added += 1
            for sug in review.suggestions:
                if sug and sug not in suggestions:
                    suggestions.append(sug)

    review_status = "fail" if issues else "pass"

    summary_text = f"风险复核完成：{len(issues)} 个问题，质量分 {audit_score:.2f}"
    if llm_review_added:
        summary_text += f"，LLM 第二意见新增 {llm_review_added} 条"

    return SubagentResult(
        name="risk_review_subagent",
        summary=summary_text,
        issues=issues,
        confidence=audit_score,
        review_status=review_status,
        suggestions=suggestions,
    )


def _review_value(
    *,
    goal: str,
    stage_name: str,
    tool_results: dict[str, Any] | None = None,
    previous_stage_result: dict[str, Any] | None = None,
) -> SubagentResult:
    """Stage 2 value review: contract validation + risk alignment checks."""
    tool_results = tool_results or {}
    value_output = tool_results.get("value_model", {})
    sla_output = tool_results.get("sla_target", {})

    issues: list[dict[str, Any]] = []
    suggestions: list[str] = []

    # Build stage 2 summary for contract validation
    from src.apps.api.app.services.stage2_contract import (
        validate_stage2_summary,
        compute_stage2_quality,
    )

    prev = previous_stage_result or {}
    scenario_summary = prev.get("scenario_summary", {})
    risk_level = scenario_summary.get("risk_level", "L1")

    # Construct stage 2 summary from tool outputs
    stage2_summary = {
        "implementation_tax": value_output.get("implementation_tax", ""),
        "target_sla": sla_output.get("target_sla"),
        "stability": sla_output.get("stability", ""),
        "risk_level": risk_level,
        "evidence_refs": list(value_output.get("evidence_refs", [])) + list(sla_output.get("evidence_refs", [])),
    }

    # Run contract validation
    validation_issues = validate_stage2_summary(stage2_summary, previous_stage_result=prev)
    if validation_issues:
        issues.extend(validation_issues)
        for issue in validation_issues:
            suggestions.append(issue.get("suggested_action", issue.get("message", str(issue))))

    # Compute quality
    quality = compute_stage2_quality(stage2_summary)
    audit_score = quality.get("audit_readiness_score", 0.0)

    # Additional semantic checks
    impl_tax = value_output.get("implementation_tax", "")
    if risk_level == "L3" and impl_tax != "high":
        issues.append({
            "issue_type": "value_mismatch",
            "field": "implementation_tax",
            "severity": "medium",
            "message": f"L3 风险等级应搭配高实施税，当前为 {impl_tax}",
        })
        suggestions.append("将实施税调整为 high")

    stability = sla_output.get("stability", "")
    if stability == "unstable":
        issues.append({
            "issue_type": "sla_unstable",
            "field": "stability",
            "severity": "medium",
            "message": "SLA 目标不稳定，需人工确认",
        })
        suggestions.append("确认 SLA 目标是否合理")

    review_status = "fail" if any(i.get("severity") == "high" for i in issues) else ("warning" if issues else "pass")

    return SubagentResult(
        name="value_review_subagent",
        summary=f"价值复核完成：{len(issues)} 个问题，质量分 {audit_score:.2f}",
        issues=issues,
        confidence=audit_score,
        review_status=review_status,
        suggestions=suggestions,
    )


def _review_probe(
    *,
    goal: str,
    stage_name: str,
    tool_results: dict[str, Any] | None = None,
    previous_stage_result: dict[str, Any] | None = None,
) -> SubagentResult:
    """Stage 3 probe review: contract validation + sample/SLA consistency checks."""
    tool_results = tool_results or {}
    sample_output = tool_results.get("sample_score", {})
    sla_output = tool_results.get("actual_sla_summary", {})

    issues: list[dict[str, Any]] = []
    suggestions: list[str] = []

    from src.apps.api.app.services.stage3_contract import (
        validate_stage3_summary,
        compute_stage3_quality,
    )

    prev = previous_stage_result or {}
    scenario_summary = prev.get("scenario_summary", {})
    risk_level = scenario_summary.get("risk_level", "L1")

    # Construct stage 3 summary from tool outputs
    stage3_summary = {
        "sample_size": sample_output.get("sample_size"),
        "low_score_samples": sample_output.get("low_score_samples"),
        "gap_to_target_pct": sla_output.get("gap_to_target_pct"),
        "actual_sla": sla_output.get("actual_sla"),
        "stability": sla_output.get("stability", ""),
        "risk_level": risk_level,
        "evidence_refs": list(sample_output.get("evidence_refs", [])) + list(sla_output.get("evidence_refs", [])),
    }

    # Run contract validation
    validation_issues = validate_stage3_summary(stage3_summary, previous_stage_result=prev)
    if validation_issues:
        issues.extend(validation_issues)
        for issue in validation_issues:
            suggestions.append(issue.get("suggested_action", issue.get("message", str(issue))))

    # Compute quality
    quality = compute_stage3_quality(stage3_summary)
    audit_score = quality.get("audit_readiness_score", 0.0)

    # Additional semantic checks
    low_score_samples = sample_output.get("low_score_samples", 0)
    if low_score_samples > 3:
        issues.append({
            "issue_type": "low_score_samples",
            "field": "low_score_samples",
            "severity": "high",
            "message": f"低分样本过多 ({low_score_samples})，需深入分析",
        })
        suggestions.append("分析低分样本原因，考虑调整任务或模型")

    gap = sla_output.get("gap_to_target_pct", 0)
    if isinstance(gap, (int, float)) and gap < -10:
        issues.append({
            "issue_type": "sla_gap_large",
            "field": "gap_to_target_pct",
            "severity": "medium",
            "message": f"SLA 低于目标过多 ({abs(gap)}pp)，需评估改进方案",
        })
        suggestions.append("评估是否需要调整 SLA 目标或改进模型")

    review_status = "fail" if any(i.get("severity") == "high" for i in issues) else ("warning" if issues else "pass")

    return SubagentResult(
        name="probe_review_subagent",
        summary=f"探针复核完成：{len(issues)} 个问题，质量分 {audit_score:.2f}",
        issues=issues,
        confidence=audit_score,
        review_status=review_status,
        suggestions=suggestions,
    )


def _review_evidence(
    *,
    goal: str,
    stage_name: str,
    tool_results: dict[str, Any] | None = None,
    previous_stage_result: dict[str, Any] | None = None,
) -> SubagentResult:
    """Stage 4 evidence review: contract validation + bundle completeness checks."""
    tool_results = tool_results or {}
    evidence_output = tool_results.get("evidence_bundle", {})

    issues: list[dict[str, Any]] = []
    suggestions: list[str] = []

    from src.apps.api.app.services.stage4_contract import (
        validate_stage4_summary,
        compute_stage4_quality,
    )

    prev = previous_stage_result or {}
    scenario_summary = prev.get("scenario_summary", {})
    risk_level = scenario_summary.get("risk_level", "L1")

    # Construct stage 4 evidence summary from tool outputs
    report_output = tool_results.get("report_generate", {})
    stage4_evidence_summary = {
        "bundle_status": evidence_output.get("bundle_status", ""),
        "evidence_count": evidence_output.get("evidence_count", 0),
        "report_status": report_output.get("report_status", ""),
        "decision_card": report_output.get("decision_card"),
        "risk_level": risk_level,
        "evidence_refs": list(evidence_output.get("evidence_refs", [])) + list(report_output.get("evidence_refs", [])),
    }

    # Run contract validation
    validation_issues = validate_stage4_summary(stage4_evidence_summary, previous_stage_result=prev)
    if validation_issues:
        issues.extend(validation_issues)
        for issue in validation_issues:
            suggestions.append(issue.get("suggested_action", issue.get("message", str(issue))))

    # Compute quality
    quality = compute_stage4_quality(stage4_evidence_summary)
    audit_score = quality.get("audit_readiness_score", 0.0)

    # Additional semantic checks
    bundle_status = evidence_output.get("bundle_status", "")
    if bundle_status == "draft":
        suggestions.append("证据包尚为草稿状态，建议完善后锁定")

    evidence_count = evidence_output.get("evidence_count", 0)
    if evidence_count < 3:
        issues.append({
            "issue_type": "insufficient_evidence",
            "field": "evidence_count",
            "severity": "medium",
            "message": f"证据数量不足 ({evidence_count})，建议补充至少 3 条",
        })
        suggestions.append("补充更多证据以支持决策")

    review_status = "fail" if any(i.get("severity") == "high" for i in issues) else ("warning" if issues else "pass")

    return SubagentResult(
        name="evidence_review_subagent",
        summary=f"证据复核完成：{len(issues)} 个问题，质量分 {audit_score:.2f}",
        issues=issues,
        confidence=audit_score,
        review_status=review_status,
        suggestions=suggestions,
    )


def _review_report(
    *,
    goal: str,
    stage_name: str,
    tool_results: dict[str, Any] | None = None,
    previous_stage_result: dict[str, Any] | None = None,
) -> SubagentResult:
    """Stage 4 report review: contract validation + report readiness checks."""
    tool_results = tool_results or {}
    report_output = tool_results.get("report_generate", {})
    export_output = tool_results.get("export_bundle", {})

    issues: list[dict[str, Any]] = []
    suggestions: list[str] = []

    from src.apps.api.app.services.stage4_contract import (
        validate_stage4_summary,
        compute_stage4_quality,
    )

    prev = previous_stage_result or {}
    scenario_summary = prev.get("scenario_summary", {})
    risk_level = scenario_summary.get("risk_level", "L1")

    # Construct stage 4 report summary from tool outputs
    evidence_output = tool_results.get("evidence_bundle", {})
    stage4_report_summary = {
        "bundle_status": evidence_output.get("bundle_status", ""),
        "evidence_count": export_output.get("evidence_count", 0),
        "report_status": report_output.get("report_status", ""),
        "decision_card": report_output.get("decision_card"),
        "export_ready": export_output.get("export_ready", False),
        "risk_level": risk_level,
        "evidence_refs": list(report_output.get("evidence_refs", [])) + list(export_output.get("evidence_refs", [])) + list(evidence_output.get("evidence_refs", [])),
        "sections": report_output.get("sections", []),
    }

    # Run contract validation
    validation_issues = validate_stage4_summary(stage4_report_summary, previous_stage_result=prev)
    if validation_issues:
        issues.extend(validation_issues)
        for issue in validation_issues:
            suggestions.append(issue.get("suggested_action", issue.get("message", str(issue))))

    # Compute quality
    quality = compute_stage4_quality(stage4_report_summary)
    audit_score = quality.get("audit_readiness_score", 0.0)

    # Additional semantic checks
    report_status = report_output.get("report_status", "")
    if report_status == "draft":
        suggestions.append("报告尚为草稿状态，建议完善后提交审核")

    if not export_output.get("export_ready", False):
        issues.append({
            "issue_type": "export_not_ready",
            "severity": "low",
            "message": "导出包尚未就绪",
        })
        suggestions.append("完善导出包内容")

    # Check report section coverage
    sections = report_output.get("sections", [])
    if not sections:
        issues.append({
            "issue_type": "empty_sections",
            "field": "sections",
            "severity": "medium",
            "message": "报告无章节定义",
        })
        suggestions.append("添加报告章节覆盖风险评估、SLA 结果和决策建议")

    review_status = "fail" if any(i.get("severity") == "high" for i in issues) else ("warning" if issues else "pass")

    return SubagentResult(
        name="report_review_subagent",
        summary=f"报告复核完成：{len(issues)} 个问题，质量分 {audit_score:.2f}",
        issues=issues,
        confidence=audit_score,
        review_status=review_status,
        suggestions=suggestions,
    )


# ---------------------------------------------------------------------------
# Dispatch registry
# ---------------------------------------------------------------------------

_SUBAGENT_REGISTRY: dict[str, Callable[..., SubagentResult]] = {
    "risk_review_subagent": _review_risk,
    "value_review_subagent": _review_value,
    "probe_review_subagent": _review_probe,
    "evidence_review_subagent": _review_evidence,
    "report_review_subagent": _review_report,
}


def invoke_subagent(
    subagent_name: str,
    *,
    goal: str,
    stage_name: str,
    tool_results: dict[str, Any] | None = None,
    previous_stage_result: dict[str, Any] | None = None,
    llm_client: Any = None,
) -> SubagentResult:
    """Dispatch to the appropriate review handler.

    Falls back to a generic pass result for unknown subagent names.
    When *llm_client* is provided, it is forwarded to handlers that
    accept it (currently ``_review_risk`` for second-opinion reviews).
    Handlers without an ``llm_client`` parameter simply ignore it via
    the filter below, preserving their original signatures.
    """
    handler = _SUBAGENT_REGISTRY.get(subagent_name)
    if handler is None:
        return SubagentResult(
            name=subagent_name,
            summary=f"未知子代理 {subagent_name}，跳过复核",
            review_status="pass",
        )

    import inspect
    handler_kwargs = {
        "goal": goal,
        "stage_name": stage_name,
        "tool_results": tool_results,
        "previous_stage_result": previous_stage_result,
    }
    # Only forward llm_client when the handler signature accepts it —
    # keeps older review handlers backward-compatible.
    try:
        sig_params = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        sig_params = {}
    if llm_client is not None and "llm_client" in sig_params:
        handler_kwargs["llm_client"] = llm_client
    return handler(**handler_kwargs)
