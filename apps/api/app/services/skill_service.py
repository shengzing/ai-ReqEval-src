"""Fixed skill listing and invocation services."""

from __future__ import annotations

from uuid import uuid4
from typing import Optional

from fastapi import HTTPException, status

from src.apps.api.app.agents.harness.llm import HarnessLLMClient
from src.apps.api.app.agents.skills.registry import SkillDefinition, get_skill_by_name, list_skills as registry_list_skills
from src.apps.api.app.agents.harness.contracts import HarnessRequest
from src.apps.api.app.agents.harness.registry import get_harness_provider
from src.apps.api.app.agents.harness.serializers import serialize_harness_payload
from src.apps.api.app.agents.harness.state import NO_LLM_FALLBACK_MESSAGE
from src.apps.api.app.core.harness_constants import DEFAULT_AGENT_HARNESS_VERSION
from src.apps.api.app.domain.models import StageResult, utcnow
from src.apps.api.app.repositories.store import get_latest_stage_result, save_stage_result
from src.apps.api.app.services.log_service import create_execution_log, create_version_log
from src.apps.api.app.services.project_service import create_report, get_stage, list_evidence
from src.apps.api.app.services.run_service import append_run_event, get_run
from src.apps.api.app.services.settings_service import filter_tools_for_skill, settings_snapshot
from src.apps.api.app.services.stage_result_service import build_stage_result_diff
from src.apps.api.app.services.vision_service import load_project_vision_results
from src.apps.api.app.services.stage1_contract import (
    _is_substantive,
    compute_stage1_quality,
    normalize_hitl_level,
    normalize_risk_level,
    validate_stage1_summary,
)
from src.apps.api.app.services.stage2_contract import (
    compute_stage2_quality,
    normalize_implementation_tax,
    normalize_target_sla,
    validate_stage2_summary,
)
from src.apps.api.app.services.stage3_contract import (
    compute_stage3_quality,
    normalize_gap_to_target_pct,
    normalize_actual_sla,
    normalize_sample_size,
    validate_stage3_summary,
)
from src.apps.api.app.services.stage4_contract import (
    BUNDLE_STATUSES,
    REPORT_STATUSES,
    compute_stage4_quality,
    validate_stage4_summary,
)


def _build_edges_from_nodes(process_nodes: list[dict]) -> dict:
    """Build an edges-based business process IR from Stage 1 process nodes.

    Replaces the former Mermaid linear generator. Returns a dict with:
    - ``format``: ``"edges"`` (new IR shape, consumed by ``flow_diagram_score``
      and the frontend ``SAPWorkflowPanel``).
    - ``edges``: list of ``{from, to, variant}`` — a default linear chain where
      each adjacent pair of process nodes gets one ``variant:"main"`` edge.
    - ``main_path``: ordered ``node_id`` list (the happy path, never regressing
      in ``process_nodes`` order — see archify's mainPath no-regression rule).
    - ``source``: ``"process_nodes"``.
    - ``warnings``: empty when nodes exist, else a single warning string.

    The LLM synthesizer may override ``edges`` / ``main_path``; this function
    only produces the deterministic fallback when evidence is absent.
    """
    if not process_nodes:
        return {
            "format": "edges",
            "edges": [],
            "main_path": [],
            "source": "process_nodes",
            "warnings": ["No process nodes available."],
        }

    # Guard against non-dict items (string nodes from test fixtures or LLM
    # candidates): ``node.get`` would otherwise raise ``AttributeError``.
    # Mirrors the ``isinstance(node, dict)`` filter already used at call site
    # :137. Protects both the production caller (:281) and the post-merge
    # revert caller (:809) without changing their call sites.
    dict_nodes = [n for n in process_nodes if isinstance(n, dict)]
    node_ids = [str(node.get("node_id", "")) for node in dict_nodes]
    edges = [
        {"from": node_ids[i], "to": node_ids[i + 1], "variant": "main"}
        for i in range(len(node_ids) - 1)
        if node_ids[i] and node_ids[i + 1]
    ]
    main_path = [nid for nid in node_ids if nid]

    return {
        "format": "edges",
        "edges": edges,
        "main_path": main_path,
        "source": "process_nodes",
        "warnings": [],
    }


def _find_process_node_id(
    process_nodes: list[dict],
    *,
    preferred_keywords: tuple[str, ...],
    fallback_to_review: bool = True,
) -> str:
    if not process_nodes:
        return ""

    for keyword in preferred_keywords:
        for node in process_nodes:
            if keyword and keyword in str(node.get("name", "")):
                return str(node.get("node_id", ""))

    if fallback_to_review:
        for node in process_nodes:
            if node.get("human_review_required") is True:
                return str(node.get("node_id", ""))

    return str(process_nodes[-1].get("node_id", ""))


def _risk_binding_keywords(description: str) -> tuple[str, ...]:
    mapping = [
        (("材料", "输入", "缺失"), ("收集", "材料")),
        (("核验", "口径", "异常", "经营"), ("核验", "异常")),
        (("预警", "漏报", "风险"), ("识别", "预警", "风险")),
        (("摘要", "疑点", "建议"), ("草拟", "摘要", "建议")),
        (("客户处置", "处置"), ("处置", "复核")),
        (("监管", "审计", "追责", "合规"), ("合规", "复核")),
    ]
    keywords: list[str] = []
    for triggers, node_keywords in mapping:
        if any(trigger in description for trigger in triggers):
            keywords.extend(node_keywords)
    if not keywords:
        keywords.extend(["风险", "复核"])
    return tuple(dict.fromkeys(keywords))


def _bind_stage_one_risk_and_hitl_to_nodes(summary: dict) -> dict:
    """Bind risk items, risk matrix rows, and HITL rules to process node IDs."""
    process_nodes = [node for node in summary.get("process_nodes", []) if isinstance(node, dict)]
    if not process_nodes:
        return summary

    risk_items = []
    risk_node_by_id: dict[str, str] = {}
    for item in summary.get("risk_items", []):
        if not isinstance(item, dict):
            risk_items.append(item)
            continue
        updated = dict(item)
        description = " ".join(
            str(updated.get(field, ""))
            for field in ("description", "impact", "audit_need", "mitigation")
        )
        node_id = updated.get("node_id") or _find_process_node_id(
            process_nodes,
            preferred_keywords=_risk_binding_keywords(description),
        )
        updated["node_id"] = node_id
        if updated.get("risk_id"):
            risk_node_by_id[str(updated["risk_id"])] = node_id
        risk_items.append(updated)

    risk_matrix = []
    for row in summary.get("risk_matrix", []):
        if not isinstance(row, dict):
            risk_matrix.append(row)
            continue
        updated = dict(row)
        row_text = " ".join(str(updated.get(field, "")) for field in ("item", "control"))
        risk_id = str(updated.get("risk_id", ""))
        updated["node_id"] = updated.get("node_id") or risk_node_by_id.get(risk_id) or _find_process_node_id(
            process_nodes,
            preferred_keywords=_risk_binding_keywords(row_text),
        )
        risk_matrix.append(updated)

    hitl_rules = []
    review_node_id = _find_process_node_id(process_nodes, preferred_keywords=("复核", "合规", "确认"))
    for rule in summary.get("hitl_rules", []):
        if not isinstance(rule, dict):
            hitl_rules.append(rule)
            continue
        updated = dict(rule)
        updated["node_id"] = updated.get("node_id") or review_node_id
        hitl_rules.append(updated)

    summary = dict(summary)
    summary["risk_items"] = risk_items
    summary["risk_matrix"] = risk_matrix
    summary["hitl_rules"] = hitl_rules
    return summary


def _build_stage_one_responsibilities(
    participants: list[dict],
    process_nodes: list[dict],
) -> list[dict]:
    """Build node-level responsibility chain from enriched process nodes."""
    if not process_nodes:
        responsibilities = []
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            responsibilities.append({
                "role": participant.get("role", ""),
                "node_id": "",
                "responsibility": participant.get("responsibility", ""),
                "handoff_to": [],
                "evidence_refs": participant.get("evidence_refs", []),
            })
        return responsibilities

    responsibilities = []
    for idx, node in enumerate(process_nodes):
        if not isinstance(node, dict):
            continue
        role = str(node.get("owner_role", ""))
        next_owner = ""
        for next_node in process_nodes[idx + 1:]:
            if isinstance(next_node, dict):
                next_owner = str(next_node.get("owner_role", ""))
                if next_owner and next_owner != role:
                    break
        handoff_to = [next_owner] if next_owner and next_owner != role else []
        node_name = str(node.get("name", ""))
        responsibility = f"负责流程节点：{node_name}" if node_name else ""
        if node.get("human_review_required"):
            responsibility += "；执行人工复核与确认"
        if node.get("audit_fields"):
            responsibility += "；保留审计留痕"
        responsibilities.append({
            "role": role,
            "node_id": node.get("node_id", ""),
            "responsibility": responsibility,
            "handoff_to": handoff_to,
            "evidence_refs": node.get("evidence_refs", []),
        })
    return responsibilities


def _build_scenario_deconstruction(
    *, goal: str, stage_name: str, tool_payload: dict, vision_results: list[dict]
) -> dict:
    """Phase A — 场景解构：构建 scenario_summary 的前 11 个字段。

    数据源：``document_parse`` + ``vision_parse``。不触碰 risk_identify 输出，
    不做风险侧对 boundary.out_of_scope 的充实（那归 Phase B）。

    返回字段：scenario_name、scenario_type、boundary（4 子键）、sop_summary、
    participants、process_nodes、process_flow_diagram、edges、main_path、
    responsibilities、evidence_refs（仅 document + vision 侧）。
    """
    parsed = tool_payload.get("document_parse", {})
    vision = tool_payload.get("vision_parse", {})

    # Scenario name: prefer parsed candidate, then goal first line, then stage name
    candidates = parsed.get("scenario_name_candidates", [])
    scenario_name = candidates[0] if candidates else (goal.split("\n")[0][:24] if goal else stage_name)

    # Boundary: from document_parse only (Phase B enriches out_of_scope with
    # prohibited_conditions).
    boundary = parsed.get("boundary", {"in_scope": [], "out_of_scope": [], "preconditions": [], "data_boundary": []})
    if not isinstance(boundary, dict):
        boundary = {"in_scope": [str(boundary)], "out_of_scope": [], "preconditions": [], "data_boundary": []}
    for key in ("in_scope", "out_of_scope", "preconditions", "data_boundary"):
        boundary.setdefault(key, [])

    # SOP summary: from document_parse
    sop_summary = parsed.get("sop_summary", "")

    # Participants: merge document_parse + vision role candidates
    participants = list(parsed.get("participants", []))
    vision_roles = vision.get("role_candidates", [])
    if isinstance(vision_roles, list):
        existing_roles = {p.get("role", "") if isinstance(p, dict) else str(p) for p in participants}
        for vr in vision_roles:
            role_name = vr.get("role", "") if isinstance(vr, dict) else str(vr)
            if role_name and role_name not in existing_roles:
                participants.append({"role": role_name, "responsibility": "", "evidence_refs": []})

    # Process nodes: from document_parse candidates
    process_nodes = list(parsed.get("process_node_candidates", []))
    process_flow_diagram = _build_edges_from_nodes(process_nodes)

    # Responsibilities: node-level responsibility chain derived from process nodes.
    responsibilities = _build_stage_one_responsibilities(participants, process_nodes)

    # Evidence refs: union of document_parse + vision_parse (risk refs added in Phase B)
    evidence_refs = list(parsed.get("evidence_refs", []))
    for ref in vision.get("evidence_fragments", []):
        frag_id = ref.get("id", "") if isinstance(ref, dict) else ""
        if frag_id and frag_id not in evidence_refs:
            evidence_refs.append(frag_id)

    return {
        "scenario_name": scenario_name,
        "scenario_type": parsed.get("scenario_type", ""),
        "boundary": boundary,
        "sop_summary": sop_summary,
        "participants": participants,
        "process_nodes": process_nodes,
        "process_flow_diagram": process_flow_diagram,
        "edges": process_flow_diagram.get("edges", []),
        "main_path": process_flow_diagram.get("main_path", []),
        "responsibilities": responsibilities,
        "evidence_refs": evidence_refs,
    }


def _build_risk_grading(
    *, scenario_deconstruction: dict, goal: str, stage_name: str, tool_payload: dict, vision_results: list[dict]
) -> dict:
    """Phase B — 风险定级：构建 scenario_summary 的后 14 个字段。

    数据源：``risk_identify``。**依赖** Phase A 的 ``process_nodes`` / ``boundary``
    （把 prohibited_conditions 充实进 boundary.out_of_scope）。

    返回字段：risk_items、risk_level、hitl_level、risk_matrix、hitl_rules、
    audit_requirements、prohibited_conditions、fatal_errors、evidence_refs
    （Phase A refs + risk refs 去重并集）、to_confirm、confidence、boundary_flag、
    review_status、可选 risk_confidence；同时返回更新后的 boundary。
    """
    parsed = tool_payload.get("document_parse", {})
    vision = tool_payload.get("vision_parse", {})
    risk = tool_payload.get("risk_identify", {})

    # Enrich boundary.out_of_scope with risk prohibited conditions
    boundary = dict(scenario_deconstruction.get("boundary", {}))
    for key in ("in_scope", "out_of_scope", "preconditions", "data_boundary"):
        boundary.setdefault(key, [])
        if not isinstance(boundary[key], list):
            boundary[key] = list(boundary[key])
    risk_prohibited = risk.get("prohibited_conditions", [])
    if risk_prohibited:
        for pc in risk_prohibited:
            cond = pc.get("condition", "") if isinstance(pc, dict) else str(pc)
            if cond and cond not in boundary["out_of_scope"]:
                boundary["out_of_scope"].append(cond)

    # Risk items, risk matrix, HITL rules: from risk_identify
    risk_items = list(risk.get("risk_items", []))
    risk_matrix = list(risk.get("risk_matrix", []))
    hitl_rules = list(risk.get("hitl_rules", []))

    # Risk level and HITL level: normalized from risk_identify
    risk_level = normalize_risk_level(risk.get("risk_level", "L1"))
    hitl_level = normalize_hitl_level(risk.get("hitl_level", "none"), risk_level=risk_level)

    # Prohibited conditions and fatal errors: from risk_identify
    prohibited_conditions = list(risk.get("prohibited_conditions", []))
    fatal_errors = list(risk.get("fatal_errors", []))

    # Audit requirements: merge document_parse + risk_identify
    audit_requirements = list(parsed.get("audit_requirements", []))
    risk_audit = risk.get("audit_requirements", [])
    if isinstance(risk_audit, list):
        for req in risk_audit:
            if req and req not in audit_requirements:
                audit_requirements.append(req)

    # Evidence refs: Phase A refs + risk refs (dedup union)
    evidence_refs = list(scenario_deconstruction.get("evidence_refs", []))
    for ref in risk.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)

    # To-confirm: merge risk to_confirm + vision_results to_confirm + vision_parse to_confirm
    to_confirm = list(risk.get("to_confirm", []))
    for vr in vision_results:
        to_confirm.extend(vr.get("to_confirm", []))
    for tc in vision.get("to_confirm", []):
        if tc not in to_confirm:
            to_confirm.append(tc)

    # Confidence: from risk_identify
    confidence = risk.get("confidence", {
        "overall": 0.5,
        "field_scores": {
            "boundary": 0.5,
            "process_nodes": 0.5,
            "risk_items": 0.5,
            "hitl_rules": 0.5,
            "audit_requirements": 0.5,
        },
    })

    # Review status: always draft on skill invocation
    review_status = "draft"

    # P2-boundary: propagate boundary_flag from risk_identify output
    boundary_flag = risk.get("boundary_flag", False)

    # P1-1: propagate risk_confidence from risk_identify output (additive overlay)
    risk_confidence = risk.get("risk_confidence")

    phase_b: dict = {
        "boundary": boundary,
        "risk_items": risk_items,
        "risk_level": risk_level,
        "hitl_level": hitl_level,
        "risk_matrix": risk_matrix,
        "hitl_rules": hitl_rules,
        "audit_requirements": audit_requirements,
        "prohibited_conditions": prohibited_conditions,
        "fatal_errors": fatal_errors,
        "evidence_refs": evidence_refs,
        "to_confirm": to_confirm,
        "confidence": confidence,
        "boundary_flag": boundary_flag,
        "review_status": review_status,
    }
    if risk_confidence is not None and isinstance(risk_confidence, dict):
        phase_b["risk_confidence"] = risk_confidence
    return phase_b


def _build_stage_one_summary(*, goal: str, stage_name: str, tool_payload: dict, vision_results: list[dict]) -> dict:
    """Build scenario_summary from evidence-driven tool outputs.

    Thin wrapper over Phase A (``_build_scenario_deconstruction``) and Phase B
    (``_build_risk_grading``). The merged dict keeps the same key set, nesting,
    and value types as before the split — ``{**phase_a, **phase_b}`` with Phase B's
    enriched ``boundary`` overriding Phase A's. Node binding runs after merge.
    """
    phase_a = _build_scenario_deconstruction(
        goal=goal, stage_name=stage_name, tool_payload=tool_payload, vision_results=vision_results
    )
    phase_b = _build_risk_grading(
        scenario_deconstruction=phase_a,
        goal=goal,
        stage_name=stage_name,
        tool_payload=tool_payload,
        vision_results=vision_results,
    )
    return _bind_stage_one_risk_and_hitl_to_nodes({**phase_a, **phase_b})


def _build_stage_two_summary(*, goal: str, stage_name: str, tool_payload: dict, previous_stage_result: dict | None) -> dict:
    """Build stage2_summary from value_model and sla_target tool outputs.

    Normalizes enums and propagates risk context from Stage 1.
    """
    value = tool_payload.get("value_model", {})
    sla = tool_payload.get("sla_target", {})

    # Propagate risk_level from Stage 1.
    prev = previous_stage_result or {}
    scenario_summary = prev.get("scenario_summary", {})
    risk_level = scenario_summary.get("risk_level", "L1")

    # Normalize implementation_tax
    impl_tax_raw = value.get("implementation_tax", "")
    impl_tax = impl_tax_raw
    try:
        impl_tax = normalize_implementation_tax(impl_tax_raw, risk_level=risk_level)
    except ValueError:
        impl_tax = "medium"  # safe default

    # Normalize target_sla
    target_sla_raw = sla.get("target_sla")
    target_sla = target_sla_raw
    try:
        target_sla = normalize_target_sla(target_sla_raw)
    except ValueError:
        target_sla = 95.0  # safe default

    # Stability
    stability_raw = sla.get("stability", "")
    stability = stability_raw if stability_raw in {"confirmed", "needs_confirmation", "unstable"} else "needs_confirmation"

    # Evidence refs: union of tool refs + Stage 1 refs
    evidence_refs = list(value.get("evidence_refs", []))
    for ref in sla.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    # Propagate Stage 1 evidence
    for ref in scenario_summary.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)

    # Review status
    review_status = "draft"

    summary = {
        "implementation_tax": impl_tax,
        "target_sla": target_sla,
        "stability": stability,
        "risk_level": risk_level,
        "evidence_refs": evidence_refs,
        "review_status": review_status,
        "estimated_value": value.get("estimated_value", ""),
        "stage1_risk_level": value.get("stage1_risk_level", risk_level),
        "stage1_hitl_level": value.get("stage1_hitl_level", scenario_summary.get("hitl_level", "none")),
    }
    for field in [
        "implementation_tax_items",
        "implementation_tax_total",
        "gross_benefit",
        "ai_operating_cost",
        "net_value",
        "net_value_formula",
        "benefit_items",
        "sensitivity_results",
        "break_even_conditions",
        "required_supplements",
        "assumption_refs",
    ]:
        if field in value:
            summary[field] = value.get(field)
    if "target_sla_components" in sla:
        summary["target_sla_components"] = sla.get("target_sla_components")
    if value.get("review_status"):
        summary["review_status"] = value.get("review_status")

    # Propagate risk_confidence from Stage 1 (additive)
    risk_confidence = scenario_summary.get("risk_confidence")
    if risk_confidence is not None and isinstance(risk_confidence, dict):
        summary["risk_confidence"] = risk_confidence

    return summary


def _build_stage_three_summary(*, goal: str, stage_name: str, tool_payload: dict, previous_stage_result: dict | None) -> dict:
    """Build stage3_summary from sample_score and actual_sla_summary tool outputs.

    Normalizes fields and propagates risk context from Stage 1.
    """
    sample = tool_payload.get("sample_score", {})
    sla = tool_payload.get("actual_sla_summary", {})

    # Stage 3 receives the Stage 2 result directly. Retain a Stage 1 fallback
    # for older records created before stage-specific prerequisite contracts.
    prev = previous_stage_result or {}
    scenario_summary = prev.get("scenario_summary", {})
    stage2_summary = prev.get("stage2_summary", {})
    risk_level = stage2_summary.get("risk_level") or scenario_summary.get("risk_level", "L1")

    # Normalize sample_size
    sample_size_raw = sample.get("sample_size")
    sample_size = sample_size_raw
    try:
        sample_size = normalize_sample_size(sample_size_raw)
    except ValueError:
        sample_size = 12  # safe default

    # Low score samples
    low_score_samples_raw = sample.get("low_score_samples", 0)
    low_score_samples = 0
    if isinstance(low_score_samples_raw, int) and 0 <= low_score_samples_raw <= sample_size:
        low_score_samples = low_score_samples_raw

    # Normalize gap_to_target_pct
    gap_raw = sla.get("gap_to_target_pct")
    gap = gap_raw
    try:
        gap = normalize_gap_to_target_pct(gap_raw)
    except ValueError:
        gap = 0  # safe default

    # Normalize actual_sla
    actual_sla_raw = sla.get("actual_sla")
    actual_sla = actual_sla_raw
    try:
        actual_sla = normalize_actual_sla(actual_sla_raw)
    except ValueError:
        actual_sla = 90.0  # safe default

    # Stability
    stability_raw = sla.get("stability", "")
    stability = stability_raw if stability_raw in {"confirmed", "needs_confirmation", "unstable"} else "needs_confirmation"

    # Target SLA from Stage 2 (if available in previous_stage_result)
    target_sla = None
    if isinstance(stage2_summary, dict):
        target_sla = stage2_summary.get("target_sla")
    if target_sla is None:
        target_sla = sla.get("target_sla")  # from actual_sla_summary tool

    # Evidence refs
    evidence_refs = list(sample.get("evidence_refs", []))
    for ref in sla.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    for ref in scenario_summary.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)

    review_status = "draft"

    summary = {
        "sample_size": sample_size,
        "low_score_samples": low_score_samples,
        "gap_to_target_pct": gap,
        "actual_sla": actual_sla,
        "target_sla": target_sla,
        "stability": stability,
        "risk_level": risk_level,
        "evidence_refs": evidence_refs,
        "review_status": review_status,
        "score_distribution": sample.get("score_distribution", {}),
    }

    # Propagate risk_confidence from Stage 1 (additive)
    risk_confidence = scenario_summary.get("risk_confidence")
    if risk_confidence is not None and isinstance(risk_confidence, dict):
        summary["risk_confidence"] = risk_confidence

    return summary


def _build_stage_four_summary(*, goal: str, stage_name: str, tool_payload: dict, previous_stage_result: dict | None) -> dict:
    """Build stage4_summary from evidence_bundle, report_generate, and export_bundle tool outputs.

    Normalizes enums and propagates risk context from Stage 1.
    """
    evidence = tool_payload.get("evidence_bundle", {})
    report = tool_payload.get("report_generate", {})
    export = tool_payload.get("export_bundle", {})

    # Propagate risk_level from Stage 1
    prev = previous_stage_result or {}
    scenario_summary = prev.get("scenario_summary", {})
    risk_level = scenario_summary.get("risk_level", "L1")

    # Normalize bundle_status
    bundle_status_raw = evidence.get("bundle_status", "")
    bundle_status = bundle_status_raw if bundle_status_raw in BUNDLE_STATUSES else "draft"

    # Evidence count
    evidence_count = evidence.get("evidence_count", 0)
    if not isinstance(evidence_count, int):
        evidence_count = 0

    # Normalize report_status
    report_status_raw = report.get("report_status", "")
    report_status = report_status_raw if report_status_raw in REPORT_STATUSES else "draft"

    # Decision card
    decision_card = report.get("decision_card")
    if not isinstance(decision_card, dict):
        decision_card = None

    # Export readiness
    export_ready = export.get("export_ready", False)

    # Evidence refs: union of all tool refs + Stage 1 refs
    evidence_refs = list(evidence.get("evidence_refs", []))
    for ref in report.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    for ref in export.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    for ref in scenario_summary.get("evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)

    # Report sections
    sections = report.get("sections", [])

    # Gaps from evidence_bundle
    gaps = evidence.get("gaps", [])

    # Blocking issues from export_bundle
    blocking_issues = export.get("blocking_issues", [])

    review_status = "draft"

    summary = {
        "bundle_status": bundle_status,
        "evidence_count": evidence_count,
        "report_status": report_status,
        "decision_card": decision_card,
        "export_ready": export_ready,
        "risk_level": risk_level,
        "evidence_refs": evidence_refs,
        "sections": sections,
        "gaps": gaps,
        "blocking_issues": blocking_issues,
        "review_status": review_status,
    }

    # Propagate risk_confidence from Stage 1 (additive)
    risk_confidence = scenario_summary.get("risk_confidence")
    if risk_confidence is not None and isinstance(risk_confidence, dict):
        summary["risk_confidence"] = risk_confidence

    return summary


def _merge_stage_one_llm_candidate(*, fallback_summary: dict, candidate: object) -> tuple[dict, list[dict], str]:
    if not isinstance(candidate, dict):
        return fallback_summary, [], "fallback"

    merged = {**fallback_summary, **candidate}
    issues: list[dict] = []
    try:
        merged["risk_level"] = normalize_risk_level(merged.get("risk_level", fallback_summary.get("risk_level")))
    except ValueError as exc:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "risk_level",
            "severity": "high",
            "message": str(exc),
            "suggested_action": "Use fallback risk_level",
        })
        merged["risk_level"] = fallback_summary.get("risk_level", "L1")

    try:
        merged["hitl_level"] = normalize_hitl_level(
            merged.get("hitl_level", fallback_summary.get("hitl_level")),
            risk_level=merged.get("risk_level"),
        )
    except ValueError as exc:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "hitl_level",
            "severity": "high",
            "message": str(exc),
            "suggested_action": "Use fallback hitl_level",
        })
        merged["hitl_level"] = normalize_hitl_level(fallback_summary.get("hitl_level", "none"), risk_level=merged.get("risk_level"))

    validation_issues = validate_stage1_summary(merged)
    if validation_issues:
        issues.extend(validation_issues)
        return fallback_summary, issues, "fallback"
    return merged, issues, "llm"


def _selective_merge_stage_one_llm_candidate(
    *, fallback_summary: dict, candidate: object,
) -> tuple[dict, list[dict], str]:
    """Selectively merge LLM candidate fields into the fallback summary.

    Unlike the deprecated all-or-nothing ``_merge_stage_one_llm_candidate``,
    this function evaluates each candidate field independently:
    - Enum fields (risk_level, hitl_level) are normalized; if normalization
      fails the fallback value is kept.
    - List fields (risk_items, hitl_rules, etc.) are adopted when the
      candidate's substantive-item ratio is >= the fallback's.
    - Scalar fields are adopted when ``_is_substantive()`` returns True.
    - After per-field merging, ``validate_stage1_summary()`` is run on the
      whole result.  Any field causing a **high** severity issue is reverted
      to the fallback value.

    Returns ``(merged_summary, issues, source_label)`` where *source_label*
    is ``"llm"`` if at least one candidate field was adopted, else ``"fallback"``.
    """
    import warnings

    if not isinstance(candidate, dict):
        return fallback_summary, [], "fallback"

    merged: dict = dict(fallback_summary)
    issues: list[dict] = []
    candidate_fields_adopted: int = 0

    # ── Enum fields: normalize, fall back on error ──────────────────

    # risk_level
    cand_risk = candidate.get("risk_level")
    if cand_risk is not None:
        try:
            merged["risk_level"] = normalize_risk_level(cand_risk)
            candidate_fields_adopted += 1
        except ValueError as exc:
            issues.append({
                "issue_type": "invalid_enum",
                "field": "risk_level",
                "severity": "high",
                "message": str(exc),
                "suggested_action": "Use fallback risk_level",
            })

    # hitl_level — depends on resolved risk_level
    cand_hitl = candidate.get("hitl_level")
    if cand_hitl is not None:
        try:
            merged["hitl_level"] = normalize_hitl_level(
                cand_hitl,
                risk_level=merged.get("risk_level"),
            )
            candidate_fields_adopted += 1
        except ValueError as exc:
            issues.append({
                "issue_type": "invalid_enum",
                "field": "hitl_level",
                "severity": "high",
                "message": str(exc),
                "suggested_action": "Use fallback hitl_level",
            })

    # ── List fields: adopt when candidate has better substantive ratio ──

    _LIST_FIELDS = (
        "risk_items", "risk_matrix", "hitl_rules", "participants",
        "process_nodes", "audit_requirements", "evidence_refs",
        "edges", "main_path",
    )

    for field in _LIST_FIELDS:
        cand_val = candidate.get(field)
        fb_val = fallback_summary.get(field)
        if cand_val is None:
            continue  # candidate doesn't provide this field
        if not isinstance(cand_val, list):
            # candidate provided it but wrong type — skip
            issues.append({
                "issue_type": "type_mismatch",
                "field": field,
                "severity": "medium",
                "message": f"Expected list for {field}, got {type(cand_val).__name__}",
                "suggested_action": "Use fallback value",
            })
            continue

        # Compute substantive ratio for both
        cand_ratio = (
            sum(1 for item in cand_val if _is_substantive(item)) / len(cand_val)
            if cand_val else 0.0
        )
        if isinstance(fb_val, list) and fb_val:
            fb_ratio = sum(1 for item in fb_val if _is_substantive(item)) / len(fb_val)
        else:
            fb_ratio = 0.0

        if cand_ratio >= fb_ratio:
            merged[field] = cand_val
            candidate_fields_adopted += 1

    # ── Scalar / dict fields: adopt when substantive ───────────────

    _SCALAR_FIELDS = (
        "scenario_name", "boundary", "risk_confidence",
        "boundary_flag", "error_amplification_path",
    )

    for field in _SCALAR_FIELDS:
        cand_val = candidate.get(field)
        if cand_val is None:
            continue
        if _is_substantive(cand_val):
            merged[field] = cand_val
            candidate_fields_adopted += 1

    # ── Post-merge validation: revert high-severity fields ──────────

    validation_issues = validate_stage1_summary(merged)
    if validation_issues:
        issues.extend(validation_issues)
        # Revert fields causing high-severity issues back to fallback.
        # Validation issues report indexed positions like "main_path[0->1]"
        # or "edges[3].from" rather than the top-level key, so map them back
        # via split("[")[0]. edges/main_path are a coupled IR over
        # process_nodes — reverting to fallback's copy can dangle against the
        # merged process_nodes (whose node_ids may come from the LLM
        # candidate), so re-derive both from the merged process_nodes.
        high_fields = {
            iss.get("field") for iss in validation_issues
            if iss.get("severity") == "high" and iss.get("field")
        }
        for field in high_fields:
            top = field.split("[")[0]
            if top in {"main_path", "edges"}:
                rederived = _build_edges_from_nodes(merged.get("process_nodes", []))
                merged["edges"] = rederived.get("edges", [])
                merged["main_path"] = rederived.get("main_path", [])
                continue
            if top in fallback_summary:
                merged[top] = fallback_summary[top]
            # Re-normalize enums after reversion
            if top == "risk_level":
                try:
                    merged["risk_level"] = normalize_risk_level(merged["risk_level"])
                except ValueError:
                    merged["risk_level"] = fallback_summary.get("risk_level", "L1")
            if top == "hitl_level":
                try:
                    merged["hitl_level"] = normalize_hitl_level(
                        merged.get("hitl_level", fallback_summary.get("hitl_level", "none")),
                        risk_level=merged.get("risk_level"),
                    )
                except ValueError:
                    merged["hitl_level"] = normalize_hitl_level(
                        fallback_summary.get("hitl_level", "none"),
                        risk_level=merged.get("risk_level"),
                    )

        # Re-validate after reversion to update issues list
        post_revert_issues = validate_stage1_summary(merged)
        # Replace the previous validation_issues with the post-revert set
        issues = [i for i in issues if i.get("severity") != "high" or i.get("field") not in high_fields]
        issues.extend(post_revert_issues)

    source_label = "llm" if candidate_fields_adopted > 0 else "fallback"
    return merged, issues, source_label


def _validate_previous_stage_result_for_skill(*, skill: SkillDefinition, previous_stage_result: dict | None) -> list[dict]:
    if skill.name == "scenario_risk_skill":
        return []  # Stage 1 has no prerequisite

    issues: list[dict] = []
    if previous_stage_result is None:
        return [
            {
                "code": "previous_stage_result_missing",
                "message": "阶段二及后续执行需要先完成上一阶段结果。",
                "severity": "high",
            }
        ]

    required_summary_by_skill = {
        "value_modeling_skill": "scenario_summary",
        "probe_validation_skill": "stage2_summary",
        "evidence_decision_skill": "stage3_summary",
        "report_generation_skill": "stage3_summary",
    }
    required_summary = required_summary_by_skill.get(skill.name)
    previous_summary = previous_stage_result.get(required_summary) if required_summary else None
    if not isinstance(previous_summary, dict) or not previous_summary:
        issues.append(
            {
                "code": "previous_stage_summary_missing",
                "message": "上一阶段结果缺少 {0}，无法执行当前阶段。".format(required_summary),
                "severity": "high",
            }
        )
    return issues


def _collect_previous_stage_warnings(*, skill: SkillDefinition, previous_stage_result: dict | None) -> list[dict]:
    """Collect warnings about the previous stage result for skills that depend on it.

    Stage 2 (value_modeling_skill) → validates Stage 1 scenario_summary.
    Stage 3 (probe_validation_skill) → validates Stage 2 stage2_summary.
    Stage 4 (evidence_decision_skill / report_generation_skill) → validates Stage 3 stage3_summary.
    """
    if not previous_stage_result:
        return []

    # Stage 1 has no prerequisite
    if skill.name == "scenario_risk_skill":
        return []

    warnings: list[dict] = []

    if skill.name == "value_modeling_skill":
        # Stage 2 depends on Stage 1
        scenario_summary = previous_stage_result.get("scenario_summary")
        if isinstance(scenario_summary, dict) and scenario_summary:
            validation_issues = validate_stage1_summary(scenario_summary)
            if validation_issues:
                warnings.append(
                    {
                        "code": "previous_stage_validation_issues",
                        "message": "上一阶段 scenario_summary 存在待确认或校验问题，阶段二结果需结合这些问题复核。",
                        "issues": validation_issues,
                    }
                )
        stage1_validation = previous_stage_result.get("stage1_validation", {})
        if isinstance(stage1_validation, dict) and stage1_validation.get("issues"):
            warnings.append(
                {
                    "code": "previous_stage_reported_issues",
                    "message": "上一阶段结果记录了校验问题，阶段二结果需人工复核。",
                    "issues": stage1_validation.get("issues", []),
                }
            )

    elif skill.name == "probe_validation_skill":
        # Stage 3 depends on Stage 2
        stage2_summary = previous_stage_result.get("stage2_summary")
        if isinstance(stage2_summary, dict) and stage2_summary:
            validation_issues = validate_stage2_summary(stage2_summary, previous_stage_result=previous_stage_result)
            if validation_issues:
                warnings.append(
                    {
                        "code": "previous_stage_validation_issues",
                        "message": "阶段二 stage2_summary 存在待确认或校验问题，阶段三结果需结合这些问题复核。",
                        "issues": validation_issues,
                    }
                )
        stage2_validation = previous_stage_result.get("stage2_validation", {})
        if isinstance(stage2_validation, dict) and stage2_validation.get("issues"):
            warnings.append(
                {
                    "code": "previous_stage_reported_issues",
                    "message": "阶段二结果记录了校验问题，阶段三结果需人工复核。",
                    "issues": stage2_validation.get("issues", []),
                }
            )

    elif skill.name in {"evidence_decision_skill", "report_generation_skill"}:
        # Stage 4 depends on Stage 3
        stage3_summary = previous_stage_result.get("stage3_summary")
        if isinstance(stage3_summary, dict) and stage3_summary:
            validation_issues = validate_stage3_summary(stage3_summary, previous_stage_result=previous_stage_result)
            if validation_issues:
                warnings.append(
                    {
                        "code": "previous_stage_validation_issues",
                        "message": "阶段三 stage3_summary 存在待确认或校验问题，阶段四结果需结合这些问题复核。",
                        "issues": validation_issues,
                    }
                )
        stage3_validation = previous_stage_result.get("stage3_validation", {})
        if isinstance(stage3_validation, dict) and stage3_validation.get("issues"):
            warnings.append(
                {
                    "code": "previous_stage_reported_issues",
                    "message": "阶段三结果记录了校验问题，阶段四结果需人工复核。",
                    "issues": stage3_validation.get("issues", []),
                }
            )

    return warnings


def _collect_tool_warnings(tool_result_items: list[dict]) -> list[dict]:
    warnings: list[dict] = []
    for item in tool_result_items:
        tool_name = str(item.get("name", ""))
        for index, warning in enumerate(item.get("warnings", [])):
            warnings.append(
                {
                    "code": "tool_warning",
                    "message": str(warning),
                    "tool_name": tool_name,
                    "index": index,
                }
            )
    return warnings


def list_skills(stage_id: Optional[str] = None) -> list[SkillDefinition]:
    if stage_id is not None:
        _ = get_stage(stage_id)
    return registry_list_skills(stage_id)


def _build_stage_result_from_base(
    *,
    base_result: StageResult,
    run_id: str,
) -> StageResult:
    return StageResult(
        id=f"stage-result-{uuid4().hex[:8]}",
        project_id=base_result.project_id,
        stage_id=base_result.stage_id,
        version_id=f"sv-{uuid4().hex[:8]}",
        base_version_id=base_result.version_id,
        run_id=run_id,
        status="draft",
        input_file_ids=list(base_result.input_file_ids),
        evidence_item_ids=list(base_result.evidence_item_ids),
        model_config=dict(base_result.model_config),
        skill_versions=dict(base_result.skill_versions),
        autoresearch_record_ids=list(base_result.autoresearch_record_ids),
        confirmation_ids=list(base_result.confirmation_ids),
        result_payload=dict(base_result.result_payload),
        summary=base_result.summary,
    )


def invoke_skill(*, skill_name: str, project_id: str, stage_id: str, run_id: Optional[str], goal: str) -> dict:
    stage = get_stage(stage_id)
    if stage.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage does not belong to project")
    try:
        skill = get_skill_by_name(skill_name)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")

    if not stage_id.endswith(skill.stage_suffix):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill does not match stage")

    if run_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill invocation requires run_id")
    run = get_run(run_id)
    if run.project_id != project_id or run.stage_id != stage_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run does not match project or stage")

    append_run_event(
        run,
        "run.skill_started",
        {
            "skill_name": skill.name,
            "tool_names": skill.allowed_tools,
            "subagent_names": skill.allowed_subagents,
            "source": "skill.invoke",
        },
    )

    latest_result = get_latest_stage_result(stage_id)
    if latest_result is None:
        # Auto-create a draft StageResult for the first run on this stage
        snapshot = settings_snapshot(project_id, stage_id, config_version_id=run.config_version_id)
        latest_result = StageResult(
            id=f"stage-result-{uuid4().hex[:8]}",
            project_id=project_id,
            stage_id=stage_id,
            version_id=f"sv-{uuid4().hex[:8]}",
            base_version_id=None,
            run_id=run_id,
            status="draft",
            model_config=snapshot["model_config"],
            skill_versions=snapshot["skill_versions"],
            result_payload={"goal": goal},
            summary="Auto-created draft stage result for first skill invocation.",
        )
        save_stage_result(latest_result)

    enabled_tools, enabled_subagents = filter_tools_for_skill(
        project_id=project_id,
        stage_id=stage_id,
        skill_name=skill.name,
        declared_tools=skill.allowed_tools,
        declared_subagents=skill.allowed_subagents,
        config_version_id=run.config_version_id,
    )
    append_run_event(
        run,
        "run.skill_filtered",
        {
            "skill_name": skill.name,
            "enabled_tools": enabled_tools,
            "enabled_subagents": enabled_subagents,
            "source": "settings.filter",
        },
    )

    evidence_items = list_evidence(project_id)
    vision_results = load_project_vision_results(project_id)

    # For Stage 2+: load previous stage result and pass to tools
    previous_stage_result = None
    if skill.stage_suffix != "stage-1":
        # Find the immediately preceding stage
        from src.apps.api.app.services.project_service import list_stages
        stages = list_stages(project_id)
        current_stage_idx = next((i for i, s in enumerate(stages) if s.id == stage_id), -1)
        if current_stage_idx > 0:
            prev_stage = stages[current_stage_idx - 1]
            prev_result = get_latest_stage_result(prev_stage.id)
            if prev_result is not None:
                previous_stage_result = dict(prev_result.result_payload)
    previous_stage_issues = _validate_previous_stage_result_for_skill(skill=skill, previous_stage_result=previous_stage_result)
    if previous_stage_issues:
        append_run_event(
            run,
            "run.harness_decision",
            {
                "skill_name": skill.name,
                "decision_source": "precondition",
                "should_continue": False,
                "confidence": 1.0,
                "summary": "上一阶段结果未满足当前阶段执行前置条件。",
                "issues": previous_stage_issues,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "previous_stage_result_invalid",
                "message": "上一阶段结果未满足当前阶段执行前置条件。",
                "issues": previous_stage_issues,
            },
        )

    current_result = latest_result
    if latest_result.status == "locked" or latest_result.run_id != run_id:
        current_result = _build_stage_result_from_base(base_result=latest_result, run_id=run_id)
    snapshot = settings_snapshot(project_id, stage_id, config_version_id=run.config_version_id)
    current_result.model_config = {
        **dict(current_result.model_config),
        **snapshot["model_config"],
    }
    for skill_name_key, version_value in snapshot["skill_versions"].items():
        current_result.skill_versions.setdefault(skill_name_key, version_value)
    current_result.result_payload.setdefault("config_version_id", snapshot["config_version_id"])
    current_result.result_payload.setdefault("prompt_refs", snapshot["prompt_refs"])
    # L1-A: copy prompt hash/version audit fields onto the StageResult so that
    # later A/B comparisons can detect prompt drift between runs.
    import hashlib as _hashlib
    for prompt_id, body in (snapshot.get("prompt_bodies") or {}).items():
        current_result.prompt_hashes.setdefault(prompt_id, _hashlib.sha256(body.encode("utf-8")).hexdigest())
    for ref in snapshot.get("prompt_refs") or []:
        prompt_id = ref.get("id", "")
        if prompt_id:
            current_result.prompt_versions.setdefault(prompt_id, ref.get("version", "v1"))

    evidence_refs = [item.id for item in evidence_items]
    skill_version = snapshot["skill_versions"].get(skill.name, "")
    llm_runtime = dict((snapshot.get("openai_compatible_models") or {}).get("general", {}))
    # The default project profile carries a display model name even when it
    # has no endpoint credentials. Do not let that placeholder override a
    # complete AGENT_LLM_* configuration used by the stage runtime.
    if llm_runtime.get("base_url") and llm_runtime.get("api_key"):
        llm_client = HarnessLLMClient(
            base_url=llm_runtime["base_url"],
            api_key=llm_runtime["api_key"],
            model=llm_runtime.get("model_name") or None,
        )
    else:
        llm_client = HarnessLLMClient()
    if llm_client.required and not llm_client.is_configured():
        llm_status = llm_client.status(mode="required_missing")
        append_run_event(
            run,
            "run.harness_fallback",
            {
                "code": "llm_required_missing",
                "message": "LLM 已设为必需，但当前未配置完整 AGENT_LLM_*，未执行工具。",
                "missing": llm_status.get("missing", []),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "llm_required_missing",
                "message": "LLM 已设为必需，但当前未配置完整 AGENT_LLM_*，未执行工具。",
                "missing": llm_status.get("missing", []),
            },
        )
    harness_version = (snapshot.get("harness_versions_by_stage") or {}).get(stage_id) or DEFAULT_AGENT_HARNESS_VERSION
    current_result.model_config["harness_version"] = harness_version
    harness_request = HarnessRequest(
        project_id=project_id,
        stage_id=stage_id,
        run_id=run_id,
        goal=goal,
        stage_name=stage.name,
        skill_name=skill.name,
        skill_version=skill_version,
        skill_description=skill.description,
        allowed_tools=list(skill.allowed_tools),
        enabled_tools=list(enabled_tools),
        allowed_subagents=list(skill.allowed_subagents),
        enabled_subagents=list(enabled_subagents),
        evidence_items=[{"id": item.id, "snippet": item.snippet, "source_type": item.source_type, "name": item.name} for item in evidence_items],
        vision_results=vision_results,
        previous_stage_result=previous_stage_result,
        config_version_id=snapshot["config_version_id"],
        prompt_templates=dict(snapshot.get("prompt_bodies") or {}),
        prompt_versions={
            str(ref.get("id", "")): str(ref.get("version", "v1"))
            for ref in snapshot.get("prompt_refs") or []
            if ref.get("id")
        },
        prompt_hashes=dict(current_result.prompt_hashes),
        options={
            "llm_client": llm_client,
            "auto_run_condition": next(
                (
                    profile.get("auto_run_condition")
                    for profile in snapshot.get("stage_skill_profiles", [])
                    if profile.get("stage_id") == stage_id
                ),
                None,
            )
        },
    )
    harness_result = get_harness_provider(harness_version).run(harness_request)
    harness_state = harness_result.to_legacy_state()
    harness_payload = serialize_harness_payload(harness_state)
    current_result.model_config["harness_graph_version"] = harness_payload.get("graph_version")
    plan_payload = dict(harness_state.get("plan", {}))
    decision_payload = dict(harness_state.get("decision", {}))
    planned_tool_names = list(plan_payload.get("tool_names", []))
    tool_payload = dict(harness_state.get("tool_results", {}))
    tool_result_items = [dict(item) for item in harness_state.get("tool_result_items", [])]
    tool_result_by_name = {str(item.get("name", "")): item for item in tool_result_items}
    tool_failures = [
        {"tool_name": str(item.get("tool_name", "")), "detail": str(item.get("detail", "Tool failed"))}
        for item in harness_state.get("tool_failures", [])
    ]
    tool_failure_by_name = {item["tool_name"]: item for item in tool_failures}
    llm_status = dict(harness_payload.get("llm_status", {}))
    warnings = []
    previous_stage_warnings = _collect_previous_stage_warnings(skill=skill, previous_stage_result=previous_stage_result)
    warnings.extend(previous_stage_warnings)
    if llm_status.get("configured") is False:
        warnings.append({"code": "llm_not_configured", "message": NO_LLM_FALLBACK_MESSAGE})
        append_run_event(
            run,
            "run.harness_fallback",
            {
                "code": "llm_not_configured",
                "message": NO_LLM_FALLBACK_MESSAGE,
                "missing": llm_status.get("missing", []),
            },
        )
    tool_warnings = _collect_tool_warnings(tool_result_items)
    warnings.extend(tool_warnings)
    if tool_warnings:
        decision_payload["notes"] = list(decision_payload.get("notes", [])) + [
            "{0}: {1}".format(item.get("tool_name", ""), item.get("message", "")) for item in tool_warnings
        ]
        harness_payload["decision"] = decision_payload
    if previous_stage_warnings:
        decision_payload["notes"] = list(decision_payload.get("notes", [])) + [
            str(item.get("message", "")) for item in previous_stage_warnings
        ]
        harness_payload["decision"] = decision_payload
    append_run_event(
        run,
        "run.harness_planned",
        {
            "skill_name": skill.name,
            "plan_source": plan_payload.get("source", "fallback"),
            "tool_names": planned_tool_names,
            "graph_version": harness_payload.get("graph_version"),
            "harness_version": harness_payload.get("harness_version"),
        },
    )
    for tool_name in planned_tool_names:
        append_run_event(run, "run.tool_started", {"skill_name": skill.name, "tool_name": tool_name})
        tool_result_item = tool_result_by_name.get(tool_name)
        if tool_result_item is not None:
            append_run_event(
                run,
                "run.tool_completed",
                {
                    "skill_name": skill.name,
                    "tool_name": tool_name,
                    "summary": tool_result_item.get("summary", ""),
                },
            )
        else:
            failure = tool_failure_by_name.get(tool_name, {"detail": "Tool failed"})
            append_run_event(
                run,
                "run.tool_completed",
                {
                    "skill_name": skill.name,
                    "tool_name": tool_name,
                    "summary": "Tool failed: {0}".format(failure.get("detail", "Tool failed")),
                    "status": "failed",
                },
            )
    append_run_event(
        run,
        "run.harness_decision",
        {
            "skill_name": skill.name,
            "plan_source": plan_payload.get("source", "fallback"),
            "decision_source": decision_payload.get("source", "fallback"),
            "should_continue": bool(decision_payload.get("should_continue", False)),
            "confidence": float(decision_payload.get("confidence", 0.0)),
            "summary": decision_payload.get("summary", ""),
            "harness_version": harness_payload.get("harness_version"),
        },
    )

    tool_results = tool_result_items
    persisted_decision = {
        "should_continue": bool(decision_payload.get("should_continue", False)),
        "requires_human": bool(decision_payload.get("requires_human", harness_state.get("requires_human", False))),
        "summary": decision_payload.get("summary", ""),
        "confidence": float(decision_payload.get("confidence", 0.0)),
        "notes": list(decision_payload.get("notes", [])),
        "source": decision_payload.get("source", "fallback"),
        "3d_alignment": dict(decision_payload.get("3d_alignment", {})),
    }
    if tool_failures:
        current_result.status = "draft"
        current_result.result_payload = {
            **dict(current_result.result_payload),
            "skill_name": skill.name,
            "tool_failures": tool_failures,
            "harness": {
                **harness_payload,
                "plan": {
                    "tool_names": planned_tool_names,
                    "reasoning": plan_payload.get("reasoning", ""),
                    "source": plan_payload.get("source", "fallback"),
                },
                "decision": persisted_decision,
            },
        }
        current_result.summary = "Skill execution completed with tool failures."
        current_result.updated_at = utcnow()
        save_stage_result(current_result)
        create_execution_log(
            project_id=project_id,
            action="skill.invoked",
            resource_type="stage_result",
            resource_id=current_result.id,
            run_id=run_id,
            details={"skill_name": skill.name, "tool_names": skill.allowed_tools, "tool_failures": tool_failures},
        )
        return {
            "skill_name": skill.name,
            "stage_id": stage_id,
            "project_id": project_id,
            "summary": "Skill execution completed with tool failures.",
            "tool_names": list(skill.allowed_tools),
            "subagent_names": list(skill.allowed_subagents),
            "enabled_tools": enabled_tools,
            "enabled_subagents": enabled_subagents,
            "config_version_id": snapshot["config_version_id"],
            "goal": goal,
            "stage_result_id": current_result.id,
            "report_id": None,
            "tool_results": tool_results,
            "warnings": warnings,
        }

    previous_result = latest_result if current_result.id != latest_result.id else StageResult(
        id=latest_result.id,
        project_id=latest_result.project_id,
        stage_id=latest_result.stage_id,
        version_id=latest_result.version_id,
        base_version_id=latest_result.base_version_id,
        run_id=latest_result.run_id,
        status=latest_result.status,
        input_file_ids=list(latest_result.input_file_ids),
        evidence_item_ids=list(latest_result.evidence_item_ids),
        model_config=dict(latest_result.model_config),
        skill_versions=dict(latest_result.skill_versions),
        autoresearch_record_ids=list(latest_result.autoresearch_record_ids),
        confirmation_ids=list(latest_result.confirmation_ids),
        result_payload=dict(latest_result.result_payload),
        summary=latest_result.summary,
        created_at=latest_result.created_at,
        updated_at=latest_result.updated_at,
        locked_at=latest_result.locked_at,
    )
    current_result.result_payload = {
        **dict(current_result.result_payload),
        "skill_name": skill.name,
        "skill_summary": "{0} 已生成阶段处理摘要。".format(skill.description),
        "tool_results": tool_payload,
        "harness": {
            **harness_payload,
            "plan": {
                "tool_names": planned_tool_names,
                "reasoning": plan_payload.get("reasoning", ""),
                "source": plan_payload.get("source", "fallback"),
            },
            "decision": persisted_decision,
        },
    }
    if skill.name == "scenario_risk_skill":
        fallback_summary = _build_stage_one_summary(
            goal=goal,
            stage_name=stage.name,
            tool_payload=tool_payload,
            vision_results=vision_results,
        )
        synthesized_payload = dict(harness_state.get("synthesized_payload", {}))
        scenario_summary, llm_synthesis_issues, synthesis_source = _selective_merge_stage_one_llm_candidate(
            fallback_summary=fallback_summary,
            candidate=synthesized_payload.get("scenario_summary_candidate"),
        )
        current_result.result_payload["harness"]["synthesis"] = {
            "source": synthesis_source,
            "candidate_source": synthesized_payload.get("source", "tool_results"),
            "issues": llm_synthesis_issues,
        }
        current_result.result_payload["scenario_summary"] = scenario_summary
        # Run validation separately and attach under stage1_validation
        validation_issues = validate_stage1_summary(scenario_summary)
        quality_scores = compute_stage1_quality(scenario_summary)
        current_result.result_payload["stage1_validation"] = {
            "issues": validation_issues,
            "quality": quality_scores,
        }
        # Record input binding
        current_result.result_payload["input_binding"] = {
            "mode": "project_evidence_fallback",
            "file_ids": list(set(f for item in evidence_items for f in ([item.source_file_id] if item.source_file_id else []))),
            "evidence_ids": evidence_refs,
        }

    if skill.name == "value_modeling_skill":
        stage2_summary = _build_stage_two_summary(
            goal=goal,
            stage_name=stage.name,
            tool_payload=tool_payload,
            previous_stage_result=previous_stage_result,
        )
        current_result.result_payload["stage2_summary"] = stage2_summary
        # Run contract validation + quality scoring
        stage2_validation_issues = validate_stage2_summary(stage2_summary, previous_stage_result=previous_stage_result)
        stage2_quality = compute_stage2_quality(stage2_summary)
        current_result.result_payload["stage2_validation"] = {
            "issues": stage2_validation_issues,
            "quality": stage2_quality,
        }

    if skill.name == "probe_validation_skill":
        stage3_summary = _build_stage_three_summary(
            goal=goal,
            stage_name=stage.name,
            tool_payload=tool_payload,
            previous_stage_result=previous_stage_result,
        )
        current_result.result_payload["stage3_summary"] = stage3_summary
        # Run contract validation + quality scoring
        stage3_validation_issues = validate_stage3_summary(stage3_summary, previous_stage_result=previous_stage_result)
        stage3_quality = compute_stage3_quality(stage3_summary)
        current_result.result_payload["stage3_validation"] = {
            "issues": stage3_validation_issues,
            "quality": stage3_quality,
        }

    if skill.name in {"evidence_decision_skill", "report_generation_skill"}:
        stage4_summary = _build_stage_four_summary(
            goal=goal,
            stage_name=stage.name,
            tool_payload=tool_payload,
            previous_stage_result=previous_stage_result,
        )
        current_result.result_payload["stage4_summary"] = stage4_summary
        # Run contract validation + quality scoring
        stage4_validation_issues = validate_stage4_summary(stage4_summary, previous_stage_result=previous_stage_result)
        stage4_quality = compute_stage4_quality(stage4_summary)
        current_result.result_payload["stage4_validation"] = {
            "issues": stage4_validation_issues,
            "quality": stage4_quality,
        }
    if vision_results and skill.name in {"scenario_risk_skill", "report_generation_skill"}:
        current_result.result_payload["vision_inputs"] = [
            {
                "structured_fields": item.get("structured_fields", {}),
                "to_confirm": item.get("to_confirm", []),
                "uncertainties": item.get("uncertainties", []),
            }
            for item in vision_results
        ]
    current_result.summary = "{0} 已完成。".format(skill.description)
    current_result.updated_at = utcnow()
    current_result.skill_versions[skill.name] = skill_version
    current_result.evidence_item_ids = evidence_refs
    save_stage_result(current_result)

    report = None
    if skill.name == "report_generation_skill":
        report = create_report(
            project_id,
            "阶段四报告草稿",
            stage_result_ids=[current_result.id],
            evidence_item_ids=evidence_refs,
            enforce_export_gate=False,
            approval_check_passed=False,
            report_status="draft",
        )

    diff_summary = build_stage_result_diff(
        current_result,
        previous_result if current_result.id == latest_result.id else latest_result,
        trigger="skill.invoke",
    )
    create_version_log(
        project_id=project_id,
        resource_type="stage_result",
        resource_id=current_result.id,
        change_type="skill.invoked",
        summary="Skill invocation updated stage result.",
        run_id=run_id,
        details={
            "skill_name": skill.name,
            "version_id": current_result.version_id,
            "base_version_id": current_result.base_version_id,
            "diff_summary": diff_summary,
            "config_version_id": snapshot["config_version_id"],
            "enabled_tools": enabled_tools,
            "enabled_subagents": enabled_subagents,
            "harness_plan_source": plan_payload.get("source", "fallback"),
            "harness_decision_source": decision_payload.get("source", "fallback"),
            "harness_version": harness_payload.get("harness_version"),
            "harness_graph_version": harness_payload.get("graph_version"),
            "harness_llm_mode": llm_status.get("mode"),
        },
    )
    create_execution_log(
        project_id=project_id,
        action="skill.invoked",
        resource_type="stage_result",
        resource_id=current_result.id,
        run_id=run_id,
        details={"skill_name": skill.name, "tool_names": skill.allowed_tools, "report_id": report.id if report else None},
    )
    append_run_event(
        run,
        "run.skill_completed",
        {
            "skill_name": skill.name,
            "summary": "Fixed skill invocation completed.",
            "source": "skill.invoke",
            "stage_result_id": current_result.id,
        },
    )

    return {
        "skill_name": skill.name,
        "stage_id": stage_id,
        "project_id": project_id,
        "summary": "{0} 已生成阶段处理摘要。".format(skill.description),
        "tool_names": list(skill.allowed_tools),
        "subagent_names": list(skill.allowed_subagents),
        "enabled_tools": enabled_tools,
        "enabled_subagents": enabled_subagents,
        "config_version_id": snapshot["config_version_id"],
        "goal": goal,
        "stage_result_id": current_result.id,
        "report_id": report.id if report is not None else None,
        "tool_results": tool_results,
        "warnings": warnings,
    }
