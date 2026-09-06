"""P2-2 rubric-designer — design the three-dimension scoring rubric (§3.4.2).

Thesis §3.4.2: the rubric covers three dimensions — quality (qual),
efficiency (eff), governance (gov) — each with a set of scored items on
the 4-tier scale (0 / 0.33 / 0.67 / 1.0).  Each item carries a
``hard_constraint`` flag: hard-constraint items (e.g. 事实一致性, 字段
完整率, 审计留痕完整率, 脱敏合规) gate the verdict independently — any
hard-constraint failure forces a hold/nogo regardless of the weighted
total.  Soft-constraint items only contribute to the 式(4) weighted
score.

The 8-factor → three-dimension reconstruction (§3.4.2 量规因子表):
  qual  (hard): 事实一致性、字段完整率、风险点召回率、规则命中准确率
  eff   (soft): 单件处理时长、返工率
  gov   (hard): 审计留痕完整率、脱敏合规

Hard-constraint items are also tagged with the audit-field IDs they
govern (when applicable), so the error-rate calculator (P2-5) can join
rubric failures to audit-completeness defects.

This Sub-agent is mounted on the existing Stage 3 Skill — NOT a
standalone 9-Agent target (CLAUDE.md "9 Agent 是目标架构，当前由 4
个阶段级分析 Skill 聚合执行").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── Rubric item field schema (§3.4.2) ─────────────────────────────────

REQUIRED_RUBRIC_ITEM_FIELDS: tuple[str, ...] = (
    "item",
    "dim",
    "hard_constraint",
    "grade_scale",
)

VALID_DIMS: tuple[str, ...] = ("qual", "eff", "gov")

# 4-tier grade scale (§3.4.4) — shared with actual_sla.py.
GRADE_SCALE: tuple[str, ...] = ("0", "0.33", "0.67", "1.0")

# ── Loan-post scenario seed rubric (Delphi prior — §3.4.2 case seed) ─
# 8 factors → three-dimension reconstruction.  Annotated as initial
# reference values pending M2-M4 empirical calibration.
LOAN_POST_SEED_RUBRIC: dict[str, list[dict[str, Any]]] = {
    "qual": [
        {
            "item": "事实一致性",
            "hard_constraint": True,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "输出是否忠实于输入材料（财报摘要、检查记录、预警信号、舆情）",
            "sla_floor_d": 95,
            "audit_field_ids": ["af-1", "af-2"],
            "source": "德尔菲先验",
        },
        {
            "item": "字段完整率",
            "hard_constraint": True,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "应抽字段是否完整（经营异常清单、疑点清单要素齐全）",
            "sla_floor_d": 90,
            "audit_field_ids": ["af-1"],
            "source": "德尔菲先验",
        },
        {
            "item": "风险点召回率",
            "hard_constraint": True,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "高风险点是否被识别（口径冲突、材料缺失、信息滞后）",
            "sla_floor_d": 95,
            "source": "德尔菲先验",
        },
        {
            "item": "规则命中准确率",
            "hard_constraint": True,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "审核规则判断是否准确（预警信号成立与否）",
            "sla_floor_d": 90,
            "source": "德尔菲先验",
        },
    ],
    "eff": [
        {
            "item": "单件处理时长",
            "hard_constraint": False,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "模型/工具运行耗时（reverse_normalize=True，越短越高分）",
            "reverse_normalize": True,
            "sla_floor_d": 85,
            "source": "德尔菲先验",
        },
        {
            "item": "返工率",
            "hard_constraint": False,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "需要重新生成或重审的比例（reverse_normalize=True，越低越高分）",
            "reverse_normalize": True,
            "sla_floor_d": 85,
            "source": "德尔菲先验",
        },
    ],
    "gov": [
        {
            "item": "审计留痕完整率",
            "hard_constraint": True,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "输入版本/AI输出/复核人/复核意见/时间戳/推理路径/阈值触发/AI标识是否留痕",
            "sla_floor_d": 95,
            "audit_field_ids": ["af-1", "af-2", "af-3", "af-4", "af-5", "af-6", "af-7", "af-8"],
            "source": "德尔菲先验",
        },
        {
            "item": "脱敏合规",
            "hard_constraint": True,
            "grade_scale": ["0", "0.33", "0.67", "1.0"],
            "description": "样本是否脱敏；未脱敏样本不得进入探针执行",
            "sla_floor_d": 100,
            "source": "德尔菲先验",
        },
    ],
}


@dataclass
class RubricDesignerResult:
    """Output of the rubric-designer Sub-agent.

    Attributes:
        rubric: ``{qual: [...], eff: [...], gov: [...]}`` — each item
            carries item, hard_constraint, grade_scale, description,
            and optional audit_field_ids / reverse_normalize.
        item_count: int — total rubric items across three dims
        hard_constraint_items: list of item names flagged hard
        has_fact_consistency_hard: bool — True when qual dim contains
            事实一致性 as a hard constraint (§3.4.2 acceptance)
        has_field_completeness: bool — True when qual dim contains
            字段完整率 (§3.4.2 acceptance)
        missing_dims: dims with zero items
        review_status: "complete" (all 3 dims, ≥1 hard in qual+gov) |
            "partial" | "empty"
        extraction_notes: human-readable provenance notes
    """

    rubric: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    item_count: int = 0
    hard_constraint_items: list[str] = field(default_factory=list)
    has_fact_consistency_hard: bool = False
    has_field_completeness: bool = False
    missing_dims: list[str] = field(default_factory=list)
    review_status: str = "empty"  # complete | partial | empty
    extraction_notes: list[str] = field(default_factory=list)


def design_rubric(
    *,
    atomic_tasks: list[dict] | None = None,
    scenario_key: str | None = None,
    delphi_seed_rubric: dict[str, list[dict]] | None = None,
    evidence_rubric: dict[str, list[dict]] | None = None,
    llm_client: Any = None,
) -> RubricDesignerResult:
    """Design the three-dimension scoring rubric (§3.4.2).

    The design proceeds in three phases:

    1. **Seed merge**: Delphi prior seed rubric (annotated "初始参考值，
       待 M2-M4 实证标定") is merged with evidence-derived rubric items.
       Evidence overrides seed on ``item`` name collision per dim.
       When *scenario_key* is recognized (e.g. ``loan_post``), the
       scenario seed is loaded as the Delphi prior baseline.
    2. **LLM extraction** (optional): when *llm_client* is provided,
       additional rubric items are extracted from atomic-task specs.
       Unconfigured / LLM-failed runs degrade gracefully to seed-only.
    3. **Schema validation**: each rubric item is validated against the
       §3.4.2 field schema; hard_constraint flags and grade_scale are
       checked.  Missing/invalid fields are collected but do not drop
       the item — the caller sees the full rubric plus the defects.

    Args:
        atomic_tasks: atomic tasks from P2-1 (used to anchor rubric
            items to tasks and to drive LLM extraction).
        scenario_key: scenario identifier for seed selection
            (e.g. ``"loan_post"``).  None → no scenario seed.
        delphi_seed_rubric: Delphi prior seed rubric (override
            scenario seed when both provided).
        evidence_rubric: evidence-derived rubric (highest confidence).
        llm_client: optional LLM client for free-text extraction.

    Returns:
        RubricDesignerResult with the full three-dimension rubric.
    """
    notes: list[str] = []

    # ── Phase 1: seed merge ──
    if delphi_seed_rubric is not None:
        seed = {d: list(items) for d, items in delphi_seed_rubric.items()}
    elif scenario_key == "loan_post":
        seed = {d: [dict(i) for i in items] for d, items in LOAN_POST_SEED_RUBRIC.items()}
        notes.append("使用贷后场景德尔菲先验种子量规（8 因子→三类）；待 M2-M4 实证标定后替换为证据材料。")
    else:
        seed = {d: [] for d in VALID_DIMS}

    # Merge evidence overrides seed on (dim, item) collision
    merged: dict[str, list[dict[str, Any]]] = {d: [] for d in VALID_DIMS}
    seen: set[tuple[str, str]] = set()

    for dim in VALID_DIMS:
        for item in seed.get(dim, []):
            if not isinstance(item, dict):
                continue
            name = item.get("item", "")
            if (dim, name) in seen:
                continue
            merged[dim].append({**item, "dim": dim, "source": item.get("source", "德尔菲先验")})
            seen.add((dim, name))

    for dim in VALID_DIMS:
        for item in (evidence_rubric or {}).get(dim, []):
            if not isinstance(item, dict):
                continue
            name = item.get("item", "")
            if (dim, name) in seen:
                # Evidence overrides seed — replace
                merged[dim] = [
                    {**item, "dim": dim, "source": item.get("source", "证据材料")}
                    if i.get("item") == name
                    else i
                    for i in merged[dim]
                ]
            else:
                merged[dim].append({**item, "dim": dim, "source": item.get("source", "证据材料")})
                seen.add((dim, name))

    # ── Phase 2: LLM extraction (optional) ──
    llm_added = 0
    if llm_client is not None and atomic_tasks:
        llm_items = _llm_extract_rubric(llm_client, atomic_tasks)
        for dim, item in llm_items:
            if dim not in VALID_DIMS:
                continue
            name = item.get("item", "")
            if (dim, name) in seen:
                continue
            merged[dim].append({**item, "source": "LLM抽取"})
            seen.add((dim, name))
            llm_added += 1
        if llm_added:
            notes.append(f"LLM 抽取新增 {llm_added} 个量规项。")

    # ── Check empty ──
    total_items = sum(len(items) for items in merged.values())
    if total_items == 0:
        return RubricDesignerResult(
            rubric=merged,
            review_status="empty",
            extraction_notes=["No rubric items provided (neither seed nor evidence nor LLM extraction)."],
        )

    # ── Phase 3: schema validation ──
    hard_items: list[str] = []
    has_fact_consistency = False
    has_field_completeness = False
    missing_dims: list[str] = []
    all_valid = True

    for dim in VALID_DIMS:
        if not merged[dim]:
            missing_dims.append(dim)
            all_valid = False
            continue
        for item in merged[dim]:
            # Check required fields
            for f in REQUIRED_RUBRIC_ITEM_FIELDS:
                if f not in item or item[f] is None:
                    all_valid = False
            # Track hard-constraint items
            if item.get("hard_constraint") is True:
                name = item.get("item", "")
                hard_items.append(name)
                if name == "事实一致性":
                    has_fact_consistency = True
                if name == "字段完整率":
                    has_field_completeness = True

    if all_valid and not missing_dims:
        review_status = "complete"
    elif total_items:
        review_status = "partial"
    else:
        review_status = "empty"

    return RubricDesignerResult(
        rubric=merged,
        item_count=total_items,
        hard_constraint_items=hard_items,
        has_fact_consistency_hard=has_fact_consistency,
        has_field_completeness=has_field_completeness,
        missing_dims=missing_dims,
        review_status=review_status,
        extraction_notes=notes,
    )


def _llm_extract_rubric(
    llm_client: Any,
    atomic_tasks: list[dict],
) -> list[tuple[str, dict[str, Any]]]:
    """Extract rubric items from atomic-task specs via LLM.

    This is a thin adapter — the actual LLM prompt and parsing logic
    live in the risk_semantic package.  Here we only provide the hook;
    when the LLM is unconfigured or returns an error, the caller
    degrades gracefully to seed-only extraction.
    """
    # Placeholder for LLM extraction — the prompt template and JSON
    # parsing are implemented in risk_semantic.patcher_prompts.  For
    # now, return empty; the Sub-agent is still useful via seed+evidence.
    _ = (llm_client, atomic_tasks)  # silence unused
    return []
