"""P4-3 evidence-fusion — three-dimension evidence fusion agent (§3.5.1).

Thesis §3.5.1 三维证据融合: fuses risk grading result, target SLA and
Actual SLA into a structured *evidence fusion table* for the §3.5
decision.  The fusion table design (§3.5.1):

    行 (rows) = 原子任务 (atomic tasks: 预警触发识别/风险原因归纳/
                  风险等级初判/处置建议生成)
    列 (cols) = 三维证据 (risk_level + HITL强度, target_sla 门槛,
                  actual_sla 实测值, 达标判断)

Evidence strength grading (§3.5.1):
  * **否决级 (hard-constraint)**: fatal_error_rate=0, HITL强度与风险
    等级对齐, 审计完整率达风险等级最低门槛 — any failure → nogo
  * **参考级 (reference)**: efficiency + non-critical governance
    indicators — failure → hold (可补充论证)
  * **决策级 (decision)**: net value — <0 → hold (补充论证),
    sensitivity-confirmed negative → nogo (式(6) 第四条)

This Sub-agent surfaces evidence conflicts between dimensions (e.g.
risk says L3 but governance SLA floor not raised) for the §3.5.2
hard-constraint check to resolve.

Mounted on the existing Stage 4 Skill — NOT a standalone 9-Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.apps.api.app.services.formulas import (
    A_AUDIT_MIN_BY_RISK,
    E_CRIT_MAX_BY_RISK,
    SLA_FLOOR_BY_RISK,
    W_D_DEFAULT,
)

# ── Evidence strength tiers (§3.5.1) ───────────────────────────────────

STRENGTH_HARD_CONSTRAINT = "否决级"  # hard-constraint (veto-level)
STRENGTH_REFERENCE = "参考级"        # reference (soft — hold if fails)
STRENGTH_DECISION = "决策级"        # decision (net value — drives go/hold/nogo)

# ── Dimension identifiers ──────────────────────────────────────────────

DIM_RISK = "risk"
DIM_VALUE = "value"
DIM_TECH = "tech"


@dataclass
class EvidenceFusionResult:
    """Output of the evidence-fusion Sub-agent.

    Attributes:
        three_dim_fusion_table: list of per-task rows, each row a dict
            with task_id + per-dimension evidence cells
            ({risk, value, tech} → {evidence, strength, meets}).
        evidence_conflicts: list of cross-dimension conflicts (e.g.
            risk=L3 but gov SLA floor not raised).
        strength_summary: {否决级, 参考级, 决策级} → count.
        task_count: int — number of atomic tasks in the fusion table.
        hard_constraint_failures: list of 否决级 failures (any → nogo).
        review_status: "complete" | "partial" | "empty".
        extraction_notes: human-readable provenance notes.
    """

    three_dim_fusion_table: list[dict[str, Any]] = field(default_factory=list)
    evidence_conflicts: list[dict[str, Any]] = field(default_factory=list)
    strength_summary: dict[str, int] = field(default_factory=dict)
    task_count: int = 0
    hard_constraint_failures: list[dict[str, Any]] = field(default_factory=list)
    review_status: str = "empty"
    extraction_notes: list[str] = field(default_factory=list)


def fuse_three_dim_evidence(
    *,
    stage1_summary: dict[str, Any] | None = None,
    stage2_summary: dict[str, Any] | None = None,
    stage3_summary: dict[str, Any] | None = None,
    atomic_tasks: list[dict[str, Any]] | None = None,
    risk_level: Optional[str] = None,
) -> EvidenceFusionResult:
    """Fuse risk/value/tech three-dim evidence into per-task fusion table.

    Args:
        stage1_summary: Stage 1 output (risk grading + HITL).
            Expected fields: risk_level, hitl_level, prohibited_hit.
        stage2_summary: Stage 2 output (value modeling + target SLA).
            Expected fields: target_sla, net_value, implementation_tax_total.
        stage3_summary: Stage 3 output (probe + actual SLA).
            Expected fields: actual_sla, actual_sla_by_dim, fatal_error_rate,
            general_error_rate, audit_completeness.
        atomic_tasks: atomic tasks from P2-1 (for per-task rows).  When
            absent, a single aggregate row is produced.
        risk_level: override risk level (defaults to stage1_summary's).

    Returns:
        EvidenceFusionResult with the fusion table + conflicts.
    """
    notes: list[str] = []
    s1 = stage1_summary or {}
    s2 = stage2_summary or {}
    s3 = stage3_summary or {}

    r_level = risk_level or s1.get("risk_level") or "L1"

    # ── Build per-task rows ──
    tasks = atomic_tasks or []
    if not tasks:
        # Aggregate row when no atomic tasks provided
        tasks = [{"task_id": "aggregate", "name": "综合"}]

    fusion_rows: list[dict[str, Any]] = []
    hard_failures: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    strength_counts = {
        STRENGTH_HARD_CONSTRAINT: 0,
        STRENGTH_REFERENCE: 0,
        STRENGTH_DECISION: 0,
    }

    # ── Per-dimension evidence extraction ──
    risk_evidence = _extract_risk_evidence(s1, r_level)
    value_evidence = _extract_value_evidence(s2)
    tech_evidence = _extract_tech_evidence(s3, r_level)

    # ── Strength classification per evidence item ──
    risk_strength = _classify_risk_strength(risk_evidence, r_level)
    value_strength = STRENGTH_DECISION
    tech_strength = _classify_tech_strength(tech_evidence, r_level)

    strength_counts[risk_strength] = strength_counts.get(risk_strength, 0) + 1
    strength_counts[value_strength] = strength_counts.get(value_strength, 0) + 1
    strength_counts[tech_strength] = strength_counts.get(tech_strength, 0) + 1

    # ── Per-task rows: each task gets risk/value/tech cells ──
    # The risk + value evidence is shared across tasks (they come from
    # stage-level summaries), while tech evidence may be per-task when
    # actual_sla_by_dim has per_task breakdown.
    per_task_tech = tech_evidence.get("per_task") or []

    for task in tasks:
        tid = task.get("task_id", "")
        row = {
            "task_id": tid,
            "task_name": task.get("name", ""),
            "risk": {
                "evidence": {
                    "risk_level": r_level,
                    "hitl_level": risk_evidence.get("hitl_level"),
                    "prohibited_hit": risk_evidence.get("prohibited_hit"),
                },
                "strength": risk_strength,
                "meets": not risk_evidence.get("prohibited_hit", False),
            },
            "value": {
                "evidence": {
                    "target_sla": value_evidence.get("target_sla"),
                    "net_value": value_evidence.get("net_value"),
                    "implementation_tax": value_evidence.get("implementation_tax"),
                },
                "strength": value_strength,
                "meets": _value_meets(value_evidence),
            },
            "tech": _build_tech_cell(tid, tech_evidence, per_task_tech, tech_strength),
        }
        fusion_rows.append(row)

    # ── Hard-constraint failures (否决级, any → nogo) ──
    if risk_evidence.get("prohibited_hit"):
        hard_failures.append({
            "dim": "risk",
            "issue": "禁入条件命中（prohibited_hit=True）",
            "strength": STRENGTH_HARD_CONSTRAINT,
        })
    if tech_evidence.get("fatal_error_rate") is not None and tech_evidence["fatal_error_rate"] > 0:
        hard_failures.append({
            "dim": "tech",
            "issue": f"致命错误率={tech_evidence['fatal_error_rate']}>0",
            "strength": STRENGTH_HARD_CONSTRAINT,
        })

    # General error rate hard-constraint (§3.5.2 式(5))
    e_max = E_CRIT_MAX_BY_RISK.get(r_level)
    gen_rate = tech_evidence.get("general_error_rate")
    if e_max is not None and gen_rate is not None and gen_rate > e_max:
        hard_failures.append({
            "dim": "tech",
            "issue": f"一般错误率={gen_rate}>{e_max}（e_crit_max({r_level})）",
            "strength": STRENGTH_HARD_CONSTRAINT,
        })

    # Audit completeness hard-constraint (§3.5.2 式(5))
    a_min = A_AUDIT_MIN_BY_RISK.get(r_level)
    audit = tech_evidence.get("audit_completeness")
    if a_min is not None and audit is not None and audit < a_min:
        hard_failures.append({
            "dim": "tech",
            "issue": f"审计完整率={audit}<{a_min}（A_audit_min({r_level})）",
            "strength": STRENGTH_HARD_CONSTRAINT,
        })

    # ── Cross-dimension evidence conflicts ──
    conflicts = _detect_conflicts(
        risk_evidence=risk_evidence,
        value_evidence=value_evidence,
        tech_evidence=tech_evidence,
        risk_level=r_level,
    )

    # ── Review status ──
    has_any_input = bool(s1 or s2 or s3 or atomic_tasks)
    if not has_any_input:
        review_status = "empty"
    elif fusion_rows and not hard_failures:
        review_status = "complete"
    elif fusion_rows and hard_failures:
        review_status = "partial"  # has rows but hard-constraint failures
    else:
        review_status = "empty"

    if hard_failures:
        notes.append(
            f"否决级证据失败 {len(hard_failures)} 项："
            + "；".join(f"[{f['dim']}] {f['issue']}" for f in hard_failures)
            + "。任一否决级失败 → nogo。"
        )
    if conflicts:
        notes.append(
            f"三维证据冲突 {len(conflicts)} 项，须回 §3.5.2 硬约束检查解决。"
        )

    return EvidenceFusionResult(
        three_dim_fusion_table=fusion_rows,
        evidence_conflicts=conflicts,
        strength_summary=strength_counts,
        task_count=len(fusion_rows),
        hard_constraint_failures=hard_failures,
        review_status=review_status,
        extraction_notes=notes,
    )


# ═══════════════════════════════════════════════════════════════════════
# Per-dimension evidence extraction
# ═══════════════════════════════════════════════════════════════════════


def _extract_risk_evidence(
    stage1: dict[str, Any], risk_level: str
) -> dict[str, Any]:
    """Extract risk-dimension evidence from Stage 1 summary."""
    return {
        "risk_level": risk_level,
        "hitl_level": stage1.get("hitl_level"),
        "prohibited_hit": stage1.get("prohibited_hit", False),
        "audit_completeness": stage1.get("audit_completeness"),
    }


def _extract_value_evidence(
    stage2: dict[str, Any],
) -> dict[str, Any]:
    """Extract value-dimension evidence from Stage 2 summary."""
    return {
        "target_sla": stage2.get("target_sla"),
        "net_value": stage2.get("net_value"),
        "implementation_tax": stage2.get("implementation_tax_total"),
        "actor_net_values": stage2.get("actor_net_value"),
    }


def _extract_tech_evidence(
    stage3: dict[str, Any], risk_level: str
) -> dict[str, Any]:
    """Extract tech-dimension evidence from Stage 3 summary."""
    return {
        "actual_sla": stage3.get("actual_sla"),
        "actual_sla_by_dim": stage3.get("actual_sla_by_dim"),
        "fatal_error_rate": stage3.get("fatal_error_rate"),
        "general_error_rate": stage3.get("general_error_rate"),
        "audit_completeness": stage3.get("audit_completeness"),
        "gap_grade": stage3.get("gap_grade"),
        "per_task": stage3.get("per_task"),
    }


# ═══════════════════════════════════════════════════════════════════════
# Evidence strength classification (§3.5.1)
# ═════════════════════════════════════════════════ 否决级/参考级/决策级
# ═══════════════════════════════════════════════════════════════════════


def _classify_risk_strength(
    risk_evidence: dict[str, Any], risk_level: str
) -> str:
    """Risk-dimension evidence strength (§3.5.1)."""
    # prohibited_hit + fatal_error_rate + audit completeness are hard-constraint
    return STRENGTH_HARD_CONSTRAINT


def _classify_tech_strength(
    tech_evidence: dict[str, Any], risk_level: str
) -> str:
    """Tech-dimension evidence strength (§3.5.1).

    fatal_error_rate + 事实一致性/字段完整率 are 否决级;
    efficiency + non-critical governance are 参考级.
    """
    # When fatal errors present, the tech evidence is hard-constraint level.
    fatal = tech_evidence.get("fatal_error_rate")
    if fatal is not None and fatal > 0:
        return STRENGTH_HARD_CONSTRAINT
    # Otherwise fatal=0 (hard-constraint met), remaining tech indicators
    # (general_error_rate, audit, SLA gap) are 参考级.
    return STRENGTH_REFERENCE


def _value_meets(value_evidence: dict[str, Any]) -> bool:
    """Check if value evidence meets the admission threshold (V_net ≥ 0)."""
    nv = value_evidence.get("net_value")
    if nv is None:
        return True  # unknown → don't flag
    return nv >= 0


# ═══════════════════════════════════════════════════════════════════════
# Per-task tech cell builder
# ═══════════════════════════════════════════════════════════════════════


def _build_tech_cell(
    task_id: str,
    tech_evidence: dict[str, Any],
    per_task: list[dict[str, Any]],
    default_strength: str,
) -> dict[str, Any]:
    """Build the tech cell for a task in the fusion table."""
    # Find per-task actual_sla_by_dim when available
    task_tech = None
    for pt in per_task:
        if pt.get("task_id") == task_id:
            task_tech = pt
            break

    actual_sla = tech_evidence.get("actual_sla")
    actual_sla_by_dim = tech_evidence.get("actual_sla_by_dim")

    # Use per-task dim scores when available
    if task_tech and task_tech.get("actual_sla_by_dim"):
        actual_sla_by_dim = task_tech["actual_sla_by_dim"]

    return {
        "evidence": {
            "actual_sla": actual_sla,
            "actual_sla_by_dim": actual_sla_by_dim,
            "gap_grade": tech_evidence.get("gap_grade"),
            "fatal_error_rate": tech_evidence.get("fatal_error_rate"),
            "general_error_rate": tech_evidence.get("general_error_rate"),
            "audit_completeness": tech_evidence.get("audit_completeness"),
        },
        "strength": default_strength,
        "meets": _tech_meets(tech_evidence),
    }


def _tech_meets(tech_evidence: dict[str, Any]) -> bool:
    """Check if tech evidence meets hard constraints."""
    fatal = tech_evidence.get("fatal_error_rate")
    if fatal is not None and fatal > 0:
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════
# Cross-dimension conflict detection
# ═══════════════════════════════════════════════════════════════════════


def _detect_conflicts(
    *,
    risk_evidence: dict[str, Any],
    value_evidence: dict[str, Any],
    tech_evidence: dict[str, Any],
    risk_level: str,
) -> list[dict[str, Any]]:
    """Detect cross-dimension evidence conflicts (§3.5.1).

    A conflict is a logical inconsistency between dimensions that the
    §3.5.2 hard-constraint check must resolve — e.g. risk=L3 but
    governance SLA floor not raised, or tech gap_grade=严重失配 but
    value net_value>0 (value says go but tech says nogo).
    """
    conflicts: list[dict[str, Any]] = []

    # Conflict 1: risk=L3 but target_sla not raised to L3 floor
    target_sla = value_evidence.get("target_sla")
    l3_floor = SLA_FLOOR_BY_RISK.get("L3")
    if risk_level == "L3" and target_sla is not None and l3_floor is not None:
        if target_sla < l3_floor:
            conflicts.append({
                "conflict_type": "risk_value_sla_mismatch",
                "description": (
                    f"风险=L3 但 target_sla={target_sla} < L3 floor={l3_floor}，"
                    f"目标 SLA 未随风险等级提升"
                ),
                "dims": ["risk", "value"],
            })

    # Conflict 2: tech gap_grade=严重失配 but value net_value ≥ 0
    gap_grade = tech_evidence.get("gap_grade")
    nv = value_evidence.get("net_value")
    if gap_grade == "严重失配" and nv is not None and nv >= 0:
        conflicts.append({
            "conflict_type": "tech_value_contradiction",
            "description": (
                f"技术 gap_grade=严重失配 但净价值={nv}≥0；"
                f"价值说 go 但技术说 nogo"
            ),
            "dims": ["tech", "value"],
        })

    # Conflict 3: fatal_error_rate > 0 but verdict not nogo (value positive)
    fatal = tech_evidence.get("fatal_error_rate")
    if fatal is not None and fatal > 0 and nv is not None and nv >= 0:
        conflicts.append({
            "conflict_type": "fatal_violation_value_contradiction",
            "description": (
                f"致命错误率={fatal}>0（硬约束失败）但净价值={nv}≥0；"
                f"硬约束优先，应为 nogo"
            ),
            "dims": ["tech", "value"],
        })

    # Conflict 4: risk L3 but hitl_level not strict/mandatory
    hitl = risk_evidence.get("hitl_level")
    if risk_level == "L3" and hitl is not None and hitl not in ("strict", "mandatory"):
        conflicts.append({
            "conflict_type": "risk_hitl_mismatch",
            "description": (
                f"风险=L3 但 HITL={hitl}（应为 strict/mandatory）"
            ),
            "dims": ["risk"],
        })

    return conflicts
