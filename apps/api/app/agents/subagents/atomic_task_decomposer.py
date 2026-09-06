"""P2-1 atomic-task-decomposer — decompose SOP nodes into measurable atomic tasks.

Thesis §3.4.1: an atomic task is the smallest unit of GenAI work that is
independently measurable, reviewable, and traceable to a process node and
a risk point.  Each atomic task carries a dual-axis annotation:

  * ``non_routine`` (1-5): how non-routine / novel the task inputs are
    (1 = highly templated, 5 = highly variable).  Drives the jagged-
    frontier analysis (P3-2).
  * ``interdependence`` (1-5): how tightly coupled the task is with
    upstream/downstream human judgment (1 = standalone, 5 = deeply
    woven into the review chain).  Drives HITL burden allocation.

Each task also carries a ``sla_dim`` primary-dimension tag (qual / eff /
gov) so the rubric designer (P2-2) can anchor the three-dimension rubric
to tasks, and the actual-SLA aggregator (式(4)) can emit per-task dim
scores.

This Sub-agent is mounted on the existing Stage 3 Skill — NOT a
standalone 9-Agent target (CLAUDE.md "9 Agent 是目标架构，当前由 4
个阶段级分析 Skill 聚合执行").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── Atomic-task field schema (§3.4.1) ─────────────────────────────────

# Required fields on every atomic task (dev-plan §6 Stage 3 contract).
REQUIRED_TASK_FIELDS: tuple[str, ...] = (
    "task_id",
    "name",
    "non_routine",
    "interdependence",
    "owner_role",
    "review_node",
    "sla_dim",
)

# Valid SLA dimension tags.
VALID_SLA_DIMS: tuple[str, ...] = ("qual", "eff", "gov")

# Dual-axis rating bounds.
NON_ROUTINE_MIN, NON_ROUTUNE_MAX = 1, 5
INTERDEPENDENCE_MIN, INTERDEPENDENCE_MAX = 1, 5

# ── Loan-post scenario seed (Delphi prior — §3.4.1 case seed) ─────────
# Source: 典型场景业务底稿 §3 nodes N2-N5 (GenAI intervention points).
# Annotated as initial reference values pending M2-M4 empirical calibration.
LOAN_POST_SEED_TASKS: list[dict[str, Any]] = [
    {
        "task_id": "at-1",
        "name": "经营异常汇总",
        "source_node_id": "N2",
        "non_routine": 4,
        "interdependence": 3,
        "owner_role": "客户经理/风险经理",
        "review_node": "N6",
        "sla_dim": "qual",
        "task_type": "抽取",
        "input_schema": "研判材料包（财报摘要、贷后检查记录、预警信号、公开舆情摘要）",
        "output_schema": "经营异常清单",
        "forbidden_outputs": "风险等级判定、处置建议",
        "expected_review_role": "风险经理",
        "source": "德尔菲先验",
    },
    {
        "task_id": "at-2",
        "name": "预警信号核验",
        "source_node_id": "N3",
        "non_routine": 3,
        "interdependence": 4,
        "owner_role": "风险经理",
        "review_node": "N6",
        "sla_dim": "qual",
        "task_type": "审核",
        "input_schema": "预警信号、贷后检查记录",
        "output_schema": "预警核验结论",
        "forbidden_outputs": "自动触发处置、风险等级自动调整",
        "expected_review_role": "风险经理",
        "source": "德尔菲先验",
    },
    {
        "task_id": "at-3",
        "name": "风险疑点提取",
        "source_node_id": "N4",
        "non_routine": 4,
        "interdependence": 4,
        "owner_role": "风险经理",
        "review_node": "N6",
        "sla_dim": "qual",
        "task_type": "抽取",
        "input_schema": "经营异常清单、预警核验结论",
        "output_schema": "疑点清单（口径冲突/材料缺失/信息滞后）",
        "forbidden_outputs": "风险等级判定、处置动作",
        "expected_review_role": "风险经理",
        "source": "德尔菲先验",
    },
    {
        "task_id": "at-4",
        "name": "风险摘要草拟",
        "source_node_id": "N5",
        "non_routine": 5,
        "interdependence": 5,
        "owner_role": "客户经理/风险经理",
        "review_node": "N6",
        "sla_dim": "qual",
        "task_type": "汇总",
        "input_schema": "疑点清单、经营异常清单",
        "output_schema": "风险摘要底稿",
        "forbidden_outputs": "风险等级自动判定、处置建议、合规结论",
        "expected_review_role": "风险经理+合规复核人员（条件触发）",
        "source": "德尔菲先验",
    },
]


@dataclass
class AtomicTaskDecomposerResult:
    """Output of the atomic-task-decomposer Sub-agent.

    Attributes:
        atomic_tasks: list of atomic tasks, each with the §3.4.1 field
            schema (task_id, name, non_routine, interdependence,
            owner_role, review_node, sla_dim) plus provenance fields.
        task_count: int — number of decomposed tasks
        dual_axis_annotated: bool — True when every task has both
            non_routine and interdependence in [1, 5]
        missing_fields: task_id → list of missing required fields
        sla_dim_distribution: {qual, eff, gov} → count
        review_status: "complete" (≥1 task, all fields, valid sla_dim) |
            "partial" (some tasks missing fields or invalid sla_dim) |
            "empty"
        extraction_notes: human-readable provenance notes
    """

    atomic_tasks: list[dict[str, Any]] = field(default_factory=list)
    task_count: int = 0
    dual_axis_annotated: bool = False
    missing_fields: dict[str, list[str]] = field(default_factory=dict)
    sla_dim_distribution: dict[str, int] = field(default_factory=dict)
    review_status: str = "empty"  # complete | partial | empty
    extraction_notes: list[str] = field(default_factory=list)


def decompose_atomic_tasks(
    *,
    process_nodes: list[dict] | None = None,
    sop_text: str | None = None,
    scenario_key: str | None = None,
    delphi_seed_tasks: list[dict] | None = None,
    evidence_tasks: list[dict] | None = None,
    llm_client: Any = None,
) -> AtomicTaskDecomposerResult:
    """Decompose SOP process nodes into measurable atomic tasks (§3.4.1).

    The decomposition proceeds in three phases:

    1. **Seed merge**: Delphi prior seed tasks (annotated "初始参考值，
       待 M2-M4 实证标定") are merged with evidence-derived tasks.
       Evidence tasks override seeds on ``task_id`` collision.
       When *scenario_key* is recognized (e.g. ``loan_post``), the
       scenario seed is loaded as the Delphi prior baseline.
    2. **LLM extraction** (optional): when *llm_client* is provided,
       additional tasks are extracted from free-text SOP materials.
       Unconfigured / LLM-failed runs degrade gracefully to seed-only.
    3. **Schema validation**: each task is validated against the
       §3.4.1 field schema; dual-axis bounds and sla_dim tags are
       checked.  Missing/invalid fields are collected but do not drop
       the task — the caller sees the full list plus the defects.

    Args:
        process_nodes: SOP process nodes (from Stage 1 document_parse).
            Each node: ``{node_id, name, inputs, outputs, owner}``.
        sop_text: free-text SOP description (for LLM extraction).
        scenario_key: scenario identifier for seed selection
            (e.g. ``"loan_post"``).  None → no scenario seed.
        delphi_seed_tasks: Delphi prior seed tasks (override scenario
            seed when both provided).
        evidence_tasks: evidence-derived tasks (highest confidence).
        llm_client: optional LLM client for free-text extraction.

    Returns:
        AtomicTaskDecomposerResult with the atomic-task list.
    """
    notes: list[str] = []

    # ── Phase 1: seed merge ──
    # Scenario seed is the baseline Delphi prior; explicit seed overrides
    # scenario seed; evidence overrides any seed on task_id collision.
    if delphi_seed_tasks is not None:
        seed = list(delphi_seed_tasks)
    elif scenario_key == "loan_post":
        seed = [dict(t) for t in LOAN_POST_SEED_TASKS]
        notes.append("使用贷后场景德尔菲先验种子值（4 原子任务）；待 M2-M4 实证标定后替换为证据材料。")
    else:
        seed = []

    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for task in seed:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id", "")
        if task_id and task_id in seen_ids:
            continue
        merged.append({**task, "source": task.get("source", "德尔菲先验")})
        if task_id:
            seen_ids.add(task_id)

    for task in (evidence_tasks or []):
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id", "")
        if task_id and task_id in seen_ids:
            # Evidence overrides seed — replace the seed entry
            merged = [
                {**task, "source": task.get("source", "证据材料")}
                if (t.get("task_id") == task_id)
                else t
                for t in merged
            ]
        else:
            merged.append({**task, "source": task.get("source", "证据材料")})
            if task_id:
                seen_ids.add(task_id)

    # ── Phase 2: LLM extraction (optional) ──
    llm_added = 0
    if llm_client is not None and (sop_text or process_nodes):
        llm_tasks = _llm_extract_tasks(
            llm_client, sop_text or "", process_nodes or []
        )
        for task in llm_tasks:
            task_id = task.get("task_id", "")
            if task_id and task_id in seen_ids:
                continue
            merged.append({**task, "source": "LLM抽取"})
            if task_id:
                seen_ids.add(task_id)
            llm_added += 1
        if llm_added:
            notes.append(f"LLM 抽取新增 {llm_added} 个原子任务。")

    if not merged:
        return AtomicTaskDecomposerResult(
            review_status="empty",
            extraction_notes=["No atomic tasks provided (neither seed nor evidence nor LLM extraction)."],
        )

    if delphi_seed_tasks is None and scenario_key != "loan_post" and not evidence_tasks:
        notes.append("仅使用德尔菲先验种子值；待 M2-M4 实证标定后替换为证据材料。")

    # ── Phase 3: schema validation ──
    missing_fields: dict[str, list[str]] = {}
    sla_dist = {"qual": 0, "eff": 0, "gov": 0}
    all_valid = True

    for task in merged:
        tid = task.get("task_id", "<unknown>")
        missing = [
            f for f in REQUIRED_TASK_FIELDS if f not in task or task[f] is None
        ]
        if missing:
            missing_fields[tid] = missing
            all_valid = False

        # Validate sla_dim
        dim = task.get("sla_dim")
        if dim in VALID_SLA_DIMS:
            sla_dist[dim] += 1
        elif dim is not None:
            missing_fields.setdefault(tid, []).append(f"sla_dim(无效值:{dim})")
            all_valid = False

        # Validate dual-axis bounds
        for axis, lo, hi in (
            ("non_routine", NON_ROUTINE_MIN, NON_ROUTUNE_MAX),
            ("interdependence", INTERDEPENDENCE_MIN, INTERDEPENDENCE_MAX),
        ):
            val = task.get(axis)
            if val is not None:
                if not isinstance(val, (int, float)) or not (lo <= val <= hi):
                    missing_fields.setdefault(tid, []).append(
                        f"{axis}(越界:{val}, 应在[{lo},{hi}])"
                    )
                    all_valid = False

    dual_axis_ok = all(
        isinstance(t.get("non_routine"), (int, float))
        and isinstance(t.get("interdependence"), (int, float))
        and NON_ROUTINE_MIN <= t.get("non_routine", 0) <= NON_ROUTUNE_MAX
        and INTERDEPENDENCE_MIN <= t.get("interdependence", 0) <= INTERDEPENDENCE_MAX
        for t in merged
    ) if merged else False

    if all_valid and merged:
        review_status = "complete"
    elif merged:
        review_status = "partial"
    else:
        review_status = "empty"

    return AtomicTaskDecomposerResult(
        atomic_tasks=merged,
        task_count=len(merged),
        dual_axis_annotated=dual_axis_ok,
        missing_fields=missing_fields,
        sla_dim_distribution=sla_dist,
        review_status=review_status,
        extraction_notes=notes,
    )


def _llm_extract_tasks(
    llm_client: Any,
    sop_text: str,
    process_nodes: list[dict],
) -> list[dict[str, Any]]:
    """Extract atomic tasks from free-text SOP via LLM.

    This is a thin adapter — the actual LLM prompt and parsing logic
    live in the risk_semantic package.  Here we only provide the hook;
    when the LLM is unconfigured or returns an error, the caller
    degrades gracefully to seed-only extraction.
    """
    # Placeholder for LLM extraction — the prompt template and JSON
    # parsing are implemented in risk_semantic.patcher_prompts.  For
    # now, return empty; the Sub-agent is still useful via seed+evidence.
    _ = (llm_client, sop_text, process_nodes)  # silence unused
    return []
