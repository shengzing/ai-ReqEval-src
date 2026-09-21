"""Fixed tool registry for MVP skills."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from src.apps.api.app.agents.risk_semantic.vocabulary import RiskVocabulary

# ── Module-level vocabulary (lazy-initialized) ────────────────────────────
_VOCAB: RiskVocabulary | None = None


def _get_vocabulary() -> RiskVocabulary:
    """Return the shared vocabulary instance (lazy singleton)."""
    global _VOCAB
    if _VOCAB is None:
        _VOCAB = RiskVocabulary()
    return _VOCAB


@dataclass
class ToolResult:
    name: str
    summary: str
    raw_output: dict[str, Any]
    evidence_refs: list[str]
    warnings: list[str]
    # A skipped tool was deliberately not executed and must never be
    # aggregated into a business conclusion as if it had succeeded.
    status: str = "completed"  # completed | skipped_missing_input
    audit: dict[str, Any] = field(default_factory=dict)


# ── Label extraction patterns for document_parse ──────────────────────

# Negation prefixes for risk keyword context scanning (P0-negation)
NEGATION_PREFIXES: list[str] = ["不涉及", "无需", "不适用", "排除", "不包括", "非"]
"""Chinese negation prefixes that suppress risk keyword matches when appearing
immediately before a keyword in a short character window."""

_LABEL_PATTERNS = [
    (r"业务环节[：:]\s*(.+)", "business_step"),
    (r"Business step[：:]\s*(.+)", "business_step"),
    (r"使用人[：:]\s*(.+)", "users"),
    (r"Users[：:]\s*(.+)", "users"),
    (r"当前流程[：:]\s*(.+)", "current_process"),
    (r"Current process[：:]\s*(.+)", "current_process"),
    (r"AI拟处理事项[：:]\s*(.+)", "ai_scope"),
    (r"AI scope[：:]\s*(.+)", "ai_scope"),
    (r"明确不让AI做的事项[：:]\s*(.+)", "ai_prohibited"),
    (r"AI prohibited[：:]\s*(.+)", "ai_prohibited"),
    (r"输入材料[：:]\s*(.+)", "input_materials"),
    (r"Input materials[：:]\s*(.+)", "input_materials"),
    (r"输出结果[：:]\s*(.+)", "output_results"),
    (r"Output results[：:]\s*(.+)", "output_results"),
    (r"常见异常[：:]\s*(.+)", "common_anomalies"),
    (r"Common anomalies[：:]\s*(.+)", "common_anomalies"),
    (r"出错最严重后果[：:]\s*(.+)", "worst_consequence"),
    (r"Worst consequence[：:]\s*(.+)", "worst_consequence"),
    (r"必须人工确认点[：:]\s*(.+)", "manual_review_points"),
    (r"Manual review points[：:]\s*(.+)", "manual_review_points"),
    (r"审计留痕要求[：:]\s*(.+)", "audit_requirements"),
    (r"Audit retention[：:]\s*(.+)", "audit_requirements"),
    (r"数据限制[：:]\s*(.+)", "data_constraints"),
    (r"Data constraints[：:]\s*(.+)", "data_constraints"),
]


def _is_negation_context(text: str, keyword: str, window: int = 6) -> bool:
    """检查关键词在text中的所有出现是否均被否定前缀修饰。

    扫描 *text* 中 *keyword* 的每次出现位置，查看该位置往前 *window*
    个字符范围内是否包含 NEGATION_PREFIXES 中的任意否定前缀。
    只有当**所有**出现都被否定前缀修饰时，返回 True；
    如果至少有一次出现是肯定的（未被否定），返回 False。

    Args:
        text: 完整待扫描文本
        keyword: 风险关键词
        window: 否定前缀搜索窗口大小（字符数），默认6

    Returns:
        True 表示该关键词被否定语境完全修饰，应跳过风险升级
    """
    start = 0
    found_any = False
    all_negated = True
    while True:
        idx = text.find(keyword, start)
        if idx == -1:
            break
        found_any = True
        # Extract the window preceding this keyword occurrence
        prefix_start = max(0, idx - window)
        preceding = text[prefix_start:idx]
        has_neg = any(neg in preceding for neg in NEGATION_PREFIXES)
        if not has_neg:
            all_negated = False
            break  # At least one affirmative occurrence → not fully negated
        start = idx + len(keyword)
    # Only fully negated if we found at least one occurrence and ALL are negated
    return found_any and all_negated


def _find_best_evidence(keyword: str, evidence_items: list[dict], evidence_snippets: dict[str, str]) -> str:
    """基于关键词重叠为风险项选择最佳证据ID。

    对每个evidence item，检查keyword是否出现在其snippet中。
    返回第一个snippet包含keyword的evidence ID；若无匹配则返回第一个evidence ID。

    Args:
        keyword: 用于匹配的关键词/描述文本
        evidence_items: 原始evidence item列表（包含id字段）
        evidence_snippets: evidence_id -> snippet text的映射字典

    Returns:
        最佳匹配的evidence ID，若无匹配则回退到第一个item的ID或'ev-unknown'
    """
    if not evidence_items:
        return "ev-unknown"
    for item in evidence_items:
        item_id = item.get("id", "")
        snippet = evidence_snippets.get(item_id, "")
        if keyword in snippet:
            return item_id
    # Fallback to first evidence item
    return evidence_items[0].get("id", "ev-unknown")


def _extract_labeled_fields(text: str) -> dict[str, str]:
    """Extract key-value pairs from Chinese- or English-labeled text."""
    fields: dict[str, str] = {}
    for pattern, key in _LABEL_PATTERNS:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            fields[key] = m.group(1).strip()
    return fields


def _split_semicolon_list(text: str) -> list[str]:
    """Split a semicolon-delimited list into clean items."""
    return [
        cleaned
        for item in re.split(r"[；;]", text)
        if (cleaned := _clean_list_item(item))
    ]


def _clean_list_item(item: str) -> str:
    """Trim common Chinese/ASCII list punctuation around one item."""
    return item.strip().strip("。；;，,、.")


def _split_chinese_list(text: str) -> list[str]:
    """Split role-like Chinese lists without changing semicolon-only fields."""
    return [
        cleaned
        for part in re.split(r"[；;、，,\n/]+", text)
        if (cleaned := _clean_list_item(part))
    ]


def _select_owner_role(node_name: str, participants: list[dict]) -> str:
    roles = [str(item.get("role", "")) for item in participants if isinstance(item, dict)]
    if not roles:
        return ""
    lower_name = node_name.lower()
    role_hints = (
        ("风险", "risk"),
        ("合规", "compliance"),
        ("客户", "customer"),
        ("业务", "business"),
        ("运营", "operation"),
    )
    for cn_keyword, en_keyword in role_hints:
        if cn_keyword in node_name or en_keyword in lower_name:
            for role in roles:
                lower_role = role.lower()
                if cn_keyword in role or en_keyword in lower_role:
                    return role
    return roles[0]


def _infer_scenario_type(
    *,
    ai_scope: str,
    combined_text: str,
    llm_client: Any = None,
) -> str:
    """Infer the AI task category for a scenario.

    LLM-first: when an LLM client is configured, ask the extractor's
    scenario_type. Fallback: the pre-upgrade keyword inference on ai_scope.
    """
    from src.apps.api.app.agents.risk_semantic.models import RiskBrief
    from src.apps.api.app.agents.risk_semantic.extractor import _normalize_scenario_type

    if llm_client is not None:
        try:
            from src.apps.api.app.agents.risk_semantic import extract_risk_artifacts

            brief = RiskBrief(
                scenario_name=ai_scope,
                combined_text=combined_text,
            )
            report = extract_risk_artifacts(
                brief, evidence_snippets={}, llm_client=llm_client,
            )
            if report.source == "llm" and report.scenario_type:
                return report.scenario_type
        except Exception:
            # Fall through to keyword inference
            pass

    # Pre-upgrade keyword inference (line 400 behavior)
    if any(kw in ai_scope for kw in ["摘要", "生成", "草拟"]):
        return "content_generation"
    if any(kw in ai_scope for kw in ["汇总", "提取", "识别"]):
        return "understanding_analysis"
    return "decision_support"


def _enrich_process_nodes(
    nodes: list[dict],
    *,
    input_objects: list[str],
    output_objects: list[str],
    participants: list[dict],
    manual_review_points: list[str],
    audit_requirements: list[str],
) -> list[dict]:
    """Populate deterministic Stage 1 node metadata from parsed fields."""
    if not nodes:
        return []

    enriched = [dict(node) for node in nodes]
    review_keywords = (
        "复核", "确认", "审批", "合规",
        "review", "confirm", "approval", "compliance", "escalate",
    )
    output_keywords = (
        "草拟", "生成", "输出", "摘要", "清单", "建议",
        "draft", "generate", "output", "summary", "list", "recommendation",
    )

    for idx, node in enumerate(enriched):
        name = str(node.get("name", ""))
        lower_name = name.lower()
        node.setdefault("input", [])
        node.setdefault("output", [])
        node.setdefault("system_refs", [])
        node.setdefault("audit_fields", [])
        node["owner_role"] = node.get("owner_role") or _select_owner_role(name, participants)
        node["human_review_required"] = bool(
            any(keyword in name for keyword in review_keywords)
            or any(keyword in lower_name for keyword in review_keywords)
        )

        if idx == 0 and input_objects:
            node["input"] = list(input_objects)
        if (
            any(keyword in name for keyword in output_keywords)
            or any(keyword in lower_name for keyword in output_keywords)
        ) and output_objects:
            node["output"] = list(output_objects)
        if node["human_review_required"]:
            if manual_review_points and not node["input"]:
                node["input"] = list(manual_review_points)
            if audit_requirements:
                node["audit_fields"] = list(audit_requirements)

    if output_objects and not any(node.get("output") for node in enriched):
        enriched[-1]["output"] = list(output_objects)

    return enriched


def _is_no_manual_review_text(text: str) -> bool:
    cleaned = _clean_list_item(text)
    return cleaned in {"无", "无需", "不需要", "无须", "暂无", "N/A", "n/a"}


def _should_downgrade_low_risk_l2(
    *,
    combined_text: str,
    l2_hits: list[str],
    l3_hits: list[str],
    manual_points: list[str],
) -> bool:
    """Conservatively suppress generic L2 hits for public/internal summaries."""
    if l3_hits or not l2_hits:
        return False

    fields = _extract_labeled_fields(combined_text)
    business_context = "\n".join(
        fields.get(key, "")
        for key in ("business_step", "current_process", "ai_scope", "input_materials", "output_results")
    )
    low_risk_markers = ("公开新闻", "公开信息", "内部会议", "会议纪要", "摘要推送")
    if not any(marker in business_context or marker in combined_text for marker in low_risk_markers):
        return False

    data_constraints = fields.get("data_constraints", "")
    low_data_markers = ("仅使用公开信息", "公开新闻", "不含客户隐私", "不涉及客户隐私", "不涉及客户数据")
    high_data_markers = ("客户经营数据", "未脱敏", "敏感数据", "数据跨境", "客户隐私数据")
    if data_constraints:
        if any(marker in data_constraints for marker in high_data_markers) and not any(
            marker in data_constraints for marker in low_data_markers
        ):
            return False

    prohibited_text = fields.get("ai_prohibited", "")
    high_prohibited_markers = ("风险分类", "风险等级", "客户处置", "监管敏感", "跳过复核", "对外发送")
    if any(marker in prohibited_text for marker in high_prohibited_markers):
        return False

    def _is_low_risk_manual_point(point: str) -> bool:
        cleaned = _clean_list_item(point)
        if _is_no_manual_review_text(cleaned):
            return True
        allowed_markers = ("待办责任人", "参会人确认", "确认人", "责任人清单", "任务完成")
        disallowed_markers = ("风险等级", "风险分类", "客户处置", "监管敏感", "合规复核", "对外发送")
        return any(marker in cleaned for marker in allowed_markers) and not any(
            marker in cleaned for marker in disallowed_markers
        )

    if manual_points and not all(_is_low_risk_manual_point(point) for point in manual_points):
        return False

    governance_text = combined_text
    if manual_points and all(_is_low_risk_manual_point(point) for point in manual_points):
        governance_text = re.sub(r"^必须人工确认点[：:].*$", "", governance_text, flags=re.MULTILINE)
    if prohibited_text and "代表参会人确认" in prohibited_text:
        governance_text = re.sub(r"^明确不让AI做的事项[：:].*$", "", governance_text, flags=re.MULTILINE)
    if "仅使用公开信息" in combined_text or "公开新闻" in combined_text or "不含客户隐私" in combined_text:
        governance_text = re.sub(r"^审计留痕要求[：:].*$", "", governance_text, flags=re.MULTILINE)
        governance_text = re.sub(r"^数据限制[：:].*$", "", governance_text, flags=re.MULTILINE)
    for phrase in (
        "发送给参会人确认",
        "参会人确认",
        "待办责任人",
        "责任人清单",
        "确认人",
    ):
        governance_text = governance_text.replace(phrase, "")

    governance_keywords = (
        "人工确认", "人工复核", "复核", "审计留痕", "责任人", "对外发送",
        "客户", "监管", "合规", "隐私", "敏感", "风险等级", "处置",
    )
    if any(keyword in governance_text for keyword in governance_keywords):
        return False

    return True


def _build_process_node_candidates(process_text: str, evidence_id: str) -> list[dict]:
    """Build process node candidates from the '当前流程' field."""
    steps = _split_semicolon_list(process_text)
    nodes = []
    for idx, step in enumerate(steps, start=1):
        nodes.append({
            "node_id": f"node-{idx}",
            "name": step,
            "input": [],
            "output": [],
            "owner_role": "",
            "system_refs": [],
            "human_review_required": None,
            "audit_fields": [],
            "evidence_refs": [evidence_id],
        })
    return nodes


def _build_participants(users_text: str, evidence_id: str) -> list[dict]:
    """Build participants from the '使用人' field."""
    roles = _split_chinese_list(users_text)
    return [
        {"role": role, "responsibility": "", "evidence_refs": [evidence_id]}
        for role in roles
    ]


def document_parse_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
    llm_client: Any = None,
) -> ToolResult:
    evidence_items = evidence_items or []
    semantic_llm_client = (
        llm_client
        if llm_client is not None and getattr(llm_client, "is_configured", lambda: False)()
        else None
    )
    all_refs: list[str] = []
    all_snippets: list[str] = []

    for item in evidence_items:
        item_id = item.get("id", "")
        snippet = item.get("snippet", "") or ""
        if item_id:
            all_refs.append(item_id)
        if snippet:
            all_snippets.append(snippet)

    combined_text = "\n".join(all_snippets)

    if not combined_text.strip():
        return ToolResult(
            name="document_parse",
            summary="无可用证据，材料解析为空。",
            raw_output={
                "scenario_name_candidates": [],
                "scenario_type": "",
                "boundary": {"in_scope": [], "out_of_scope": [], "preconditions": [], "data_boundary": []},
                "sop_summary": "",
                "participants": [],
                "process_node_candidates": [],
                "input_objects": [],
                "output_objects": [],
                "known_risk_points": [],
                "manual_review_points": [],
                "audit_requirements": [],
                "prohibited_conditions": [],
                "evidence_refs": [],
            },
            evidence_refs=[],
            warnings=["No evidence snippets available for parsing."],
            status="skipped_missing_input",
        )

    fields = _extract_labeled_fields(combined_text)

    # Scenario name candidates: first heading line + goal
    heading_match = re.search(r"^#\s*(.+)$", combined_text, re.MULTILINE)
    scenario_name_candidates = []
    if heading_match:
        scenario_name_candidates.append(heading_match.group(1).strip())

    # Scenario type: infer from AI scope (LLM-first when available, keyword fallback)
    ai_scope = fields.get("ai_scope", "")
    scenario_type = _infer_scenario_type(
        ai_scope=ai_scope,
        combined_text=combined_text,
        llm_client=semantic_llm_client,
    )

    # Boundary
    in_scope = _split_semicolon_list(fields.get("ai_scope", ""))
    out_scope_raw = fields.get("ai_prohibited", "")
    out_of_scope = _split_semicolon_list(out_scope_raw)
    data_boundary = _split_semicolon_list(fields.get("data_constraints", ""))
    preconditions = []

    # SOP summary
    sop_summary = fields.get("current_process", "")

    # Process node candidates
    process_text = fields.get("current_process", "")
    process_node_candidates = []
    primary_evidence_id = all_refs[0] if all_refs else "ev-unknown"
    users_text = fields.get("users", "")
    participants = []
    if users_text:
        participants = _build_participants(users_text, primary_evidence_id)

    # Input / output objects
    input_objects = _split_semicolon_list(fields.get("input_materials", ""))
    output_objects = _split_semicolon_list(fields.get("output_results", ""))

    # Risk points
    anomalies = _split_semicolon_list(fields.get("common_anomalies", ""))
    worst = _split_semicolon_list(fields.get("worst_consequence", ""))
    known_risk_points = anomalies + worst

    # Manual review points
    manual_review_points = _split_semicolon_list(fields.get("manual_review_points", ""))

    # Audit requirements
    audit_requirements = _split_semicolon_list(fields.get("audit_requirements", ""))

    if process_text:
        process_node_candidates = _build_process_node_candidates(process_text, primary_evidence_id)
        # LLM-first semantic enrichment (owner_role / human_review_required / output)
        # with keyword fallback identical to the pre-upgrade _enrich_process_nodes.
        from src.apps.api.app.agents.risk_semantic import enrich_process_nodes_semantic

        enrich_report = enrich_process_nodes_semantic(
            process_node_candidates,
            participants,
            llm_client=semantic_llm_client,
            input_objects=input_objects,
            output_objects=output_objects,
            manual_review_points=manual_review_points,
            audit_requirements=audit_requirements,
        )
        process_node_candidates = enrich_report.nodes

    # Prohibited conditions (from "不让AI做" field)
    prohibited_conditions = []
    for cond in out_of_scope:
        prohibited_conditions.append({
            "condition": cond,
            "reason": "",
            "evidence_refs": [primary_evidence_id],
        })

    raw_output = {
        "scenario_name_candidates": scenario_name_candidates,
        "scenario_type": scenario_type,
        "boundary": {
            "in_scope": in_scope,
            "out_of_scope": out_of_scope,
            "preconditions": preconditions,
            "data_boundary": data_boundary,
        },
        "sop_summary": sop_summary,
        "participants": participants,
        "process_node_candidates": process_node_candidates,
        "input_objects": input_objects,
        "output_objects": output_objects,
        "known_risk_points": known_risk_points,
        "manual_review_points": manual_review_points,
        "audit_requirements": audit_requirements,
        "prohibited_conditions": prohibited_conditions,
        "evidence_refs": list(all_refs),
    }

    return ToolResult(
        name="document_parse",
        summary="已从证据中提取材料解析字段。",
        raw_output=raw_output,
        evidence_refs=list(all_refs),
        warnings=[],
    )


def risk_identify_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
    llm_client: Any = None,
) -> ToolResult:
    from src.apps.api.app.services.stage1_contract import (
        HITL_LEVELS,
        RISK_LEVELS,
        RISK_L3_KEYWORDS,
        RISK_L2_KEYWORDS,
        normalize_hitl_level,
        normalize_risk_level,
    )

    evidence_items = evidence_items or []
    vision_results = vision_results or []

    # Collect all text from evidence and vision
    all_refs: list[str] = []
    all_text_parts: list[str] = []

    for item in evidence_items:
        item_id = item.get("id", "")
        snippet = item.get("snippet", "") or ""
        if item_id:
            all_refs.append(item_id)
        if snippet:
            all_text_parts.append(snippet)

    for vr in vision_results:
        for frag in vr.get("evidence_fragments", []):
            text = frag.get("text", "") if isinstance(frag, dict) else str(frag)
            if text:
                all_text_parts.append(text)

    combined_text = "\n".join(all_text_parts)
    if not combined_text.strip():
        # P2: empty-evidence path still emits the guaranteed default risk item
        # and a fully-shaped confidence dict so downstream consumers never see
        # a schema hole (tests expect risk-1 "通用风险识别" + field_scores keys).
        default_risk_item = {
            "risk_id": "risk-1",
            "node_id": "",
            "description": "通用风险识别",
            "severity": "low",
            "likelihood": "low",
            "impact": "",
            "owner_role": "",
            "mitigation": "",
            "audit_need": "",
            "risk_level": "",
            "evidence_refs": [],
        }
        return ToolResult(
            name="risk_identify",
            summary="无可用证据，跳过风险识别。",
            raw_output={
                "risk_level": "",
                "hitl_level": "",
                "risk_items": [default_risk_item],
                "risk_matrix": [
                    {
                        "risk_id": "risk-1",
                        "item": "通用风险识别",
                        "level": "",
                        "control": "人工复核",
                        "evidence_refs": [],
                    }
                ],
                "hitl_rules": [],
                "prohibited_conditions": [],
                "fatal_errors": [],
                "audit_requirements": [],
                "confidence": {
                    "overall": 0.3,
                    "field_scores": {
                        "boundary": 0.3,
                        "process_nodes": 0.3,
                        "risk_items": 0.3,
                        "hitl_rules": 0.3,
                        "audit_requirements": 0.3,
                    },
                },
                "to_confirm": ["无可用证据，风险识别结果需人工确认。"],
                "boundary_flag": False,
                "evidence_refs": [],
            },
            evidence_refs=[],
            warnings=["No evidence snippets available for risk identification."],
            status="skipped_missing_input",
        )
    primary_evidence_id = all_refs[0] if all_refs else "ev-unknown"

    # Build evidence_snippets mapping for keyword-overlap evidence binding (P1-evidence)
    evidence_snippets: dict[str, str] = {}
    for item in evidence_items:
        item_id = item.get("id", "")
        snippet = item.get("snippet", "") or ""
        if item_id:
            evidence_snippets[item_id] = snippet

    # ── Risk level determination (vocabulary-augmented keyword heuristics) ─

    # P0-negation: scan for negation context before keyword matching
    negated_keywords: set[str] = set()
    negation_warnings: list[str] = []

    # Use RiskVocabulary for keyword scanning (supports synonyms + hierarchy)
    vocab = _get_vocabulary()
    all_matches = vocab.lookup(combined_text)

    # Collect L3 and L2 hits from vocabulary matches (after negation check)
    l3_hits: list[str] = []
    l2_hits: list[str] = []
    raw_risk = "L1"

    for match in all_matches:
        # Determine the string that was actually found in the text
        matched_str = match.matched_synonym or match.matched_child or match.term
        if _is_negation_context(combined_text, matched_str):
            negated_keywords.add(match.term)
            negation_warnings.append(
                f"Negation context suppressed {match.level} keyword: {match.term}"
                + (f" (via synonym: {match.matched_synonym})" if match.matched_synonym else "")
                + (f" (via child: {match.matched_child})" if match.matched_child else "")
            )
        else:
            if match.level == "L3":
                l3_hits.append(match.term)
                raw_risk = "L3"
            elif match.level == "L2":
                l2_hits.append(match.term)
                if raw_risk == "L1":
                    raw_risk = "L2"

    # P2-boundary: check if both L2 and L3 non-negated keywords co-occur
    boundary_flag = len(l3_hits) > 0 and len(l2_hits) > 0

    manual_review_match = re.search(r"必须人工确认点[：:]\s*(.+)", combined_text)
    manual_points = _split_semicolon_list(manual_review_match.group(1)) if manual_review_match else []

    # ── Semantic risk classification (P0-1) ───────────────────────────
    # Build RiskBrief for classifier
    from src.apps.api.app.agents.risk_semantic.models import RiskBrief
    from src.apps.api.app.agents.risk_semantic import classify_risk_semantic

    # Extract known_risk_points and prohibited_conditions from document_parse
    prev_doc = (previous_stage_result or {}).get("document_parse", {})
    known_risk_points = prev_doc.get("known_risk_points", []) if isinstance(prev_doc, dict) else []
    prohibited_conditions_raw = prev_doc.get("prohibited_conditions", []) if isinstance(prev_doc, dict) else []
    prohibited_conditions = [
        c.get("condition", "") if isinstance(c, dict) else str(c)
        for c in prohibited_conditions_raw
    ]

    scenario_name = goal or ""
    # Try to get scenario name from document_parse result
    if prev_doc and isinstance(prev_doc, dict):
        name_candidates = prev_doc.get("scenario_name_candidates", [])
        if name_candidates:
            scenario_name = name_candidates[0]

    brief = RiskBrief(
        scenario_name=scenario_name,
        combined_text=combined_text,
        keyword_hits_l3=l3_hits,
        keyword_hits_l2=l2_hits,
        negated_keywords=negated_keywords,
        known_risk_points=known_risk_points,
        prohibited_conditions=prohibited_conditions,
        boundary_flag=boundary_flag,
    )

    # Attempt semantic classification with LLM client
    from src.apps.api.app.agents.harness.llm import HarnessLLMClient
    if llm_client is None:
        llm_client = HarnessLLMClient()
    if not getattr(llm_client, "is_configured", lambda: False)():
        llm_client = None
    semantic_result = classify_risk_semantic(brief, llm_client=llm_client)

    if semantic_result.source == "llm":
        # LLM result takes precedence
        risk_level = semantic_result.risk_level
        hitl_level = semantic_result.hitl_level
        boundary_flag = semantic_result.boundary_flag
    else:
        # Fallback: use keyword-based result
        low_risk_downgraded = False
        if raw_risk == "L2" and _should_downgrade_low_risk_l2(
            combined_text=combined_text,
            l2_hits=l2_hits,
            l3_hits=l3_hits,
            manual_points=manual_points,
        ):
            raw_risk = "L1"
            boundary_flag = False
            low_risk_downgraded = True
        risk_level = normalize_risk_level(raw_risk)
        hitl_level = normalize_hitl_level(
            "mandatory" if raw_risk == "L3" and any(kw in combined_text for kw in ["不得自动", "必须人工确认", "风险等级调整", "客户处置", "监管敏感"])
            else "strict" if raw_risk == "L3"
            else "standard" if raw_risk == "L2"
            else "none",
            risk_level=normalize_risk_level(raw_risk),
        )
        if low_risk_downgraded:
            semantic_result = replace(
                semantic_result,
                risk_level=risk_level,
                hitl_level=hitl_level,
                confidence=max(semantic_result.confidence, 0.7),
                reasoning=(semantic_result.reasoning + "; " if semantic_result.reasoning else "")
                + "内部/公开摘要场景仅涉及待办确认与留痕，按低风险校准为L1",
                boundary_flag=False,
            )

    # ── Extract risk items / fatal errors / evidence bindings ──────────
    # LLM-first: ask the extractor for risk_items + fatal_errors +
    # evidence_bindings + scenario_type in one call. Fallback is byte-identical
    # to the pre-upgrade regex/keyword block below.
    from src.apps.api.app.agents.risk_semantic import extract_risk_artifacts
    from src.apps.api.app.agents.risk_semantic.models import RiskBrief as _RiskBrief

    artifacts_brief = _RiskBrief(
        scenario_name=scenario_name,
        combined_text=combined_text,
        known_risk_points=known_risk_points,
        prohibited_conditions=prohibited_conditions,
        boundary_flag=boundary_flag,
    )
    artifacts = extract_risk_artifacts(
        artifacts_brief,
        evidence_snippets,
        llm_client=llm_client,
        risk_level=risk_level,
        primary_evidence_id=primary_evidence_id,
    )

    if artifacts.source == "llm":
        risk_items = list(artifacts.risk_items)
        # evidence_bindings already attached to each item's evidence_refs by
        # the extractor; fall back to keyword-overlap binding for any item
        # that came back empty.
        for item in risk_items:
            if not item.get("evidence_refs"):
                rid = item.get("risk_id", "")
                ev = artifacts.evidence_bindings.get(rid)
                if ev:
                    item["evidence_refs"] = list(ev)
                else:
                    item["evidence_refs"] = [_find_best_evidence(
                        item.get("description", ""), evidence_items, evidence_snippets
                    )]
        fatal_errors = list(artifacts.fatal_errors)
        for fe in fatal_errors:
            if not fe.get("evidence_refs"):
                fe["evidence_refs"] = [_find_best_evidence(
                    fe.get("error", ""), evidence_items, evidence_snippets
                )]
    else:
        # Fallback path — reuse the extractor's own fallback (byte-identical
        # to the pre-upgrade block) so we have a single source of truth.
        risk_items = list(artifacts.risk_items)
        fatal_errors = list(artifacts.fatal_errors)

    # Ensure at least one risk item exists (mirrors pre-upgrade guarantee)
    if not risk_items:
        risk_items.append({
            "risk_id": "risk-1",
            "node_id": "",
            "description": "通用风险识别",
            "severity": "low",
            "likelihood": "low",
            "impact": "",
            "owner_role": "",
            "mitigation": "",
            "audit_need": "",
            "risk_level": risk_level,
            "evidence_refs": [primary_evidence_id] if primary_evidence_id != "ev-unknown" else [],
        })

    # ── Evidence chain semantic verification (P0-2) ────────────────────
    from src.apps.api.app.agents.risk_semantic import verify_evidence_chain

    evidence_report = verify_evidence_chain(
        risk_items,
        evidence_snippets,
        llm_client=llm_client,
    )

    # Add evidence_verified flag per risk item
    verified_map: dict[str, bool] = {}
    for vr in evidence_report.results:
        verified_map[vr.risk_id] = vr.supports

    for item in risk_items:
        item["evidence_verified"] = verified_map.get(item.get("risk_id", ""), False)

    # ── Risk matrix ───────────────────────────────────────────────────

    risk_matrix = [
        {
            "risk_id": item["risk_id"],
            "item": item["description"],
            "level": item["risk_level"],
            "control": item.get("mitigation", "") or "人工复核",
            "evidence_refs": item["evidence_refs"],
        }
        for item in risk_items
    ]

    # ── HITL rules ────────────────────────────────────────────────────

    hitl_rules: list[dict] = []
    if risk_level in {"L2", "L3"}:
        hitl_rules.append({
            "risk_level": risk_level,
            "review_level": hitl_level,
            "review_trigger": "风险等级判定" if risk_level == "L3" else "复核确认",
            "review_owner": "风险经理" if risk_level == "L3" else "业务负责人",
            "review_evidence": manual_points,
            "evidence_refs": [primary_evidence_id],
        })

    # ── Prohibited conditions ─────────────────────────────────────────

    prohibited_conditions: list[dict] = []
    prohibited_match = re.search(r"明确不让AI做的事项[：:]\s*(.+)", combined_text)
    if prohibited_match:
        for cond in _split_semicolon_list(prohibited_match.group(1)):
            best_ev = _find_best_evidence(cond, evidence_items, evidence_snippets)
            prohibited_conditions.append({
                "condition": cond,
                "reason": "业务底线约束",
                "evidence_refs": [best_ev],
            })

    # ── Fatal errors ──────────────────────────────────────────────────
    # `fatal_errors` was already populated by extract_risk_artifacts above
    # (LLM-first with the 4-keyword fallback baked into the extractor when
    # risk_level == L3). The pre-upgrade inline block is no longer needed here.

    # ── Audit requirements — P2: structured 8-field schema (§3.2.4) ────
    # Parse free-text requirements, map to canonical field IDs, and always
    # emit all 8 base fields so downstream coverage checks see the full
    # schema (configured=True/False per field). Enum-valued fields get
    # thesis-mandated defaults for loan-risk scenarios.

    audit_match = re.search(r"审计留痕要求[：:]\s*(.+)", combined_text)
    audit_raw_items = _split_semicolon_list(audit_match.group(1)) if audit_match else []
    audit_text = "；".join(audit_raw_items)

    # Keyword → field_id mapping (mirrors frontend AUDIT_KEYWORD_RULES)
    _AUDIT_FIELD_DEFS = [
        ("input_material_version", "输入材料版本", ["输入材料版本", "材料版本", "版本号"]),
        ("raw_analysis_output", "AI 原始输出", ["AI输出", "AI 输出", "原始输出", "分析结果"]),
        ("reviewer_opinion", "复核人及复核意见", ["复核人", "复核意见", "复核结论"]),
        ("timestamp", "时间戳", ["时间戳"]),
        ("inference_path", "推理路径", ["推理路径", "推理链路"]),
        ("threshold_trigger_log", "阈值触发记录", ["阈值触发", "阈值命中"]),
        ("ai_disclosure", "AI 生成内容显著标识", ["显著标识", "AIGC", "水印", "AI生成"]),
        ("log_retention", "日志保存期限", ["日志保存", "保存期限", "存续期"]),
    ]
    audit_requirements: list[dict] = []
    for fid, label, keywords in _AUDIT_FIELD_DEFS:
        configured = any(kw in audit_text for kw in keywords)
        value = ""
        if fid == "ai_disclosure":
            # NFRA §21 + 深度合成规定 §17: L2/L3 贷后风控必须显式水印。
            # 这是监管最低要求（非业务可选项），L2/L3 直接生效。
            value = "explicit_watermark" if risk_level in {"L2", "L3"} else ""
            configured = configured or risk_level in {"L2", "L3"}
        elif fid == "log_retention":
            # NFRA §21: 日志保存 ≥ 业务存续期。L2/L3 直接生效。
            value = "business_lifetime" if risk_level in {"L2", "L3"} else ""
            configured = configured or risk_level in {"L2", "L3"}
        elif configured:
            matched = [raw for raw in audit_raw_items if any(kw in raw for kw in keywords)]
            value = matched[0] if matched else label
        audit_requirements.append({
            "field_id": fid,
            "label": label,
            "configured": configured,
            "value": value,
            "evidence_refs": [primary_evidence_id] if configured else [],
        })
    # AML 场景追加第 9 字段（监管报送流水）
    if any(kw in combined_text for kw in ("反洗钱", "AML", "监管报送", "报送流水")):
        audit_requirements.append({
            "field_id": "regulatory_reporting_log",
            "label": "监管报送流水",
            "configured": True,
            "value": "监管报送批次号+回执",
            "evidence_refs": [primary_evidence_id],
        })

    # ── Confidence scoring ────────────────────────────────────────────

    # overall confidence: counts how many of the six contract-relevant fields
    # are directly backed by evidence. Each "present" field adds 1/total_fields
    # to the score; missing fields keep the score below 0.8 to signal that
    # human confirmation is required before locking.
    directly_supported = 0
    total_fields = 6  # risk_level, hitl_level, risk_items, prohibited, fatal, audit
    if risk_items:
        directly_supported += 1
    if prohibited_conditions:
        directly_supported += 1
    if fatal_errors:
        directly_supported += 1
    if any(r.get("configured") for r in audit_requirements if isinstance(r, dict)):
        directly_supported += 1
    if risk_level != "L1" or any(kw in combined_text for kw in RISK_L2_KEYWORDS + RISK_L3_KEYWORDS):
        directly_supported += 1
    if manual_points:
        directly_supported += 1

    overall_confidence = min(0.95, directly_supported / total_fields) if total_fields > 0 else 0.3
    # Cap at 0.8 when some fields are inferred
    if directly_supported < total_fields:
        overall_confidence = min(overall_confidence, 0.8)

    confidence = {
        "overall": round(overall_confidence, 2),
        "field_scores": {
            "boundary": round(min(0.9, 0.5 + 0.1 * len(all_refs)), 2) if all_refs else 0.3,
            "process_nodes": round(min(0.9, 0.5 + 0.1 * len(all_refs)), 2) if all_refs else 0.3,
            "risk_items": round(min(0.9, 0.6 + 0.05 * len(risk_items)), 2) if risk_items else 0.3,
            "hitl_rules": round(min(0.9, 0.6 + 0.1 * len(hitl_rules)), 2) if hitl_rules else 0.3,
            "audit_requirements": round(min(0.9, 0.5 + 0.1 * sum(1 for r in audit_requirements if isinstance(r, dict) and r.get("configured"))), 2) if audit_requirements else 0.3,
        },
    }

    # ── To-confirm items ──────────────────────────────────────────────

    to_confirm: list[dict] = []
    # If some risk fields lack direct evidence, add to_confirm
    if not prohibited_conditions and risk_level == "L3":
        to_confirm.append({
            "field": "prohibited_conditions",
            "question": "当前 L3 风险场景是否有其他禁止条件未在材料中明确？",
            "reason": "L3 风险需要完整的禁止条件清单",
            "source_refs": list(all_refs),
        })
    if not fatal_errors and risk_level == "L3":
        to_confirm.append({
            "field": "fatal_errors",
            "question": "当前 L3 风险场景是否有其他致命错误场景未在材料中明确？",
            "reason": "L3 风险需要完整的致命错误清单",
            "source_refs": list(all_refs),
        })

    # P2-boundary: add to_confirm item when boundary_flag is True
    if boundary_flag:
        to_confirm.append({
            "field": "boundary_flag",
            "question": "同时命中L2和L3风险关键词，建议人工复核风险等级是否合理",
            "reason": "L2+L3关键词同时存在可能表示场景处于等级边界",
            "source_refs": list(all_refs),
        })

    # P2: governance fields are no longer auto-filled. When they are required
    # (mandatory HITL / L3), emit to_confirm entries so a human must supply
    # the value before the stage can lock. Empty string + to_confirm is the
    # contract-expected "missing but actionable" state.
    if hitl_level == "mandatory":
        to_confirm.append({
            "field": "alternative_channel",
            "question": "mandatory HITL 场景须配置替代渠道（PIPL §24），请人工确认。",
            "reason": "PIPL 第二十四条：不得仅通过自动化决策方式作出决定，须有不依赖算法的替代渠道",
            "source_refs": list(all_refs),
        })
    if risk_level == "L3":
        to_confirm.append({
            "field": "approval_subject",
            "question": "L3 风险场景须由风险管理委员会批准（NFRA 第十六条），请人工确认。",
            "reason": "NFRA 第十六条：风险管理类高风险应用须经本机构风险管理委员会批准",
            "source_refs": list(all_refs),
        })

    # ── Risk confidence distribution (P1-1) ──────────────────────────
    from src.apps.api.app.agents.risk_semantic import compute_risk_confidence_distribution

    risk_confidence = compute_risk_confidence_distribution(
        semantic_result,
        evidence_report=evidence_report,
        llm_client=llm_client,
    )

    raw_output = {
        "risk_level": risk_level,
        "hitl_level": hitl_level,
        "risk_items": risk_items,
        "risk_matrix": risk_matrix,
        "hitl_rules": hitl_rules,
        "prohibited_conditions": prohibited_conditions,
        "fatal_errors": fatal_errors,
        "audit_requirements": audit_requirements,
        "confidence": confidence,
        "to_confirm": to_confirm,
        "boundary_flag": boundary_flag,
        "evidence_refs": list(all_refs),
        "risk_confidence": {
            "L1": risk_confidence.L1,
            "L2": risk_confidence.L2,
            "L3": risk_confidence.L3,
            "dominant_level": risk_confidence.dominant_level,
            "boundary_flag": risk_confidence.boundary_flag,
            "source": risk_confidence.source,
        },
        # §3.2.2 PIPL §24 替代渠道 + §3.2.3 NFRA §16 批准主体 — P2 起不再
        # 自动填默认值。mandatory / L3 场景由 to_confirm 提示人工确认，
        # 值为空时 contract 校验 + lock 门禁会正确拒绝锁定。
        "alternative_channel": "",
        "approval_subject": "",
        # §3.2.1 STS 六变量诊断（默认值 unmapped，等待业务侧或 LLM 补全）
        "sts_diagnosis": {
            "autonomy": "unmapped",
            "responsibility": "unmapped",
            "task_integrity": "unmapped",
            "diversity": "unmapped",
            "social_support": "unmapped",
            "boundary_spanning": "unmapped",
        },
        # §3.2 步骤2 KOITL 四类组织循环（L2/L3 默认给出骨架，待人工/LLM 补全）
        # P2 数据契约对齐论文：loop_type / responsible_role / frequency / mandatory_flag
        "org_loops": (
            [
                {"loop_id": "loop-ua", "loop_type": "UA-Tasks",
                 "responsible_role": "风险经理 / 合规经理",
                 "frequency": "per_decision", "mandatory_flag": risk_level == "L3",
                 "responsibility": "AI 使用循环：复核与审批频率",
                 "evidence_refs": list(all_refs)[:1]},
                {"loop_id": "loop-ca", "loop_type": "CA-Tasks",
                 "responsible_role": "科技 / 规则维护",
                 "frequency": "per_release", "mandatory_flag": False,
                 "responsibility": "AI 定制循环：谁维护规则",
                 "evidence_refs": []},
                {"loop_id": "loop-o", "loop_type": "O-Tasks",
                 "responsible_role": "业务负责人",
                 "frequency": "per_decision", "mandatory_flag": risk_level == "L3",
                 "responsibility": "原任务循环：业务负责人签字链",
                 "evidence_refs": [primary_evidence_id]},
                {"loop_id": "loop-c", "loop_type": "C-Tasks",
                 "responsible_role": "合规 / 监管联络",
                 "frequency": "quarterly", "mandatory_flag": risk_level == "L3",
                 "responsibility": "上下文变化循环：监管/业务变化触发再评估",
                 "evidence_refs": []},
            ]
            if risk_level in {"L2", "L3"} else []
        ),
    }

    # P0-negation: include negation warnings in ToolResult
    all_warnings: list[str] = []
    if negation_warnings:
        all_warnings.extend(negation_warnings)

    return ToolResult(
        name="risk_identify",
        summary=f"已识别阶段一风险: {risk_level}, HITL: {hitl_level}。",
        raw_output=raw_output,
        evidence_refs=list(all_refs),
        warnings=all_warnings,
    )


def value_model_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    # Consume Stage 1 risk level to influence implementation_tax
    stage1_summary = (previous_stage_result or {}).get("scenario_summary", {})
    risk_level = stage1_summary.get("risk_level", "L1")
    hitl_level = stage1_summary.get("hitl_level", "none")

    # Map risk/HITL to implementation tax (legacy qualitative bucket)
    if risk_level == "L3" or hitl_level == "mandatory":
        impl_tax = "high"
    elif risk_level == "L2" or hitl_level in {"strict", "standard"}:
        impl_tax = "medium"
    else:
        impl_tax = "low"

    warnings: list[str] = []
    if not previous_stage_result:
        warnings.append("No Stage 1 result found; using default low implementation tax.")
    if not stage1_summary:
        warnings.append("No scenario_summary in Stage 1 result; risk-aware value modeling disabled.")

    value_inputs = (previous_stage_result or {}).get("value_inputs", {})
    implementation_tax_items = list(value_inputs.get("implementation_tax_items", []) or [])
    benefit_items = list(value_inputs.get("benefit_items", []) or [])
    parameter_sources = list(value_inputs.get("parameter_sources", []) or [])
    sensitivity_params = list(value_inputs.get("sensitivity_params", []) or [])

    def _num(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _money(value: float) -> float:
        return round(value, 2)

    # ── 式(1): delegate implementation-tax computation to formulas package ──
    from src.apps.api.app.services.formulas import compute_implementation_tax

    tax_result = compute_implementation_tax(
        items=implementation_tax_items, hitl_level=hitl_level
    )
    implementation_tax_total: float | None
    if tax_result["missing_parameters"]:
        # Missing inputs → cannot sum; report None to preserve "do not
        # fabricate net_value" invariant (§3.3.2).
        implementation_tax_total = None
        missing_parameters = list(tax_result["missing_parameters"])
    else:
        implementation_tax_total = _money(tax_result["implementation_tax_total"])
        missing_parameters = []

    gross_benefit = _num(value_inputs.get("expected_benefit"))
    ai_operating_cost = _num(value_inputs.get("ai_operating_cost"))
    if gross_benefit is None:
        missing_parameters.append("expected_benefit")
    if ai_operating_cost is None:
        missing_parameters.append("ai_operating_cost")
    if _num(value_inputs.get("manual_baseline_cost")) is None:
        missing_parameters.append("manual_baseline_cost")

    # ── 式(2): delegate net-value computation to formulas package ──
    from src.apps.api.app.services.formulas import compute_net_value

    can_calculate_net = (
        gross_benefit is not None
        and ai_operating_cost is not None
        and implementation_tax_total is not None
    )
    net_value: float | None = None
    if can_calculate_net:
        nv_result = compute_net_value(
            gross_benefit=gross_benefit,
            ai_operating_cost=ai_operating_cost,
            implementation_tax_total=implementation_tax_total,
        )
        net_value = _money(nv_result["net_value"]) if nv_result["net_value"] is not None else None

    required_supplements = [
        {
            "field": field,
            "reason": "value_parameter_missing",
            "suggested_action": "补充有来源的成本、收益或数量参数后再计算净价值。",
        }
        for field in sorted(set(missing_parameters))
    ]

    # ── §3.3.4: delegate sensitivity analysis to formulas package ──
    from src.apps.api.app.services.formulas import compute_sensitivity

    sensitivity_results: list[dict] = []
    if can_calculate_net:
        # Build perturbation rows.  The legacy tool computed low_net/high_net
        # inline per param name; we preserve that logic to populate the
        # sensitivity params dict, then hand to compute_sensitivity for the
        # conclusion_flip verdict.
        sens_rows: list[dict] = []
        base_tax_total = implementation_tax_total
        for param in sensitivity_params:
            name = param.get("param", "")
            low = _num(param.get("low"))
            high = _num(param.get("high"))
            if not name or low is None or high is None:
                continue
            low_net = gross_benefit - ai_operating_cost - base_tax_total
            high_net = low_net
            if name in {"ai_operating_cost"}:
                low_net = gross_benefit - low - base_tax_total
                high_net = gross_benefit - high - base_tax_total
            elif name in {"review_unit_cost"}:
                review_quantity = 0.0
                other_tax = 0.0
                for item in implementation_tax_items:
                    unit_cost = _num(item.get("unit_cost"))
                    quantity = _num(item.get("quantity"))
                    if unit_cost is None or quantity is None:
                        continue
                    if item.get("category") == "review":
                        review_quantity += quantity
                    else:
                        other_tax += unit_cost * quantity
                low_net = gross_benefit - ai_operating_cost - (other_tax + low * review_quantity)
                high_net = gross_benefit - ai_operating_cost - (other_tax + high * review_quantity)
            elif name in {"review_quantity"}:
                review_unit_cost = 0.0
                other_tax = 0.0
                for item in implementation_tax_items:
                    unit_cost = _num(item.get("unit_cost"))
                    quantity = _num(item.get("quantity"))
                    if unit_cost is None or quantity is None:
                        continue
                    if item.get("category") == "review":
                        review_unit_cost = max(review_unit_cost, unit_cost)
                    else:
                        other_tax += unit_cost * quantity
                low_net = gross_benefit - ai_operating_cost - (other_tax + review_unit_cost * low)
                high_net = gross_benefit - ai_operating_cost - (other_tax + review_unit_cost * high)
            elif name in {"processing_volume"}:
                base_volume = _num(value_inputs.get("processing_volume")) or high or 1.0
                variable_benefit = gross_benefit / base_volume if base_volume else 0.0
                low_net = (variable_benefit * low) - ai_operating_cost - base_tax_total
                high_net = (variable_benefit * high) - ai_operating_cost - base_tax_total
            elif name in {"conversion_lift", "rework_reduction", "risk_screening_benefit", "quality_improvement"}:
                base = _num(param.get("base")) or 0.0
                low_net = (gross_benefit - base + low) - ai_operating_cost - base_tax_total
                high_net = (gross_benefit - base + high) - ai_operating_cost - base_tax_total
            sens_rows.append({
                "param": name,
                "low": low,
                "high": high,
                "low_net": low_net,
                "high_net": high_net,
                "regulatory_floor": param.get("regulatory_floor", False),
            })
        sens_result = compute_sensitivity(params=sens_rows)
        # Translate back to the legacy sensitivity_results shape.
        for row in sens_result["sensitivity_table"]:
            sensitivity_results.append({
                "param": row["param"],
                "low_net_value": _money(row["low_net"]) if row["low_net"] is not None else None,
                "high_net_value": _money(row["high_net"]) if row["high_net"] is not None else None,
                "conclusion_flip": row["conclusion_flip"],
            })

    break_even_conditions = []
    if can_calculate_net:
        break_even_conditions.append({
            "condition": "gross_benefit >= ai_operating_cost + implementation_tax_total",
            "break_even_gross_benefit": _money(ai_operating_cost + implementation_tax_total),
            "current_gross_benefit": _money(gross_benefit),
        })
    else:
        break_even_conditions.append({
            "condition": "补齐 required_supplements 后计算 gross_benefit >= ai_operating_cost + implementation_tax_total",
            "missing_parameters": sorted(set(missing_parameters)),
        })

    assumption_refs = [
        {
            "field": source.get("field", ""),
            "source": source.get("source", ""),
        }
        for source in parameter_sources
        if source.get("field") or source.get("source")
    ]

    review_status = "ready_for_probe" if can_calculate_net else "need_supplement"

    return ToolResult(
        name="value_model",
        summary="已生成价值建模结论。",
        raw_output={
            "estimated_value": "medium",
            "implementation_tax": impl_tax,
            "implementation_tax_items": implementation_tax_items,
            "implementation_tax_total": implementation_tax_total,
            "gross_benefit": _money(gross_benefit) if gross_benefit is not None else None,
            "ai_operating_cost": _money(ai_operating_cost) if ai_operating_cost is not None else None,
            "net_value": net_value,
            "net_value_formula": "net_value = gross_benefit - ai_operating_cost - implementation_tax_total",
            "benefit_items": benefit_items,
            "sensitivity_results": sensitivity_results,
            "break_even_conditions": break_even_conditions,
            "required_supplements": required_supplements,
            "assumption_refs": assumption_refs,
            "review_status": review_status,
            "stage1_risk_level": risk_level,
            "stage1_hitl_level": hitl_level,
            "goal": goal,
            "stage_name": stage_name,
        },
        evidence_refs=[],
        warnings=warnings,
    )


def sla_target_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    """Stage 2 tool: derive target SLA via 式(3) back-deduction.

    Replaces the old fixed sla_map {L3:99%, L2:97%, L1:95%} with the
    thesis formula: SLA_tgt = SLA_floor,d(R) + α_d · r, where r is the
    net-value gain ratio.  When net_value is unavailable (Stage 2 value
    model not yet run), the target degenerates to the risk floor
    (r=0) — this is the "准入门槛" interpretation, not a prediction.
    """
    from src.apps.api.app.services.formulas import (
        compute_target_sla,
        resolve_floor_comprehensive,
    )

    # Consume Stage 1 risk level
    stage1_summary = (previous_stage_result or {}).get("scenario_summary", {})
    risk_level = stage1_summary.get("risk_level", "L1")
    hitl_level = stage1_summary.get("hitl_level", "none")

    # Source net_value: prefer Stage 2 partial output (value_model_tool
    # ran earlier in the same stage), then value_inputs pre-seed.
    net_value: float | None = None
    if previous_stage_result:
        # value_model_tool raw_output is often hoisted to top level
        net_value = _sla_num(previous_stage_result.get("net_value"))
        if net_value is None:
            stage2_partial = previous_stage_result.get("stage2_summary") or {}
            net_value = _sla_num(stage2_partial.get("net_value"))
        if net_value is None:
            value_inputs = previous_stage_result.get("value_inputs") or {}
            net_value = _sla_num(value_inputs.get("net_value"))

    warnings: list[str] = []
    stability = "confirmed"

    if not previous_stage_result:
        stability = "needs_confirmation"
        warnings.append("No Stage 1 result found; target SLA degenerates to risk floor.")
    if not stage1_summary:
        stability = "needs_confirmation"
        warnings.append("No scenario_summary in Stage 1 result; SLA target may need adjustment.")

    # ── 式(3)(3a): back-deduce target SLA from net_value ──
    if net_value is not None:
        sla_result = compute_target_sla(
            risk_level=risk_level,
            net_value=net_value,
        )
        target_sla = sla_result["target_sla"]
        r = sla_result["r"]
        target_sla_by_dim = sla_result["target_sla_by_dim"]
        v_min = sla_result["v_min"]
        v_max = sla_result["v_max"]
        # Override stability from gain-ratio clamping/degenerate state
        stability = sla_result["stability"]
        if stability == "needs_confirmation":
            warnings.append(
                f"Gain ratio r={r} is degenerate or clamped; target SLA "
                f"({target_sla:.1f}) requires HITL confirmation."
            )
    else:
        # Degenerate: r=0 → target SLA = risk floor (准入门槛)
        floor = resolve_floor_comprehensive(risk_level)
        if floor is None:
            floor = 85.0  # L1 default for unknown risk levels
            warnings.append(f"Unknown risk_level {risk_level!r}; defaulting to L1 floor.")
        target_sla = round(floor, 2)
        r = 0.0
        target_sla_by_dim = None
        v_min = None
        v_max = None
        stability = "needs_confirmation"
        warnings.append(
            "net_value not available; target SLA degenerates to risk floor "
            f"({target_sla:.1f}). Run value_model_tool first for back-deduction."
        )

    # Build per-dimension components for backward compatibility
    target_sla_pct_str = f"{target_sla:.1f}%"
    target_sla_components = {
        "quality": {
            "target": target_sla_pct_str,
            "basis": f"{risk_level} risk level; 式(3) back-deduction (r={r:.2f})",
        },
        "efficiency": {
            "target": "manual_baseline_time_reduction_without_HITL_bypass",
            "manual_baseline_time": (previous_stage_result or {}).get(
                "value_inputs", {}
            ).get("manual_baseline_time"),
        },
        "governance": {
            "target": "mandatory_human_confirmation" if risk_level == "L3" or hitl_level == "mandatory" else "sampled_or_standard_review",
            "hitl_level": hitl_level,
        },
    }

    raw_output: dict[str, Any] = {
        "target_sla": target_sla,
        "target_sla_pct": target_sla_pct_str,
        "target_sla_components": target_sla_components,
        "stability": stability,
        "stage1_risk_level": risk_level,
        "goal": goal,
        "stage_name": stage_name,
    }
    # Include 式(3) back-deduction artifacts when available
    if net_value is not None:
        raw_output["r"] = r
        raw_output["target_sla_by_dim"] = target_sla_by_dim
        raw_output["v_min"] = v_min
        raw_output["v_max"] = v_max
        raw_output["net_value"] = net_value
        raw_output["formula"] = "SLA_tgt = Σ_d w_d · (SLA_floor,d(R) + α_d · r)"
    else:
        raw_output["r"] = 0.0
        raw_output["formula"] = "SLA_tgt = SLA_floor(R) (degenerate, r=0)"

    return ToolResult(
        name="sla_target",
        summary="已生成目标 SLA 建议。",
        raw_output=raw_output,
        evidence_refs=[],
        warnings=warnings,
    )


def _sla_num(value: Any) -> float | None:
    """Extract a float from a value, rejecting bool/None/str."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # Try stripping "%" from strings
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def sample_score_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    """Stage 3 tool: generate atomic tasks + rubric + sample scores.

    P2-6 refactor: replaces fixed risk-level scalars with 式(4) structural
    inputs — atomic_task_decomposer (P2-1) + rubric_designer (P2-2) +
    compute_actual_sla (P2-3) + compute_error_rates (P2-5).  The actual
    SLA is now computed from the rubric seed, not a fixed 94.

    L3 scenarios produce more low-score samples; L1 fewer.
    Consumes previous_stage_result for risk differentiation.
    """
    from src.apps.api.app.agents.subagents import (
        decompose_atomic_tasks,
        design_rubric,
    )

    stage1_summary = (previous_stage_result or {}).get("scenario_summary", {})
    risk_level = stage1_summary.get("risk_level", "L1")
    scenario_key = (previous_stage_result or {}).get("scenario_key") or (
        "loan_post" if risk_level == "L3" else None
    )

    # ── P2-1: decompose atomic tasks from SOP ──
    task_result = decompose_atomic_tasks(
        scenario_key=scenario_key,
        process_nodes=(previous_stage_result or {}).get("process_nodes"),
    )
    atomic_tasks = task_result.atomic_tasks

    # ── P2-2: design three-dimension rubric ──
    rubric_result = design_rubric(
        scenario_key=scenario_key, atomic_tasks=atomic_tasks
    )
    rubric = rubric_result.rubric

    # Risk-aware sample generation (probe mock — P3 will replace with real probe)
    base_sample_size = 12
    if risk_level == "L3":
        sample_size = base_sample_size + 4  # More samples for high-risk
        low_score_samples = 4  # Higher failure rate
        score_distribution = {"high": 3, "medium": 5, "low": 4}
    elif risk_level == "L2":
        sample_size = base_sample_size + 2
        low_score_samples = 2
        score_distribution = {"high": 5, "medium": 5, "low": 2}
    else:
        sample_size = base_sample_size
        low_score_samples = 1
        score_distribution = {"high": 7, "medium": 4, "low": 1}

    evidence_refs = []
    if evidence_items:
        evidence_refs = [item.get("id", "") for item in evidence_items[:3] if isinstance(item, dict)]

    warnings = []
    if not previous_stage_result:
        warnings.append("No Stage 1 result found; using L1 defaults for sample generation.")

    return ToolResult(
        name="sample_score",
        summary="已生成样本评分摘要。",
        raw_output={
            "sample_size": sample_size,
            "low_score_samples": low_score_samples,
            "score_distribution": score_distribution,
            "risk_level": risk_level,
            "atomic_tasks": atomic_tasks,
            "rubric": rubric,
            "evidence_refs": evidence_refs,
            "goal": goal,
            "stage_name": stage_name,
        },
        evidence_refs=evidence_refs,
        warnings=warnings,
    )


def actual_sla_summary_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    """Stage 3 tool: compute actual SLA from rubric scores (式(4)).

    P2-6 refactor: replaces fixed risk-level scalars (L3=94/L2=92/L1=90)
    with 式(4) three-dim weighted aggregation via compute_actual_sla,
    plus compute_error_rates (fatal/general/audit completeness) and
    grade_gap five-tier grading.  The actual SLA is now computed from
    rubric scores, not a fixed constant — when no probe scores are
    available it falls back to a risk-floor-derived mock.
    """
    from src.apps.api.app.services.formulas import (
        compute_actual_sla,
        compute_error_rates,
        grade_gap,
    )

    stage1_summary = (previous_stage_result or {}).get("scenario_summary", {})
    risk_level = stage1_summary.get("risk_level", "L1")

    # Source target_sla from Stage 2 result (sla_target_tool output)
    target_sla: float
    stage2 = previous_stage_result or {}
    if stage2.get("target_sla") is not None:
        target_sla = _sla_num(stage2.get("target_sla")) or _risk_floor(risk_level)
    elif (stage2.get("stage2_summary") or {}).get("target_sla") is not None:
        target_sla = _sla_num(stage2["stage2_summary"]["target_sla"]) or _risk_floor(risk_level)
    else:
        target_sla = _risk_floor(risk_level)

    # Source rubric_scores + samples from probe execution (P3) or
    # previous_stage_result.  When unavailable, fall back to a mock
    # probe derived from the risk floor so the tool remains callable
    # in isolation (Stage 3 contract still validates structure).
    rubric_scores = (previous_stage_result or {}).get("rubric_scores") or []
    probe_samples = (previous_stage_result or {}).get("probe_samples") or []

    if rubric_scores:
        sla_result = compute_actual_sla(rubric_scores=rubric_scores)
        actual_sla = sla_result["actual_sla"]
        actual_sla_by_dim = sla_result["actual_sla_by_dim"]
        score_distribution = sla_result["score_distribution"]
    else:
        # Fallback: mock actual SLA slightly below target (probe not run)
        actual_sla = round(target_sla - 5.0, 2)
        actual_sla_by_dim = None
        score_distribution = {"high": 0, "medium": 0, "low": 0}

    # Error rates + audit completeness (§3.4.4/§3.5.2)
    if probe_samples:
        err_result = compute_error_rates(samples=probe_samples, risk_level=risk_level)
        fatal_error_rate = err_result["fatal_error_rate"]
        general_error_rate = err_result["general_error_rate"]
        audit_completeness = err_result["audit_completeness"]
        critical_field_completeness = err_result["critical_field_completeness"]
        fatal_violation = err_result["fatal_violation"]
        general_violation = err_result["general_violation"]
        audit_violation = err_result["audit_violation"]
    else:
        # Fallback: zero-error mock (probe not run)
        fatal_error_rate = 0.0
        general_error_rate = 0.0
        audit_completeness = 1.0
        critical_field_completeness = 1.0
        fatal_violation = False
        general_violation = False
        audit_violation = False

    # Gap grading (§3.4.4 five-tier + L3 escalation)
    delta_sla = round(actual_sla - target_sla, 2)
    gap_result = grade_gap(
        delta_sla=delta_sla, target_sla=target_sla, risk_level=risk_level
    )
    gap_grade = gap_result["gap_grade"]
    relative_gap_pct = gap_result["relative_gap_pct"]
    l3_escalation = gap_result["l3_escalation"]

    gap_to_target_pct = int(delta_sla)

    stability = "confirmed"
    warnings: list[str] = []
    if not previous_stage_result:
        stability = "needs_confirmation"
        warnings.append("No Stage 1 result found; using default SLA summary.")
    if gap_to_target_pct < -5:
        stability = "unstable"
        warnings.append(f"SLA is {abs(gap_to_target_pct)}pp under target, exceeding 5pp threshold.")
    if fatal_violation:
        stability = "unstable"
        warnings.append("Fatal error detected (硬约束: fatal_error_rate must be 0).")
    if l3_escalation:
        warnings.append("L3 gap exceeds 5% → escalated to hard constraint (sla_gap_l3).")

    evidence_refs = []
    if evidence_items:
        evidence_refs = [item.get("id", "") for item in evidence_items[:3] if isinstance(item, dict)]

    return ToolResult(
        name="actual_sla_summary",
        summary="已汇总 Actual SLA。",
        raw_output={
            "actual_sla": actual_sla,
            "actual_sla_by_dim": actual_sla_by_dim,
            "target_sla": target_sla,
            "gap_to_target_pct": gap_to_target_pct,
            "gap_grade": gap_grade,
            "relative_gap_pct": relative_gap_pct,
            "l3_escalation": l3_escalation,
            "fatal_error_rate": fatal_error_rate,
            "general_error_rate": general_error_rate,
            "audit_completeness": audit_completeness,
            "critical_field_completeness": critical_field_completeness,
            "fatal_violation": fatal_violation,
            "general_violation": general_violation,
            "audit_violation": audit_violation,
            "score_distribution": score_distribution,
            "stability": stability,
            "risk_level": risk_level,
            "evidence_refs": evidence_refs,
            "goal": goal,
            "stage_name": stage_name,
        },
        evidence_refs=evidence_refs,
        warnings=warnings,
    )


def _risk_floor(risk_level: str) -> float:
    """Return the comprehensive SLA floor for a risk level (式(3))."""
    floors = {"L1": 85.0, "L2": 90.0, "L3": 95.0}
    return floors.get(risk_level, 85.0)


def evidence_bundle_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    """Stage 4 tool: collect evidence from preceding stages.

    Aggregates evidence_refs from Stage 1-3 results and current evidence_items.
    Outputs bundle_status and evidence_count for contract validation.
    """
    # Collect evidence from previous stage results
    evidence_ids: list[str] = []
    gaps: list[str] = []

    if previous_stage_result:
        prev_refs = (previous_stage_result.get("scenario_summary") or {}).get("evidence_refs", [])
        evidence_ids.extend(prev_refs)
    if evidence_items:
        evidence_ids.extend(item.get("id", "") for item in evidence_items if isinstance(item, dict) and item.get("id"))

    # Deduplicate
    evidence_ids = list(dict.fromkeys(evidence_ids))
    evidence_count = len(evidence_ids)

    # Determine bundle status
    bundle_status = "draft"
    if evidence_count >= 3:
        bundle_status = "locked"
    elif evidence_count >= 1:
        bundle_status = "review"
        gaps.append(f"证据数量不足 ({evidence_count}/3)，建议补充")

    if evidence_count == 0:
        gaps.append("无证据引用，报告无法生成")

    warnings = []
    if gaps:
        warnings.extend(gaps)

    return ToolResult(
        name="evidence_bundle",
        summary="已汇总证据链摘要。",
        raw_output={
            "bundle_status": bundle_status,
            "evidence_count": evidence_count,
            "evidence_ids": evidence_ids,
            "gaps": gaps,
            "evidence_refs": evidence_ids,
            "goal": goal,
            "stage_name": stage_name,
        },
        evidence_refs=evidence_ids,
        warnings=warnings,
    )


def report_generate_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    """Stage 4 tool: generate structured report outline from Stage 1-3 results.

    Produces risk-aware report sections and decision_card.

    P4-5 enhancement (§3.5.3 report-writer-agent): now integrates the
    evidence-fusion Sub-agent (P4-3) to produce the three-dimension
    evidence fusion table section + per-actor section + remediation
    items section, and emits a ``decision_card.verdict`` of go/hold/nogo
    derived from 式(6) ``compute_decision`` (replacing the old fixed
    risk-level scalars).  The verdict is computed from G_hard (式(5)) +
    delta_sla + net_value when those inputs are available; otherwise it
    falls back to the risk-level heuristic.
    """
    from src.apps.api.app.agents.subagents import fuse_three_dim_evidence
    from src.apps.api.app.services.formulas import compute_decision

    stage1_summary = (previous_stage_result or {}).get("scenario_summary", {})
    risk_level = stage1_summary.get("risk_level", "L1")

    # ── P4-3: evidence fusion (§3.5.1) ──
    stage2_summary = (previous_stage_result or {}).get("stage2_summary", {})
    stage3_summary = (previous_stage_result or {}).get("stage3_summary", {})
    # actual_sla_summary_tool emits flat fields; normalize to a summary dict
    if not stage3_summary and previous_stage_result:
        stage3_summary = {
            k: previous_stage_result.get(k)
            for k in (
                "actual_sla",
                "actual_sla_by_dim",
                "fatal_error_rate",
                "general_error_rate",
                "audit_completeness",
                "gap_grade",
                "per_task",
            )
            if k in (previous_stage_result or {})
        }

    atomic_tasks = (previous_stage_result or {}).get("atomic_tasks") or []

    fusion_result = fuse_three_dim_evidence(
        stage1_summary=stage1_summary,
        stage2_summary=stage2_summary,
        stage3_summary=stage3_summary,
        atomic_tasks=atomic_tasks,
        risk_level=risk_level,
    )

    # ── 式(6) decision verdict (go/hold/nogo) ──
    target_sla = _sla_num(stage2_summary.get("target_sla")) if stage2_summary else None
    actual_sla = _sla_num(stage3_summary.get("actual_sla")) if stage3_summary else None
    net_value = _sla_num(stage2_summary.get("net_value")) if stage2_summary else None

    delta_sla: Optional[float] = None
    if actual_sla is not None and target_sla is not None:
        delta_sla = round(actual_sla - target_sla, 2)

    # G_hard from fusion hard-constraint failures (否决级)
    hard_failures = fusion_result.hard_constraint_failures
    g_hard = len(hard_failures) == 0

    # Only run compute_decision when we have enough inputs; else fall back
    verdict: str
    decision_rationale: str
    remediation_items: list[dict] = []
    dec_path: str = ""

    if g_hard and delta_sla is not None and net_value is not None:
        # Full 式(6) decision
        dec = compute_decision(
            g_hard=g_hard,
            delta_sla=delta_sla,
            net_value=net_value,
            risk_level=risk_level,
            target_sla=target_sla,
            failed_terms=hard_failures,
        )
        verdict = dec["verdict"]
        decision_rationale = dec["decision_rationale"]
        remediation_items = dec.get("remediation_items", [])
        dec_path = dec.get("dec_path", "")
    elif not g_hard:
        verdict = "nogo"
        decision_rationale = "硬约束未通过（G_hard=0），建议不予立项并补配退出 AI 替代方案。"
        dec_path = "式(6)第一条 G_hard=0 → nogo (fusion hard-failures)"
    else:
        # Fallback: risk-level heuristic (insufficient inputs for full 式(6))
        if risk_level == "L3":
            verdict = "hold"
            decision_rationale = "L3 场景输入不足，按风险底线暂缓论证。"
        elif risk_level == "L2":
            verdict = "hold"
            decision_rationale = "L2 场景输入不足，建议补充论证。"
        else:
            verdict = "go"
            decision_rationale = "低风险场景且无硬约束失败，建议立项。"
        dec_path = "fallback (insufficient inputs for 式(6))"

    # ── Risk-aware report sections ──
    base_sections = [
        {"title": "场景概述", "status": "draft"},
        {"title": "价值建模结论", "status": "draft"},
        {"title": "样本评分结果", "status": "draft"},
        {"title": "三维证据融合表", "status": "draft"},  # P4-5 new section
        {"title": "逐 actor 盈利性", "status": "draft"},  # P4-5 new section
        {"title": "补齐项清单", "status": "draft" if remediation_items else "n/a"},
    ]
    if risk_level in {"L2", "L3"}:
        base_sections.extend([
            {"title": "风险评估", "status": "draft"},
            {"title": "HITL 建议", "status": "draft"},
        ])
    if risk_level == "L3":
        base_sections.extend([
            {"title": "禁止条件复核", "status": "draft"},
            {"title": "致命错误分析", "status": "draft"},
        ])

    # ── Decision card (§3.5.3 verdict = go/hold/nogo) ──
    confidence = 0.9 if verdict == "go" else (0.5 if verdict == "hold" else 0.3)
    decision_card = {
        "verdict": verdict,
        "recommendation": verdict,  # legacy field (go/hold/nogo)
        "confidence": confidence,
        "risk_level": risk_level,
        "decision_rationale": decision_rationale,
        "dec_path": dec_path,
        "g_hard": g_hard,
        "delta_sla": delta_sla,
        "net_value": net_value,
        "hard_constraint_failures": hard_failures,
        "remediation_items": remediation_items,
        "notes": decision_rationale,
    }

    evidence_refs = []
    if evidence_items:
        evidence_refs = [item.get("id", "") for item in evidence_items[:3] if isinstance(item, dict)]

    warnings = []
    if not previous_stage_result:
        warnings.append("No Stage 1 result found; using L1 defaults for report generation.")
    if fusion_result.evidence_conflicts:
        warnings.append(
            f"三维证据冲突 {len(fusion_result.evidence_conflicts)} 项，须回 §3.5.2 硬约束检查解决。"
        )

    report_status = "draft" if verdict == "hold" or not g_hard else "review"

    return ToolResult(
        name="report_generate",
        summary=f"已生成报告草稿，决策结论：{verdict}。",
        raw_output={
            "report_status": report_status,
            "sections": base_sections,
            "decision_card": decision_card,
            "three_dim_fusion_table": fusion_result.three_dim_fusion_table,
            "evidence_conflicts": fusion_result.evidence_conflicts,
            "strength_summary": fusion_result.strength_summary,
            "risk_level": risk_level,
            "evidence_refs": evidence_refs,
            "goal": goal,
            "stage_name": stage_name,
        },
        evidence_refs=evidence_refs,
        warnings=warnings,
    )


def vision_parse_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    vision_results = vision_results or []

    if not vision_results:
        return ToolResult(
            name="vision_parse",
            summary="无视觉解析结果可用。",
            raw_output={
                "vision_ready": False,
                "structured_fields": [],
                "evidence_fragments": [],
                "to_confirm": [],
                "uncertainties": [],
                "process_node_candidates": [],
                "role_candidates": [],
            },
            evidence_refs=[],
            warnings=["No vision results available."],
            status="skipped_missing_input",
        )

    # Aggregate from all vision results
    structured_fields: list[dict] = []
    evidence_fragments: list[dict] = []
    to_confirm: list[dict] = []
    uncertainties: list[str] = []
    process_node_candidates: list[dict] = []
    role_candidates: list[dict] = []

    for vr in vision_results:
        sf = vr.get("structured_fields")
        if sf:
            structured_fields.append(sf if isinstance(sf, dict) else {"value": sf})
        evidence_fragments.extend(vr.get("evidence_fragments", []))
        to_confirm.extend(vr.get("to_confirm", []))
        uncertainties.extend(vr.get("uncertainties", []))
        pnc = vr.get("process_node_candidates", [])
        if isinstance(pnc, list):
            process_node_candidates.extend(pnc)
        rc = vr.get("role_candidates", [])
        if isinstance(rc, list):
            role_candidates.extend(rc)

    return ToolResult(
        name="vision_parse",
        summary="已聚合视觉解析结果。",
        raw_output={
            "vision_ready": True,
            "structured_fields": structured_fields,
            "evidence_fragments": evidence_fragments,
            "to_confirm": to_confirm,
            "uncertainties": uncertainties,
            "process_node_candidates": process_node_candidates,
            "role_candidates": role_candidates,
        },
        evidence_refs=[],
        warnings=[],
    )


def export_bundle_tool(
    *,
    goal: str,
    stage_name: str,
    evidence_items: list[dict] | None = None,
    vision_results: list[dict] | None = None,
    previous_stage_result: dict | None = None,
) -> ToolResult:
    """Stage 4 tool: check export readiness.

    Requires all preceding stages to have non-draft status and
    evidence_count >= 3 from evidence_bundle tool.
    """
    stage1_summary = (previous_stage_result or {}).get("scenario_summary", {})
    risk_level = stage1_summary.get("risk_level", "L1")

    blocking_issues: list[str] = []

    # Check previous stage result exists
    if not previous_stage_result:
        blocking_issues.append("No previous stage result found")

    # Check evidence count from evidence_bundle (would be in tool_results, but
    # we can check evidence_items directly as proxy)
    evidence_count = 0
    if evidence_items:
        evidence_count = len(evidence_items)
    if evidence_count < 3:
        blocking_issues.append(f"Insufficient evidence items ({evidence_count}/3)")

    export_ready = len(blocking_issues) == 0

    evidence_refs = []
    if evidence_items:
        evidence_refs = [item.get("id", "") for item in evidence_items if isinstance(item, dict)]

    return ToolResult(
        name="export_bundle",
        summary="已生成导出包摘要。",
        raw_output={
            "export_ready": export_ready,
            "blocking_issues": blocking_issues,
            "evidence_count": evidence_count,
            "risk_level": risk_level,
            "evidence_refs": evidence_refs,
            "goal": goal,
            "stage_name": stage_name,
        },
        evidence_refs=evidence_refs,
        warnings=[] if export_ready else [f"Export blocked: {', '.join(blocking_issues)}"],
    )


TOOL_HANDLERS = {
    "document_parse": document_parse_tool,
    "vision_parse": vision_parse_tool,
    "risk_identify": risk_identify_tool,
    "value_model": value_model_tool,
    "sla_target": sla_target_tool,
    "sample_score": sample_score_tool,
    "actual_sla_summary": actual_sla_summary_tool,
    "evidence_bundle": evidence_bundle_tool,
    "report_generate": report_generate_tool,
    "export_bundle": export_bundle_tool,
}
