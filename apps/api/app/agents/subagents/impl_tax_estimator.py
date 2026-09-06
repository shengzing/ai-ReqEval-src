"""P1-4 impl-tax-estimator — LLM extraction of 式(1) seven-category tax items.

Thesis §3.3.2 式(1): T_tax = Σ_k T_tax,k, k ∈ {review, rework, audit,
monitor, coord, integ, train}.

This Sub-agent extracts the seven-category itemised implementation-tax
ledger from evidence materials (post-loan SOP, audit checklists, shift
schedules, Delphi prior seeds) and validates them via the formulas
package.  It is a Sub-agent mounted on the existing Stage 2 Skill —
NOT a standalone 9-Agent target (CLAUDE.md "9 Agent 是目标架构，当前由
4 个阶段级分析 Skill 聚合执行").

Categories and actor attribution (§3.3.2):
  review  → 业务 + 风险/合规   (复核动作：签字、意见填写)
  rework  → 业务 + 风险/合规   (复核后修正：重做或补录)
  audit   → 风险/合规          (留痕动作：日志填写、归档)
  monitor → 科技               (模型监控)
  coord   → 运营               (跨部门协同)
  integ   → 科技               (系统集成)
  train   → 风险/合规 + 运营   (培训)

Repetition-prevention rule (§3.3.2 重复计量防范): the three action
categories (review/rework/audit) do not overlap — 复核 vs 修正 vs 留痕
— so the same human work is not double-priced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.apps.api.app.services.formulas import compute_implementation_tax
from src.apps.api.app.services.formulas.impl_tax import SEVEN_CATEGORIES


@dataclass
class ImplTaxEstimatorResult:
    """Output of the impl-tax-estimator Sub-agent.

    Attributes:
        items: list of implementation-tax line items (七类), each
            ``{category, item_id, unit_cost, quantity, rho_H?, source?}``
        tax_total: float — 式(1) total (None if missing parameters)
        tax_by_category: {category: float}
        tax_by_actor: {actor: float}
        missing_categories: categories present in SEVEN_CATEGORIES but
            not in items — used to flag incomplete extraction
        missing_parameters: item fields without values
        review_status: "complete" (all 7 categories, no missing params) |
            "partial" (some categories/params missing) | "empty"
        extraction_notes: human-readable provenance notes
    """

    items: list[dict[str, Any]] = field(default_factory=list)
    tax_total: Optional[float] = None
    tax_by_category: dict[str, float] = field(default_factory=dict)
    tax_by_actor: dict[str, float] = field(default_factory=dict)
    missing_categories: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)
    review_status: str = "empty"  # complete | partial | empty
    extraction_notes: list[str] = field(default_factory=list)


def estimate_implementation_tax(
    *,
    evidence_items: list[dict] | None = None,
    delphi_seed_items: list[dict] | None = None,
    hitl_level: str = "none",
    llm_client: Any = None,
) -> ImplTaxEstimatorResult:
    """Extract and validate the 式(1) seven-category implementation tax.

    The extraction proceeds in three phases:

    1. **Seed merge**: Delphi prior seed items (annotated "初始参考值，
       待 M2-M4 实证标定") are merged with evidence-derived items.
       Evidence items override seeds on ``item_id`` collision.
    2. **LLM extraction** (optional): when *llm_client* is provided,
       additional items are extracted from free-text evidence materials.
       Unconfigured / LLM-failed runs degrade gracefully to seed-only.
    3. **Formula validation**: the merged item list is handed to
       ``compute_implementation_tax`` (pure function) which applies
       rho_H cascade, actor attribution, and repetition-prevention.

    Args:
        evidence_items: evidence-derived tax items (highest confidence).
        delphi_seed_items: Delphi prior seed items (lowest confidence;
            annotated as initial reference values).
        hitl_level: HITL intensity (none/standard/strict/mandatory) —
            resolves rho_H for review-category items lacking explicit rho_H.
        llm_client: optional LLM client for free-text extraction.

    Returns:
        ImplTaxEstimatorResult with the full tax ledger.
    """
    notes: list[str] = []

    # ── Phase 1: seed merge ──
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for item in (delphi_seed_items or []):
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id", "")
        if item_id and item_id in seen_ids:
            continue
        merged.append({**item, "source": item.get("source", "德尔菲先验")})
        if item_id:
            seen_ids.add(item_id)

    for item in (evidence_items or []):
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id", "")
        if item_id and item_id in seen_ids:
            # Evidence overrides seed — replace the seed entry
            merged = [
                {**item, "source": item.get("source", "证据材料")}
                if (i.get("item_id") == item_id)
                else i
                for i in merged
            ]
        else:
            merged.append({**item, "source": item.get("source", "证据材料")})
            if item_id:
                seen_ids.add(item_id)

    if not merged:
        return ImplTaxEstimatorResult(
            review_status="empty",
            extraction_notes=["No implementation-tax items provided (neither evidence nor Delphi seed)."],
        )

    if delphi_seed_items and not evidence_items:
        notes.append("仅使用德尔菲先验种子值；待 M2-M4 实证标定后替换为证据材料。")

    # ── Phase 2: LLM extraction (optional) ──
    llm_added = 0
    if llm_client is not None:
        llm_items = _llm_extract_tax_items(llm_client, merged, hitl_level)
        for item in llm_items:
            item_id = item.get("item_id", "")
            if item_id and item_id in seen_ids:
                continue
            merged.append({**item, "source": "LLM抽取"})
            if item_id:
                seen_ids.add(item_id)
            llm_added += 1
        if llm_added:
            notes.append(f"LLM 抽取新增 {llm_added} 条实施税项。")

    # ── Phase 3: formula validation ──
    tax_result = compute_implementation_tax(
        items=merged, hitl_level=hitl_level
    )

    # Identify missing categories
    found_categories = {item.get("category") for item in merged}
    missing_categories = [c for c in SEVEN_CATEGORIES if c not in found_categories]

    # Determine review status
    if not missing_categories and not tax_result["missing_parameters"]:
        review_status = "complete"
    elif merged:
        review_status = "partial"
    else:
        review_status = "empty"

    return ImplTaxEstimatorResult(
        items=tax_result["items"],
        tax_total=tax_result["implementation_tax_total"],
        tax_by_category=tax_result["tax_by_category"],
        tax_by_actor=tax_result["tax_by_actor"],
        missing_categories=missing_categories,
        missing_parameters=tax_result["missing_parameters"],
        review_status=review_status,
        extraction_notes=notes,
    )


def _llm_extract_tax_items(
    llm_client: Any,
    existing_items: list[dict],
    hitl_level: str,
) -> list[dict[str, Any]]:
    """Extract additional tax items from free-text evidence via LLM.

    This is a thin adapter — the actual LLM prompt and parsing logic
    live in the risk_semantic package.  Here we only provide the hook;
    when the LLM is unconfigured or returns an error, the caller
    degrades gracefully to seed-only extraction.
    """
    # Placeholder for LLM extraction — the prompt template and JSON
    # parsing are implemented in risk_semantic.patcher_prompts.  For
    # now, return empty; the Sub-agent is still useful via seed+evidence.
    _ = (llm_client, existing_items, hitl_level)  # silence unused
    return []
