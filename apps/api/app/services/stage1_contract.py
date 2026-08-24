"""Stage 1 contract validation and normalization helpers.

Pure module — no FastAPI, repository, or model client imports.
"""

from __future__ import annotations

import re
from typing import Any

# ── Completeness helpers (P0-completeness) ─────────────────────────────

PLACEHOLDER_VALUES: set[str] = {
    "暂无", "N/A", "n/a", "待补充", "无", "TBD", "tbd",
    "-", "—", "无内容", "未填写", "TODO",
}
"""Placeholder values that indicate a field is substantively empty."""

MIN_SUBSTANTIVE_LENGTH: int = 10
"""Minimum effective character count for a field to be considered substantive."""

# Pre-compiled pattern: matches whitespace and common Chinese/English
# punctuation.  Used to compute "effective" character count when
# judging whether a string is substantive.  Compiled once at import
# time to avoid re-compilation on every call.
_EFFECTIVE_CHAR_RE = re.compile(
    r"[\s\.,;；，。、：:！!？?（）()\[\]【】\"'—\\\-_]"
)


def _is_substantive(value: Any) -> bool:
    """Return True if *value* has substantive content (not a placeholder, >=10 chars).

    For string values: strip whitespace, check against PLACEHOLDER_VALUES,
    then count effective characters (excluding common punctuation).
    For list values: return True if at least one element is substantive.
    For other types: return True if truthy.
    """
    if isinstance(value, list):
        return any(_is_substantive(item) for item in value)
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed in PLACEHOLDER_VALUES:
            return False
        effective = _EFFECTIVE_CHAR_RE.sub("", trimmed)
        return len(effective) >= MIN_SUBSTANTIVE_LENGTH
    # For non-string, non-list (bool, int, etc.): truthy check
    return bool(value)

# ── Contract enum values ──────────────────────────────────────────────

RISK_LEVELS = {"L1", "L2", "L3"}
HITL_LEVELS = {"none", "standard", "strict", "mandatory"}

# ── Boundary review status (F1 business-side acknowledgment) ─────────
BOUNDARY_REVIEW_STATUSES = {
    "business_pending",      # 业务侧尚未认可（研究侧版本，待业务确认）
    "business_confirmed",    # 业务侧已认可边界
    "business_rejected",     # 业务侧退回，需修订边界
}

# ── Risk normalization mappings ───────────────────────────────────────

_RISK_L1_ALIASES = {"low", "低", "l1", "1"}
_RISK_L2_ALIASES = {"medium", "中", "l2", "2"}
_RISK_L3_ALIASES = {"high", "高", "critical", "l3", "3", "高风险"}

_HITL_NONE_ALIASES = {"none", "无", "no_hitl"}
_HITL_STANDARD_ALIASES = {"standard", "标准", "普通"}
_HITL_STRICT_ALIASES = {"strict", "强hitl", "强HITL", "强", "严格"}
_HITL_MANDATORY_ALIASES = {"mandatory", "必须人工", "全量人工", "强制", "必人工"}

# ── Risk keyword lists for deterministic risk identification ───────────

RISK_L3_KEYWORDS = [
    "风险等级调整", "客户处置", "监管敏感", "审计追责",
    "漏报风险", "未脱敏", "客户经营数据", "合规复核",
    "适当性管理", "投资建议", "误导性收益", "对客内容",
    "算法歧视", "模型漂移", "数据跨境",
]
RISK_L2_KEYWORDS = ["人工确认", "审计留痕", "责任人", "对外发送", "复核", "数据隐私", "业务连续性", "模型可解释性"]


# ── Normalization ─────────────────────────────────────────────────────


def normalize_risk_level(value: object) -> str:
    """Normalize a risk level value to contract enum L1|L2|L3.

    Handles English, Chinese, and numeric aliases.
    If the value is already a valid contract value, returns it as-is.
    Raises ``ValueError`` if the value cannot be normalized.
    """
    if value is None:
        raise ValueError("risk_level is None; cannot normalize")

    text = str(value).strip()

    # Already a valid contract value
    if text in RISK_LEVELS:
        return text

    lower = text.lower()
    if lower in _RISK_L1_ALIASES:
        return "L1"
    if lower in _RISK_L2_ALIASES:
        return "L2"
    if lower in _RISK_L3_ALIASES:
        return "L3"

    raise ValueError(f"Cannot normalize risk_level: {value!r}")


def normalize_hitl_level(value: object, *, risk_level: str | None = None) -> str:
    """Normalize a HITL level value to contract enum none|standard|strict|mandatory.

    When *risk_level* is provided, enforces the L3→strict/mandatory constraint.
    Raises ``ValueError`` if the value cannot be normalized or if the
    risk/HITL combination is invalid (e.g. L3 + none/standard).
    """
    if value is None:
        raise ValueError("hitl_level is None; cannot normalize")

    text = str(value).strip()

    # Already a valid contract value
    if text in HITL_LEVELS:
        result = text
    else:
        lower = text.lower()
        if lower in _HITL_NONE_ALIASES:
            result = "none"
        elif lower in _HITL_STANDARD_ALIASES:
            result = "standard"
        elif lower in _HITL_STRICT_ALIASES:
            result = "strict"
        elif lower in _HITL_MANDATORY_ALIASES:
            result = "mandatory"
        else:
            raise ValueError(f"Cannot normalize hitl_level: {value!r}")

    # Enforce L3 risk → strict or mandatory HITL
    if risk_level == "L3" and result not in {"strict", "mandatory"}:
        # Escalate to the minimum acceptable level
        result = "strict"

    return result


# ── Stage 1 HITL policy (L3 / boundary mandates human review) ─────────

def stage1_requires_human_review(
    *, risk_level: str | None, boundary_flag: bool = False
) -> bool:
    """Explicit Stage-1 HITL policy: L3 or boundary risk mandates human review.

    Decoupled from the ``enable_hitl`` checkpoint flag — this function takes
    no such parameter, so the L3-mandatory rule cannot be turned off by the
    harness checkpoint default. An L3/boundary result must not auto-complete
    even when no durable checkpoint was taken. The boolean truth table matches
    the previous inline expression ``bool(risk_level == "L3" or boundary_flag)``
    bit-for-bit (``boundary_flag`` is normalised through ``bool()``).
    """
    if risk_level == "L3":
        return True
    if boundary_flag:
        return True
    return False


# ── Validation ────────────────────────────────────────────────────────


def validate_scenario_deconstruction(summary: dict) -> list[dict]:
    """Phase A — 场景解构校验：占位内容(#10)、edges 悬挂引用(#13)、main_path 不回退(#14)。

    返回 issue dict 列表（空列表表示通过）。不修改输入。
    """
    issues: list[dict] = []

    # 10. Placeholder content detection (P0-completeness)
    _placeholder_check_fields = [
        "scenario_name", "sop_summary", "boundary",
    ]
    for field in _placeholder_check_fields:
        val = summary.get(field)
        if isinstance(val, str) and val.strip() in PLACEHOLDER_VALUES:
            issues.append({
                "issue_type": "placeholder_content",
                "field": field,
                "severity": "medium",
                "message": f"Field '{field}' contains placeholder value: {val!r}",
                "suggested_action": f"Replace placeholder in '{field}' with substantive content",
            })

    # 13. edges reference validity (Stage 1 flow IR)
    #    Each edge's from/to must reference an existing process_nodes[*].node_id.
    process_nodes = summary.get("process_nodes", [])
    known_node_ids = {
        str(node.get("node_id", ""))
        for node in process_nodes
        if isinstance(node, dict) and node.get("node_id")
    }
    edges = summary.get("edges", [])
    if isinstance(edges, list) and edges:
        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            for endpoint in ("from", "to"):
                endpoint_id = str(edge.get(endpoint, ""))
                if endpoint and endpoint_id not in known_node_ids:
                    issues.append({
                        "issue_type": "dangling_edge_ref",
                        "field": f"edges[{idx}].{endpoint}",
                        "severity": "medium",
                        "message": (
                            f"edge {endpoint} {endpoint_id!r} does not match any "
                            f"process_nodes[*].node_id"
                        ),
                        "suggested_action": (
                            "Set from/to to an existing node_id, or drop the edge"
                        ),
                    })

    # 14. main_path no-regression (Stage 1 flow IR)
    #    main_path consecutive pairs must have a matching edge AND not regress in
    #    process_nodes order (borrowed from archify's mainPath rule: loops must
    #    be return edges outside main_path).
    main_path = summary.get("main_path", [])
    if isinstance(main_path, list) and len(main_path) >= 2:
        node_index: dict[str, int] = {
            str(node.get("node_id", "")): i
            for i, node in enumerate(process_nodes)
            if isinstance(node, dict) and node.get("node_id")
        }
        edge_pairs: set[tuple[str, str]] = set()
        if isinstance(edges, list):
            for edge in edges:
                if isinstance(edge, dict):
                    edge_pairs.add(
                        (str(edge.get("from", "")), str(edge.get("to", "")))
                    )
        for i in range(len(main_path) - 1):
            a = str(main_path[i])
            b = str(main_path[i + 1])
            pair = (a, b)
            idx_a = node_index.get(a)
            idx_b = node_index.get(b)
            regresses = (
                idx_a is not None and idx_b is not None and idx_b < idx_a
            )
            missing_edge = pair not in edge_pairs
            if regresses or missing_edge or idx_a is None or idx_b is None:
                issues.append({
                    "issue_type": "main_path_regression",
                    "field": f"main_path[{i}->{i + 1}]",
                    "severity": "high",
                    "message": (
                        f"main_path pair ({a!r} -> {b!r}) "
                        + (
                            "regresses in process_nodes order"
                            if regresses else
                            "has no matching edge"
                            if missing_edge else
                            "references an unknown node_id"
                        )
                    ),
                    "suggested_action": (
                        "Use a return edge (variant=\"return\") outside main_path "
                        "for loops; keep main_path forward in process_nodes order"
                    ),
                })

    return issues


def validate_risk_grading(summary: dict) -> list[dict]:
    """Phase B — 风险定级校验：risk_level 枚举(#1)、hitl_level 枚举(#2)、
    L3→strict/mandatory(#3)、risk_items 非空(#4)、risk_matrix 非空(#5)、
    evidence_refs 非空(#6)、risk_item 证据/to_confirm(#7)、L2/L3 hitl_rules(#8)、
    L3 prohibited+fatal(#9)、证据链(#11)、risk_confidence 主导匹配(#12)。

    返回 issue dict 列表（空列表表示通过）。不修改输入。
    """
    issues: list[dict] = []

    # 1. risk_level must be contract enum
    rl = summary.get("risk_level")
    if rl not in RISK_LEVELS:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "risk_level",
            "severity": "high",
            "message": f"risk_level must be L1|L2|L3, got {rl!r}",
            "suggested_action": "Normalize risk_level using normalize_risk_level()",
        })

    # 2. hitl_level must be contract enum
    hl = summary.get("hitl_level")
    if hl not in HITL_LEVELS:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "hitl_level",
            "severity": "high",
            "message": f"hitl_level must be none|standard|strict|mandatory, got {hl!r}",
            "suggested_action": "Normalize hitl_level using normalize_hitl_level()",
        })

    # 3. L3 must map to strict or mandatory HITL
    if rl == "L3" and hl not in {"strict", "mandatory", None}:
        issues.append({
            "issue_type": "hitl_mismatch",
            "field": "hitl_level",
            "severity": "high",
            "message": f"L3 risk must have strict or mandatory HITL, got {hl!r}",
            "suggested_action": "Set hitl_level to strict or mandatory",
        })

    # 4. risk_items must be non-empty
    risk_items = summary.get("risk_items", [])
    if not risk_items:
        issues.append({
            "issue_type": "missing_field",
            "field": "risk_items",
            "severity": "high",
            "message": "risk_items is empty",
            "suggested_action": "Generate risk items from evidence using risk_identify tool",
        })

    # 5. risk_matrix must be non-empty
    risk_matrix = summary.get("risk_matrix", [])
    if not risk_matrix:
        issues.append({
            "issue_type": "missing_field",
            "field": "risk_matrix",
            "severity": "medium",
            "message": "risk_matrix is empty",
            "suggested_action": "Generate risk matrix from risk items",
        })

    # 6. evidence_refs must be non-empty
    evidence_refs = summary.get("evidence_refs", [])
    if not evidence_refs:
        issues.append({
            "issue_type": "weak_evidence",
            "field": "evidence_refs",
            "severity": "high",
            "message": "scenario_summary has no evidence references",
            "suggested_action": "Bind evidence items to the summary",
        })

    # 7. Each risk_item must have evidence_refs or matching to_confirm
    to_confirm = summary.get("to_confirm", [])
    confirmed_fields = {tc.get("field") for tc in to_confirm if isinstance(tc, dict)}
    for idx, item in enumerate(risk_items):
        if not isinstance(item, dict):
            continue
        item_refs = item.get("evidence_refs", [])
        item_id = item.get("risk_id", f"risk-{idx}")
        if not item_refs and f"risk_items.{item_id}" not in confirmed_fields:
            issues.append({
                "issue_type": "weak_evidence",
                "field": f"risk_items.{item_id}",
                "severity": "medium",
                "message": f"Risk item {item_id} has no evidence_refs and no matching to_confirm",
                "suggested_action": "Add evidence references or create a to_confirm item for this risk",
            })

    # 8. L2/L3 must include HITL rules
    hitl_rules = summary.get("hitl_rules", [])
    if rl in {"L2", "L3"} and not hitl_rules:
        issues.append({
            "issue_type": "missing_field",
            "field": "hitl_rules",
            "severity": "high",
            "message": f"{rl} risk must include HITL rules",
            "suggested_action": "Generate HITL rules mapped to risk level",
        })

    # 9. L3 must include prohibited conditions and fatal errors
    if rl == "L3":
        prohibited = summary.get("prohibited_conditions", [])
        if not prohibited:
            issues.append({
                "issue_type": "missing_field",
                "field": "prohibited_conditions",
                "severity": "high",
                "message": "L3 risk must include prohibited conditions",
                "suggested_action": "Identify prohibited conditions from evidence (e.g. 不得自动...)",
            })
        fatal_errors = summary.get("fatal_errors", [])
        if not fatal_errors:
            issues.append({
                "issue_type": "missing_field",
                "field": "fatal_errors",
                "severity": "high",
                "message": "L3 risk must include fatal errors",
                "suggested_action": "Identify fatal error scenarios from evidence (e.g. 漏报风险, 审计追责)",
            })

    # 11. Evidence chain verification flag (P0-2)
    for idx, item in enumerate(risk_items):
        if not isinstance(item, dict):
            continue
        item_id = item.get("risk_id", f"risk-{idx}")
        if item.get("evidence_verified") is False:
            issues.append({
                "issue_type": "weak_evidence",
                "field": f"risk_items.{item_id}",
                "severity": "medium",
                "message": f"Risk item {item_id} evidence does not semantically support the description",
                "suggested_action": "Review evidence binding or add more specific evidence for this risk item",
            })

    # 12. Risk confidence distribution consistency (P1-1)
    risk_confidence = summary.get("risk_confidence")
    if isinstance(risk_confidence, dict):
        dominant = risk_confidence.get("dominant_level", "")
        if dominant and dominant != rl and rl in RISK_LEVELS:
            issues.append({
                "issue_type": "confidence_mismatch",
                "field": "risk_confidence.dominant_level",
                "severity": "high",
                "message": f"risk_confidence dominant level {dominant!r} does not match risk_level {rl!r}",
                "suggested_action": "Re-run risk classification or adjust confidence distribution",
            })

    # 15. Error amplification paths — M1 硬性收口：L2/L3 至少 3 条可定位的错误放大路径
    error_paths = summary.get("error_amplification_paths", [])
    # An error path is "substantive" when it carries a description OR at least
    # one amplification mechanism. Short Chinese identifiers ("漏报链") fall
    # below the 10-char generic heuristic, so check presence rather than length.
    substantive_paths = [
        p for p in error_paths
        if isinstance(p, dict)
        and (
            str(p.get("description", "")).strip()
            or (
                isinstance(p.get("amplification_mechanisms"), list)
                and any(str(m).strip() for m in p["amplification_mechanisms"])
            )
        )
    ]
    if rl in {"L2", "L3"} and len(substantive_paths) < 3:
        issues.append({
            "issue_type": "missing_field",
            "field": "error_amplification_paths",
            "severity": "high",
            "message": (
                f"{rl} 风险至少需 3 条错误放大路径，当前 {len(substantive_paths)} 条"
            ),
            "suggested_action": "Derive error amplification paths from risk-bound process nodes",
        })

    # 16. Cross-system link coverage — F2 要求流程节点绑定跨系统链路
    links = summary.get("cross_system_links", [])
    process_nodes_all = summary.get("process_nodes", [])
    known_ids = {
        str(node.get("node_id", ""))
        for node in process_nodes_all
        if isinstance(node, dict) and node.get("node_id")
    }
    if process_nodes_all:
        linked_ids = {
            str(link.get("node_id", ""))
            for link in links
            if isinstance(link, dict) and link.get("node_id")
        }
        if known_ids and not linked_ids:
            issues.append({
                "issue_type": "missing_field",
                "field": "cross_system_links",
                "severity": "medium",
                "message": "跨系统链路为空，流程节点未绑定系统",
                "suggested_action": "Bind each process node to its systems （预警平台/贷后系统/核心系统）",
            })

    # 18. Boundary review status — 业务侧认可边界的状态显式可见
    brs = summary.get("boundary_review_status")
    if brs is not None and brs not in BOUNDARY_REVIEW_STATUSES:
        issues.append({
            "issue_type": "invalid_enum",
            "field": "boundary_review_status",
            "severity": "medium",
            "message": f"boundary_review_status must be one of {sorted(BOUNDARY_REVIEW_STATUSES)}, got {brs!r}",
            "suggested_action": "Set to business_pending / business_confirmed / business_rejected",
        })

    return issues


def validate_stage1_summary(summary: dict) -> list[dict]:
    """Validate a Stage 1 ``scenario_summary`` dict.

    Returns a list of issue dicts (empty if valid).  Each issue has:
      issue_type, field, severity, message, suggested_action.

    Thin wrapper over ``validate_scenario_deconstruction`` (Phase A) and
    ``validate_risk_grading`` (Phase B). Does **not** mutate the input.
    """
    return [
        *validate_scenario_deconstruction(summary),
        *validate_risk_grading(summary),
    ]


# ── Quality scoring ────────────────────────────────────────────────────

# Weight per dimension for audit_readiness_score
_QUALITY_WEIGHTS = {
    "completeness": 0.25,
    "evidence_coverage": 0.25,
    "risk_consistency": 0.25,
    "hitl_alignment": 0.25,
}


# Fields whose values are contract enums (not free-form text).
# These should be considered "substantive" when their value is one of
# the allowed enum values, regardless of character count.
_ENUM_FIELDS: set[str] = {"risk_level", "hitl_level"}


def _is_substantive_field(field: str, value: Any) -> bool:
    """Substantive check that respects contract enums.

    For enum-typed fields (``risk_level``, ``hitl_level``) the value
    counts as substantive when it is one of the allowed enum values,
    because contract enums are intentionally short ("L1", "strict").
    For all other fields, fall back to ``_is_substantive``.
    """
    if value is None:
        return False
    if field == "risk_level" and value in RISK_LEVELS:
        return True
    if field == "hitl_level" and value in HITL_LEVELS:
        return True
    return _is_substantive(value)


def _main_path_valid(
    edges: list, main_path: list, process_nodes: list
) -> bool:
    """Return True when ``main_path`` is forward-only and edge-backed.

    Borrowed from archify's mainPath no-regression rule (render-workflow.mjs
    enforces ``to.col >= from.col``); ai-ReqEval uses ``process_nodes`` array
    index as the anchor instead of ``col``. Consecutive pairs in ``main_path``
    must (a) reference existing node ids, (b) have a matching entry in
    ``edges``, and (c) not regress in ``process_nodes`` order. Loops must be
    expressed as ``variant:"return"`` edges outside ``main_path``.
    """
    if not isinstance(main_path, list) or len(main_path) < 2:
        return False
    if not isinstance(edges, list) or not edges:
        return False

    node_index: dict[str, int] = {
        str(node.get("node_id", "")): i
        for i, node in enumerate(process_nodes)
        if isinstance(node, dict) and node.get("node_id")
    }
    edge_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        if isinstance(edge, dict):
            edge_pairs.add((str(edge.get("from", "")), str(edge.get("to", ""))))

    for i in range(len(main_path) - 1):
        a = str(main_path[i])
        b = str(main_path[i + 1])
        idx_a = node_index.get(a)
        idx_b = node_index.get(b)
        if idx_a is None or idx_b is None:
            return False
        if (a, b) not in edge_pairs:
            return False
        if idx_b < idx_a:
            return False
    return True


def compute_scenario_quality(summary: dict) -> dict:
    """Phase A — 场景解构质量维度（8 维，返回原始未取整值）。

    维度：completeness_score、participant_split_score、
    process_node_completeness_score、responsibility_mapping_score、
    responsibility_chain_score、audit_node_mapping_score、
    flow_diagram_score、flow_diagram_generated。

    注意：completeness 的 key_fields 包含风险侧字段（risk_items / risk_matrix /
    risk_level / hitl_level / audit_requirements），因为完整度衡量的是整份
    scenario_summary 的关键字段填充情况，属场景解构维度。不修改输入。
    """
    rl = summary.get("risk_level")

    # Completeness: fraction of key fields with substantive content.
    # Enum-typed fields (risk_level, hitl_level) are checked against
    # their allowed values rather than the 10-char heuristic, so short
    # but valid values like "L1" or "strict" still count.
    key_fields = [
        "scenario_name", "boundary", "participants", "process_nodes",
        "risk_items", "risk_matrix", "risk_level", "hitl_level",
        "audit_requirements",
    ]
    substantive = 0
    for field in key_fields:
        val = summary.get(field)
        if _is_substantive_field(field, val):
            substantive += 1
    completeness = substantive / len(key_fields) if key_fields else 0.0

    # Participant split
    participants = summary.get("participants", [])
    participant_roles = [
        str(item.get("role", ""))
        for item in participants
        if isinstance(item, dict) and item.get("role")
    ]
    if participant_roles:
        unsplit_roles = [
            role for role in participant_roles
            if any(separator in role for separator in ("、", "，", ",", "；", ";"))
        ]
        participant_split = 0.5 if unsplit_roles else 1.0
    else:
        participant_split = 0.0

    # Process node completeness + responsibility mapping
    process_nodes = summary.get("process_nodes", [])
    if process_nodes:
        node_scores = []
        for node in process_nodes:
            if not isinstance(node, dict):
                continue
            checks = [
                bool(node.get("name")),
                bool(node.get("owner_role")),
                bool(node.get("input") or node.get("output")),
                node.get("human_review_required") is not None,
                bool(node.get("evidence_refs")),
            ]
            node_scores.append(sum(1 for check in checks if check) / len(checks))
        process_node_completeness = sum(node_scores) / len(node_scores) if node_scores else 0.0
        responsibility_mapping = sum(
            1 for node in process_nodes
            if isinstance(node, dict) and node.get("owner_role")
        ) / len(process_nodes)
    else:
        process_node_completeness = 0.0
        responsibility_mapping = 0.0

    # Audit node mapping
    review_nodes = [
        node for node in process_nodes
        if isinstance(node, dict)
        and (
            node.get("human_review_required") is True
            or any(keyword in str(node.get("name", "")) for keyword in ("复核", "确认", "审批", "合规"))
        )
    ]
    if review_nodes:
        audit_node_mapping = sum(1 for node in review_nodes if node.get("audit_fields")) / len(review_nodes)
    else:
        audit_node_mapping = 1.0 if rl == "L1" else 0.0

    # Responsibility chain
    responsibilities = summary.get("responsibilities", [])
    process_node_ids = {
        str(node.get("node_id", ""))
        for node in process_nodes
        if isinstance(node, dict) and node.get("node_id")
    }
    if responsibilities and process_node_ids:
        responsibility_scores = []
        covered_node_ids = set()
        for item in responsibilities:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("node_id", ""))
            if node_id in process_node_ids:
                covered_node_ids.add(node_id)
            checks = [
                bool(item.get("role")),
                node_id in process_node_ids,
                bool(item.get("responsibility")),
                bool(item.get("evidence_refs")),
            ]
            responsibility_scores.append(sum(1 for check in checks if check) / len(checks))
        detail_score = sum(responsibility_scores) / len(responsibility_scores) if responsibility_scores else 0.0
        coverage_score = len(covered_node_ids) / len(process_node_ids)
        responsibility_chain = (detail_score + coverage_score) / 2
    elif process_node_ids:
        responsibility_chain = 0.0
    else:
        responsibility_chain = 1.0 if rl == "L1" else 0.0

    # Flow diagram
    flow_diagram = summary.get("process_flow_diagram", {})
    edges = summary.get("edges", [])
    main_path = summary.get("main_path", [])
    flow_diagram_score = 1.0 if (
        isinstance(flow_diagram, dict)
        and flow_diagram.get("format") == "edges"
        and isinstance(edges, list) and edges
        and isinstance(main_path, list) and len(main_path) >= 2
        and _main_path_valid(edges, main_path, process_nodes)
    ) else 0.0

    # Supplementary verification scenarios — 步骤1 要求 2-3 个贷后相近补充场景
    # Cross-system link coverage — F2 要求流程节点绑定跨系统链路
    links = summary.get("cross_system_links", [])
    process_node_ids = {
        str(node.get("node_id", ""))
        for node in process_nodes
        if isinstance(node, dict) and node.get("node_id")
    }
    if process_node_ids:
        linked_ids = {
            str(link.get("node_id", ""))
            for link in links
            if isinstance(link, dict) and link.get("node_id")
        }
        cross_system_link_score = len(linked_ids) / len(process_node_ids)
    else:
        cross_system_link_score = 0.0

    return {
        "completeness_score": completeness,
        "participant_split_score": participant_split,
        "process_node_completeness_score": process_node_completeness,
        "responsibility_mapping_score": responsibility_mapping,
        "responsibility_chain_score": responsibility_chain,
        "audit_node_mapping_score": audit_node_mapping,
        "flow_diagram_score": flow_diagram_score,
        "flow_diagram_generated": flow_diagram_score == 1.0,
        "cross_system_link_score": cross_system_link_score,
    }


def compute_risk_quality(summary: dict) -> dict:
    """Phase B — 风险定级质量维度（6 维，返回原始未取整值）。

    维度：evidence_coverage_score、risk_consistency_score、
    hitl_alignment_score、risk_item_node_binding_score、
    hitl_rule_node_binding_score、risk_node_binding_score。
    不修改输入。
    """
    rl = summary.get("risk_level")
    risk_items = summary.get("risk_items", [])

    # Evidence coverage: fraction of risk items with evidence refs
    if risk_items:
        items_with_refs = sum(
            1 for item in risk_items
            if isinstance(item, dict) and item.get("evidence_refs")
        )
        evidence_coverage = items_with_refs / len(risk_items)
    else:
        evidence_coverage = 0.0

    # Risk consistency: 1.0 if risk_level is valid and risk_items agree
    risk_consistency = 0.0
    if rl in RISK_LEVELS:
        risk_consistency = 1.0
        # Check if risk_items contain at least one item matching the overall level
        if risk_items:
            has_matching = any(
                isinstance(item, dict) and item.get("risk_level") == rl
                for item in risk_items
            )
            if not has_matching:
                risk_consistency = 0.7  # Level declared but no matching risk item
    elif rl is not None:
        risk_consistency = 0.3  # Invalid enum

    # HITL alignment: 1.0 if hitl_level is valid and consistent with risk
    hl = summary.get("hitl_level")
    hitl_alignment = 0.0
    if hl in HITL_LEVELS:
        hitl_alignment = 1.0
        if rl == "L3" and hl not in {"strict", "mandatory"}:
            hitl_alignment = 0.3  # Mismatch
        elif rl == "L2" and hl == "none":
            hitl_alignment = 0.5  # Weak
    elif hl is not None:
        hitl_alignment = 0.2  # Invalid enum

    # Risk item node binding
    if risk_items:
        bound_risk_items = sum(
            1 for item in risk_items
            if isinstance(item, dict) and item.get("node_id")
        )
        risk_item_binding_score = bound_risk_items / len(risk_items)
    else:
        risk_item_binding_score = 1.0 if rl == "L1" else 0.0

    # HITL rule node binding
    hitl_rules = summary.get("hitl_rules", [])
    if hitl_rules:
        bound_hitl_rules = sum(
            1 for rule in hitl_rules
            if isinstance(rule, dict) and rule.get("node_id")
        )
        hitl_rule_binding_score = bound_hitl_rules / len(hitl_rules)
    else:
        hitl_rule_binding_score = 1.0 if rl == "L1" else 0.0

    risk_node_binding = (risk_item_binding_score + hitl_rule_binding_score) / 2

    # Error amplification path coverage: >=3 substantive paths = 1.0 (M1 gate)
    error_paths = summary.get("error_amplification_paths", [])
    substantive_paths = [
        p for p in error_paths
        if isinstance(p, dict)
        and (
            str(p.get("description", "")).strip()
            or (
                isinstance(p.get("amplification_mechanisms"), list)
                and any(str(m).strip() for m in p["amplification_mechanisms"])
            )
        )
    ]
    error_path_coverage = min(1.0, len(substantive_paths) / 3) if rl in {"L2", "L3"} else (
        1.0 if substantive_paths else 0.0
    )

    return {
        "evidence_coverage_score": evidence_coverage,
        "risk_consistency_score": risk_consistency,
        "hitl_alignment_score": hitl_alignment,
        "risk_item_node_binding_score": risk_item_binding_score,
        "hitl_rule_node_binding_score": hitl_rule_binding_score,
        "risk_node_binding_score": risk_node_binding,
        "error_path_coverage_score": error_path_coverage,
    }


def compute_stage1_quality(summary: dict) -> dict:
    """Compute quality scores for a Stage 1 ``scenario_summary``.

    Returns a dict with 16 keys (14 float scores in [0, 1] + 1 bool +
    1 composite). Thin wrapper over ``compute_scenario_quality`` (Phase A,
    8 dims) and ``compute_risk_quality`` (Phase B, 6 dims), then computes
    2 composites (``audit_readiness_score``, ``deliverable_readiness_score``).

    Does **not** mutate the input.
    """
    phase_a = compute_scenario_quality(summary)
    phase_b = compute_risk_quality(summary)

    # Audit readiness: weighted combination (completeness from Phase A,
    # evidence_coverage / risk_consistency / hitl_alignment from Phase B)
    audit_readiness = (
        phase_a["completeness_score"] * _QUALITY_WEIGHTS["completeness"]
        + phase_b["evidence_coverage_score"] * _QUALITY_WEIGHTS["evidence_coverage"]
        + phase_b["risk_consistency_score"] * _QUALITY_WEIGHTS["risk_consistency"]
        + phase_b["hitl_alignment_score"] * _QUALITY_WEIGHTS["hitl_alignment"]
    )

    # Deliverable readiness: advisory dimensions (6 from Phase A +
    # risk_node_binding from Phase B)
    deliverable_readiness = (
        phase_a["participant_split_score"]
        + phase_a["process_node_completeness_score"]
        + phase_a["responsibility_mapping_score"]
        + phase_a["responsibility_chain_score"]
        + phase_a["audit_node_mapping_score"]
        + phase_a["flow_diagram_score"]
        + phase_b["risk_node_binding_score"]
    ) / 7

    # Stage-1 deliverable readiness for the F2/F3 product fields:
    # cross-system links (F2) + error amplification paths (F3). These are
    # advisory coverage signals, not gating. (F1 主案例/补充场景/材料清单
    # 是课题级产物，不在单项目 scenario_summary 内，不计入此处。)
    extended_readiness = (
        phase_a["cross_system_link_score"]
        + phase_b["error_path_coverage_score"]
    ) / 2

    return {
        "completeness_score": round(phase_a["completeness_score"], 4),
        "evidence_coverage_score": round(phase_b["evidence_coverage_score"], 4),
        "risk_consistency_score": round(phase_b["risk_consistency_score"], 4),
        "hitl_alignment_score": round(phase_b["hitl_alignment_score"], 4),
        "audit_readiness_score": round(audit_readiness, 4),
        "participant_split_score": round(phase_a["participant_split_score"], 4),
        "process_node_completeness_score": round(phase_a["process_node_completeness_score"], 4),
        "responsibility_mapping_score": round(phase_a["responsibility_mapping_score"], 4),
        "responsibility_chain_score": round(phase_a["responsibility_chain_score"], 4),
        "audit_node_mapping_score": round(phase_a["audit_node_mapping_score"], 4),
        "flow_diagram_score": round(phase_a["flow_diagram_score"], 4),
        "flow_diagram_generated": phase_a["flow_diagram_generated"],
        "risk_node_binding_score": round(phase_b["risk_node_binding_score"], 4),
        "risk_item_node_binding_score": round(phase_b["risk_item_node_binding_score"], 4),
        "hitl_rule_node_binding_score": round(phase_b["hitl_rule_node_binding_score"], 4),
        "deliverable_readiness_score": round(deliverable_readiness, 4),
        "cross_system_link_score": round(phase_a["cross_system_link_score"], 4),
        "error_path_coverage_score": round(phase_b["error_path_coverage_score"], 4),
        "extended_deliverable_readiness_score": round(extended_readiness, 4),
    }
