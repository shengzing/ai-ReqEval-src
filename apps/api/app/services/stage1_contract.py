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

# ── §3.2.2 PIPL §24 替代渠道（mandatory 级场景必填） ─────────────────────
ALTERNATIVE_CHANNELS: set[str] = {
    "manual_fallback",       # 人工流程降级
    "full_manual",           # 纯人工复核
    "manual_plus_rules",     # 人工 + 规则引擎
}
_ALTCHANNEL_ALIASES: dict[str, str] = {
    "人工流程降级": "manual_fallback",
    "人工降级": "manual_fallback",
    "纯人工复核": "full_manual",
    "全量人工": "full_manual",
    "人工+规则引擎": "manual_plus_rules",
    "人工加规则": "manual_plus_rules",
    "manual fallback": "manual_fallback",
    "full manual": "full_manual",
    "manual + rules": "manual_plus_rules",
}

# ── §3.2.3 NFRA §16 / 第十六条 批准主体（L3 必填） ──────────────────────
APPROVAL_SUBJECTS: set[str] = {
    "risk_committee",        # 风险管理委员会批准
    "compliance_committee",  # 合规委员会
    "technology_committee",  # 科技委员会
}
_APPROVAL_ALIASES: dict[str, str] = {
    "风险管理委员会": "risk_committee",
    "风管委": "risk_committee",
    "合规委员会": "compliance_committee",
    "合规委": "compliance_committee",
    "科技委员会": "technology_committee",
    "科技委": "technology_committee",
}


# ── §3.2 步骤1 STS 六变量社会子系统诊断（§3.2.1 / §1.3.1 STS 理论） ────
# 论文 §3.2.1 六变量（Trist&Bamforth 1951, Emery 1959）：自律性 / 责任 /
# 任务整体性 / 多样性 / 社会支持 / 边界跨越。L3 场景须在自律性、责任、
# 社会支持三个维度经业务/风险/合规角色访谈确认无重大缺陷，方可继续步骤2。
STS_6_VARIABLES: tuple[str, ...] = (
    "autonomy",           # 自律性
    "responsibility",     # 责任
    "task_integrity",     # 任务整体性
    "diversity",          # 多样性
    "social_support",     # 社会支持
    "boundary_spanning",  # 边界跨越
)
_STS_VAR_ALIASES: dict[str, str] = {
    "自律性": "autonomy",
    "责任": "responsibility",
    "任务整体性": "task_integrity",
    "多样性": "diversity",
    "社会支持": "social_support",
    "边界跨越": "boundary_spanning",
}
STS_DIAGNOSIS_STATUSES: set[str] = {"aligned", "tension", "misaligned", "unmapped"}
"""单变量的诊断状态：aligned 对齐 / tension 需协调 / misaligned 失配 / unmapped 未识别。"""


# ── §3.2 步骤2 KOITL 组织在环循环归属（step2 四字段之一） ────────────
# 论文 §3.2 步骤2 KOITL 组织层循环映射表：四类组织循环。
# UA-Tasks = AI 使用循环（谁复核/审批频率）；CA-Tasks = AI 定制循环（谁维护
# 规则）；O-Tasks = 原任务循环（业务负责人签字链）；C-Tasks = 上下文变化
# 循环（监管/业务变化触发再评估）。
ORG_LOOP_KINDS: set[str] = {
    "UA-Tasks",  # AI 使用循环：谁复核、审批频率
    "CA-Tasks",  # AI 定制循环：谁维护规则
    "O-Tasks",   # 原任务循环：业务负责人签字链
    "C-Tasks",   # 上下文变化循环：监管/业务变化触发再评估
}
_ORG_LOOP_KIND_ALIASES: dict[str, str] = {
    "AI使用循环": "UA-Tasks",
    "AI 使用循环": "UA-Tasks",
    "AI定制循环": "CA-Tasks",
    "AI 定制循环": "CA-Tasks",
    "原任务循环": "O-Tasks",
    "上下文变化循环": "C-Tasks",
}
MIN_SUBSTANTIVE_ORG_LOOPS = 1  # L2/L3 至少 1 个明确循环


# ── §3.2.4 最小审计留痕 8 字段（贷后场景；AML +1 = 9 字段） ────────────
# NFRA 第二十一条（显著标识+日志≥业务存续期）+ 第二十二条（推理路径/阈值
# 触发记录保留）+ 金规〔2024〕24号第五十条（可验证可审核可追溯）。
AUDIT_FIELD_IDS: tuple[str, ...] = (
    "input_material_version",   # (1) 输入材料版本
    "raw_analysis_output",      # (2) AI 原始输出
    "reviewer_opinion",         # (3) 复核人及复核意见
    "timestamp",                # (4) 时间戳
    "inference_path",           # (5) 推理路径（NFRA §22）
    "threshold_trigger_log",    # (6) 阈值触发记录（NFRA §22）
    "ai_disclosure",            # (7) AI 生成内容显著标识（NFRA §21）
    "log_retention",            # (8) 日志保存期限（NFRA §21）
)
AML_EXTRA_AUDIT_FIELD_IDS: tuple[str, ...] = (
    "regulatory_reporting_log", # (9) AML 监管报送流水
)
AIGC_DISCLOSURE_VALUES: set[str] = {
    "explicit_watermark",   # 显式水印（贷后风控必须）
    "implicit_metadata",    # 隐式元数据
    "unlabeled",            # 不标识
}
LOG_RETENTION_VALUES: set[str] = {
    "business_lifetime",    # ≥业务存续期（贷后风控默认）
    "5_years",
    "10_years",
}
# 贷后风控：AIGC 标识必须 = explicit_watermark；日志保存 ≥ business_lifetime
LOAN_RISK_REQUIRED_AIGC = "explicit_watermark"
LOAN_RISK_REQUIRED_LOG_RETENTION = "business_lifetime"


def normalize_alternative_channel(value: object) -> str | None:
    """Normalize PIPL §24 alternative channel to contract enum, or None if absent/empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in ALTERNATIVE_CHANNELS:
        return text
    if text in _ALTCHANNEL_ALIASES:
        return _ALTCHANNEL_ALIASES[text]
    raise ValueError(f"Cannot normalize alternative_channel: {value!r}")


def normalize_approval_subject(value: object) -> str | None:
    """Normalize NFRA §16 approval subject to contract enum, or None if absent/empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in APPROVAL_SUBJECTS:
        return text
    if text in _APPROVAL_ALIASES:
        return _APPROVAL_ALIASES[text]
    raise ValueError(f"Cannot normalize approval_subject: {value!r}")


def normalize_sts_variable(value: object) -> str | None:
    """Normalize a STS six-variable key to contract enum, or None if absent/empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in STS_6_VARIABLES:
        return text
    if text in _STS_VAR_ALIASES:
        return _STS_VAR_ALIASES[text]
    raise ValueError(f"Cannot normalize STS variable: {value!r}")


def normalize_org_loop_kind(value: object) -> str | None:
    """Normalize a KOITL org-loop kind to contract enum, or None if absent/empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in ORG_LOOP_KINDS:
        return text
    if text in _ORG_LOOP_KIND_ALIASES:
        return _ORG_LOOP_KIND_ALIASES[text]
    raise ValueError(f"Cannot normalize org_loop kind: {value!r}")

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

    # 19. PIPL §24 alternative channel — mandatory HITL 场景须配置不依赖算法的替代渠道
    alt_channel = summary.get("alternative_channel")
    if hl == "mandatory":
        if not alt_channel:
            issues.append({
                "issue_type": "missing_field",
                "field": "alternative_channel",
                "severity": "high",
                "message": "mandatory HITL 场景须配置替代渠道（PIPL §24），缺失则阶段一不予锁定",
                "suggested_action": "Set alternative_channel 到 manual_fallback / full_manual / manual_plus_rules",
            })
        elif alt_channel not in ALTERNATIVE_CHANNELS:
            issues.append({
                "issue_type": "invalid_enum",
                "field": "alternative_channel",
                "severity": "high",
                "message": f"alternative_channel must be one of {sorted(ALTERNATIVE_CHANNELS)}, got {alt_channel!r}",
                "suggested_action": "使用 normalize_alternative_channel 归一后填入",
            })

    # 20. NFRA §16 approval subject — 枚举收窄为风管委/合规委/科技委，
    #     L3 场景必须 = risk_committee（风管委），缺失或非风管委则锁定门禁不通过。
    approval_subject = summary.get("approval_subject")
    if rl == "L3":
        if not approval_subject:
            issues.append({
                "issue_type": "missing_field",
                "field": "approval_subject",
                "severity": "high",
                "message": "L3 风险场景须配置批准主体（NFRA 第十六条），缺失则阶段一不予锁定",
                "suggested_action": "Set approval_subject 到 risk_committee / compliance_committee / technology_committee",
            })
        elif approval_subject not in APPROVAL_SUBJECTS:
            issues.append({
                "issue_type": "invalid_enum",
                "field": "approval_subject",
                "severity": "high",
                "message": f"approval_subject must be one of {sorted(APPROVAL_SUBJECTS)}, got {approval_subject!r}",
                "suggested_action": "使用 normalize_approval_subject 归一后填入",
            })
        elif approval_subject != "risk_committee":
            issues.append({
                "issue_type": "invalid_value",
                "field": "approval_subject",
                "severity": "high",
                "message": f"L3 场景批准主体必须为 risk_committee（风管委），当前 {approval_subject!r}",
                "suggested_action": "NFRA 第十六条：风险管理类高风险应用须经本机构风险管理委员会批准",
            })

    # 21. §3.2 步骤1 STS 六变量社会子系统诊断 — 阶段一建议补全，便于回溯
    #     STS 社会侧诊断与 ISO 技术侧分级互为依据。不强制（缺失只 warning），
    #     但 L3 场景强烈建议给出全部 6 变量以备 §5.3 回溯校准。
    sts = summary.get("sts_diagnosis")
    if sts is not None:
        if not isinstance(sts, dict):
            issues.append({
                "issue_type": "invalid_enum",
                "field": "sts_diagnosis",
                "severity": "medium",
                "message": "sts_diagnosis 必须为 dict（键为 STS 六变量 id）",
                "suggested_action": "提供 {autonomy: aligned/tension/..., responsibility: ..., task_integrity: ..., diversity: ..., social_support: ..., boundary_spanning: ...}",
            })
        else:
            for var in sts.keys():
                if var not in STS_6_VARIABLES:
                    issues.append({
                        "issue_type": "invalid_enum",
                        "field": f"sts_diagnosis.{var}",
                        "severity": "medium",
                        "message": f"sts_diagnosis key {var!r} 不是 STS 六变量之一",
                        "suggested_action": f"使用 STS_6_VARIABLES = {list(STS_6_VARIABLES)}",
                    })
                elif sts[var] not in STS_DIAGNOSIS_STATUSES:
                    issues.append({
                        "issue_type": "invalid_enum",
                        "field": f"sts_diagnosis.{var}",
                        "severity": "medium",
                        "message": f"sts_diagnosis[{var}] = {sts[var]!r} 不在 {sorted(STS_DIAGNOSIS_STATUSES)}",
                        "suggested_action": "使用 aligned / tension / misaligned / unmapped",
                    })
            if rl == "L3":
                covered = sum(1 for v in STS_6_VARIABLES if v in sts)
                if covered < 3:
                    issues.append({
                        "issue_type": "missing_field",
                        "field": "sts_diagnosis",
                        "severity": "medium",
                        "message": f"L3 场景建议补全 STS 六变量诊断（当前 {covered} / 6）",
                        "suggested_action": "为至少 3 个 STS 变量给出 aligned/tension/misaligned 判定",
                    })

    # 22. §3.2 步骤2 KOITL 组织循环归属（org_loops）— L2/L3 须有组织在环记录
    # P2 数据契约：loop_type / responsible_role / frequency / mandatory_flag（论文口径）；
    # 兼容旧字段名 kind / role（历史数据）。L3 场景四类循环（UA/CA/O/C）须全部在场。
    org_loops = summary.get("org_loops")
    if rl in {"L2", "L3"}:
        if not isinstance(org_loops, list) or len(org_loops) < MIN_SUBSTANTIVE_ORG_LOOPS:
            issues.append({
                "issue_type": "missing_field",
                "field": "org_loops",
                "severity": "medium",
                "message": f"{rl} 风险建议记录至少 {MIN_SUBSTANTIVE_ORG_LOOPS} 条组织循环归属（UA/CA/O/C-Tasks）",
                "suggested_action": "添加 org_loops 列表，每项含 loop_id / loop_type / responsible_role / frequency / mandatory_flag / evidence_refs",
            })
        else:
            seen_loop_types: set[str] = set()
            for idx, loop in enumerate(org_loops):
                if not isinstance(loop, dict):
                    issues.append({
                        "issue_type": "invalid_enum",
                        "field": f"org_loops[{idx}]",
                        "severity": "medium",
                        "message": "org_loops 项必须为 dict",
                        "suggested_action": "提供 {loop_id, loop_type, responsible_role, frequency, mandatory_flag, evidence_refs}",
                    })
                    continue
                # P2: loop_type is the thesis field; kind is the legacy alias.
                loop_type = loop.get("loop_type") or loop.get("kind")
                if loop_type is not None and loop_type not in ORG_LOOP_KINDS:
                    issues.append({
                        "issue_type": "invalid_enum",
                        "field": f"org_loops[{idx}].loop_type",
                        "severity": "medium",
                        "message": f"org_loops[{idx}].loop_type = {loop_type!r} 不在 {sorted(ORG_LOOP_KINDS)}",
                        "suggested_action": "使用 UA-Tasks / CA-Tasks / O-Tasks / C-Tasks",
                    })
                elif loop_type is not None:
                    seen_loop_types.add(loop_type)
                # P2: responsible_role is the thesis field; role is legacy.
                responsible_role = loop.get("responsible_role") or loop.get("role")
                if not responsible_role:
                    issues.append({
                        "issue_type": "missing_field",
                        "field": f"org_loops[{idx}].responsible_role",
                        "severity": "medium",
                        "message": f"org_loops[{idx}] 缺少 responsible_role（旧字段名 role 亦可）",
                        "suggested_action": "填写负责该循环的角色（如 风险经理 / 业务负责人）",
                    })
            # 论文 §3.2 步骤2 判据：L3 场景任一组织循环缺位则 locked=False
            if rl == "L3":
                missing_types = ORG_LOOP_KINDS - seen_loop_types
                if missing_types:
                    issues.append({
                        "issue_type": "missing_field",
                        "field": "org_loops",
                        "severity": "high",
                        "message": f"L3 场景四类组织循环缺位：{sorted(missing_types)}",
                        "suggested_action": "L3 须 UA-Tasks（风险+合规双签）+ CA-Tasks（规则维护）+ O-Tasks（业务负责人 mandatory 签字）+ C-Tasks（季度再评估）全部在场",
                    })
                # 论文 §3.2 步骤2：O-Tasks 必含业务负责人 mandatory 签字
                o_tasks = [l for l in org_loops if isinstance(l, dict) and (l.get("loop_type") or l.get("kind")) == "O-Tasks"]
                if o_tasks and not any(l.get("mandatory_flag") is True for l in o_tasks):
                    issues.append({
                        "issue_type": "invalid_value",
                        "field": "org_loops[O-Tasks].mandatory_flag",
                        "severity": "high",
                        "message": "L3 场景 O-Tasks 必含业务负责人 mandatory 签字（mandatory_flag=True）",
                        "suggested_action": "将 O-Tasks 循环的 mandatory_flag 设为 True",
                    })

    # 23. §3.2.4 最小审计留痕 — P2 起支持结构化对象（{field_id, label,
    #     value, evidence_refs}）；兼容旧字符串列表（不做结构校验）。
    #     L2/L3 场景建议至少覆盖基础 4 字段；枚举字段值校验。
    audit_reqs = summary.get("audit_requirements")
    if isinstance(audit_reqs, list) and audit_reqs and all(isinstance(r, dict) for r in audit_reqs):
        seen_field_ids: set[str] = set()
        for idx, req in enumerate(audit_reqs):
            fid = req.get("field_id")
            if fid not in AUDIT_FIELD_IDS and fid not in AML_EXTRA_AUDIT_FIELD_IDS:
                issues.append({
                    "issue_type": "invalid_enum",
                    "field": f"audit_requirements[{idx}].field_id",
                    "severity": "medium",
                    "message": f"audit field_id {fid!r} 不在 8+1 字段 schema 内",
                    "suggested_action": f"使用 {list(AUDIT_FIELD_IDS)} 或 AML 扩展 {list(AML_EXTRA_AUDIT_FIELD_IDS)}",
                })
            else:
                seen_field_ids.add(fid)
            # 枚举字段值校验
            if fid == "ai_disclosure":
                val = req.get("value")
                if val is not None and val not in AIGC_DISCLOSURE_VALUES:
                    issues.append({
                        "issue_type": "invalid_enum",
                        "field": f"audit_requirements[{idx}].value",
                        "severity": "high",
                        "message": f"ai_disclosure = {val!r} 不在 {sorted(AIGC_DISCLOSURE_VALUES)}",
                        "suggested_action": "贷后风控必须 explicit_watermark（NFRA 第二十一条）",
                    })
            if fid == "log_retention":
                val = req.get("value")
                if val is not None and val not in LOG_RETENTION_VALUES:
                    issues.append({
                        "issue_type": "invalid_enum",
                        "field": f"audit_requirements[{idx}].value",
                        "severity": "high",
                        "message": f"log_retention = {val!r} 不在 {sorted(LOG_RETENTION_VALUES)}",
                        "suggested_action": "贷后风控默认 business_lifetime（≥业务存续期，NFRA 第二十一条）",
                    })
        # L2/L3 覆盖度：至少覆盖基础 4 字段
        if rl in {"L2", "L3"}:
            base_covered = sum(1 for f in AUDIT_FIELD_IDS[:4] if f in seen_field_ids)
            if base_covered < 4:
                issues.append({
                    "issue_type": "missing_field",
                    "field": "audit_requirements",
                    "severity": "medium",
                    "message": f"{rl} 场景建议覆盖基础 4 审计字段（当前 {base_covered} / 4）",
                    "suggested_action": "补全 input_material_version / raw_analysis_output / reviewer_opinion / timestamp",
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
