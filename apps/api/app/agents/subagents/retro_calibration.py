"""P4-2 retro-calibration — retroactive calibration agent (§3.5.2 步骤9).

Thesis §3.5.2 步骤9 + §5.3.1-§5.3.2: when the shadow-run / retro Actual
SLA diverges from the probe Actual SLA beyond the acceptable interval
(式(7) |gap| > 3pp), this agent produces revision suggestions at
rule/threshold/sample/task granularity and — critically — marks a *new*
framework version rather than overwriting the old conclusion (§5.3.2:
"风险规则确认后必须锁定，后续修改必须开新版本，不能覆盖旧版本").

§5.3.2 four-direction偏差归因 (deviation attribution):
  1. 样本代表性不足 (sample) — probe sample not covering high-freq
  2. 任务拆解粒度不当 (task) — atomic task granularity too coarse/fine
  3. 目标SLA设定偏差 (threshold/sla) — param source/interval issue
  4. HITL配置过强或过弱 (rule) — HITL intensity mismatch

§5.3.2 framework revision record template (9 fields):
  revision_id, trigger_source, deviation_magnitude, attribution_direction,
  revised_item, evidence_ref, rollback_target, approval_status,
  impacted_stages

This Sub-agent is mounted on the existing Stage 4 Skill — NOT a
standalone 9-Agent target (CLAUDE.md "9 Agent 是目标架构，当前由 4
个阶段级分析 Skill 聚合执行").

Constraint (§3.3.2 "先固定净价值、单次反推"): retro-calibration
never feeds retro Actual SLA back into the target-side SLA 反推 — it
produces a new *framework version* for future runs, not a re-adjusted
target for the current decision.  The current decision's target_sla
remains frozen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.apps.api.app.services.formulas import compute_retro_gap
from src.apps.api.app.services.formulas.retro_gap import (
    ALL_REVISION_GRANULARITIES,
    REVISION_GRANULARITY_RULE,
    REVISION_GRANULARITY_SAMPLE,
    REVISION_GRANULARITY_TASK,
    REVISION_GRANULARITY_THRESHOLD,
)

# ── §5.3.1 relative deviation rate thresholds (representativeness caliber) ──

# §5.3.1: 偏差率 = |T1-T0|/T0
#   ≤ 10% → 探针结果代表性成立（时间序列稳定）
#   10%-30% → 部分代表性需偏差归因
#   > 30% → 探针结果不具代表性，进入四方向归因
# Note: these are the §5.3.1 relative-rate caliber, NOT the 式(7)
# absolute-gap trigger (which uses 3pp).  The two calibers do not mix.
REPRESENTATIVENESS_STABLE_MAX: float = 0.10
REPRESENTATIVENESS_PARTIAL_MAX: float = 0.30

# ── §5.3.2 framework revision record template fields ──────────────────

REVISION_RECORD_FIELDS: tuple[str, ...] = (
    "revision_id",
    "trigger_source",
    "deviation_magnitude",
    "attribution_direction",
    "revised_item",
    "evidence_ref",
    "rollback_target",
    "approval_status",
    "impacted_stages",
)

# Trigger sources (§5.3.2 framework修订记录模板 field 2)
TRIGGER_SHADOW_DEVIATION = "影子运行偏差"
TRIGGER_MIGRATION_FAILURE = "迁移失败"
TRIGGER_EXPERT_REVIEW = "专家复核"

# Approval statuses (§5.3.2 field 8)
APPROVAL_PENDING = "待处理"
APPROVAL_CONFIRMED = "已确认"
APPROVAL_REJECTED = "已拒绝"

# §5.3.2: "中断点判据" — T1 fatal_error_rate > 0 (T0=0) → time-series
# interruption → framework correction (hard-constraint breach).
INTERRUPT_FATAL_RATE_FLAG = "fatal_rate_interrupt"


@dataclass
class RetroCalibrationResult:
    """Output of the retro-calibration Sub-agent.

    Attributes:
        gap: 式(7) gap = SLA_act,probe − SLA_act,retro (pp).
        abs_gap: |gap|.
        direction: probe_overestimate | probe_underestimate | no_deviation.
        needs_revision: bool — 式(7) |gap| > 3pp trigger.
        new_version_required: bool — True when a new framework version
            must be produced (mirrors needs_revision; §5.5.2 new version,
            not overwrite).
        revision_suggestions: list of {granularity, action, direction,
            urgency} — non-empty when needs_revision.
        representativeness: "stable" | "partial" | "unstable" | None —
            §5.3.1 relative-rate caliber grading.
        relative_deviation_rate: |T1-T0|/T0 (§5.3.1 caliber).
        fatal_rate_interrupt: bool — §5.3.2 中断点判据 (T1 fatal>0, T0=0).
        revision_records: list of framework revision record dicts
            (§5.3.2 9-field template), one per revision suggestion when
            new_version_required.
        rollback_target: str | None — version to roll back to.
        impacted_stages: list of stage identifiers affected (stale标记).
        review_status: "complete" | "partial" | "empty".
        extraction_notes: human-readable provenance notes.
    """

    gap: Optional[float] = None
    abs_gap: Optional[float] = None
    direction: Optional[str] = None
    needs_revision: bool = False
    new_version_required: bool = False
    revision_suggestions: list[dict[str, Any]] = field(default_factory=list)
    representativeness: Optional[str] = None
    relative_deviation_rate: Optional[float] = None
    fatal_rate_interrupt: bool = False
    revision_records: list[dict[str, Any]] = field(default_factory=list)
    rollback_target: Optional[str] = None
    impacted_stages: list[str] = field(default_factory=list)
    review_status: str = "empty"
    extraction_notes: list[str] = field(default_factory=list)


def calibrate_retrospective(
    *,
    sla_act_probe: Optional[float] = None,
    sla_act_retro: Optional[float] = None,
    history_log: dict[str, Any] | None = None,
    current_version: str = "v1",
    risk_level: Optional[str] = None,
) -> RetroCalibrationResult:
    """Run retroactive calibration (§3.5.2 步骤9) — 式(7) gap + version mgmt.

    Args:
        sla_act_probe: probe Actual SLA (T0, percentage points).
        sla_act_retro: retro/shadow-run Actual SLA (T1, percentage points).
        history_log: historical run log dict with optional fields:
            ``probe_fatal_rate`` (T0), ``retro_fatal_rate`` (T1),
            ``previous_gaps`` (list of prior gaps for trend),
            ``evidence_refs`` (list of evidence IDs).
        current_version: current framework version label (for rollback target).
        risk_level: L1/L2/L3 — impacts impacted_stages cascade.

    Returns:
        RetroCalibrationResult with gap + revision suggestions + version
        records.
    """
    notes: list[str] = []
    log = history_log or {}

    # ── Phase 1: 式(7) retro gap ──
    gap_result = compute_retro_gap(
        sla_act_probe=sla_act_probe,
        sla_act_retro=sla_act_retro,
    )

    gap = gap_result["gap"]
    abs_gap = gap_result["abs_gap"]
    direction = gap_result["direction"]
    needs_revision = gap_result["needs_revision"]
    suggestions = gap_result["revision_suggestions"]
    rel_rate = gap_result["relative_deviation_rate"]

    if gap is None:
        return RetroCalibrationResult(
            review_status="empty",
            extraction_notes=[
                "Missing sla_act_probe or sla_act_retro; cannot compute 式(7) gap.",
                *gap_result.get("missing", []),
            ],
        )

    # ── Phase 2: §5.3.1 representativeness grading (relative-rate caliber) ──
    representativeness: Optional[str] = None
    if rel_rate is not None:
        if rel_rate <= REPRESENTATIVENESS_STABLE_MAX:
            representativeness = "stable"
        elif rel_rate <= REPRESENTATIVENESS_PARTIAL_MAX:
            representativeness = "partial"
        else:
            representativeness = "unstable"

    # ── Phase 3: §5.3.2 中断点判据 (fatal-rate time-series interruption) ──
    probe_fatal = _num(log.get("probe_fatal_rate"))
    retro_fatal = _num(log.get("retro_fatal_rate"))
    fatal_interrupt = False
    if probe_fatal is not None and retro_fatal is not None:
        # T0=0 and T1>0 → time-series interruption (hard-constraint breach)
        if probe_fatal == 0.0 and retro_fatal > 0.0:
            fatal_interrupt = True
            notes.append(
                "§5.3.2 中断点判据：T1 致命错误率>0（T0=0），"
                "时间序列中断，触发框架修正。"
            )

    # Fatal interrupt forces revision even if gap is within 3pp
    if fatal_interrupt and not needs_revision:
        needs_revision = True
        # Add a rule-granularity suggestion for the fatal interrupt
        suggestions = list(suggestions) + [{
            "granularity": REVISION_GRANULARITY_RULE,
            "action": (
                "致命错误率时间序列中断（T1>0, T0=0）——"
                "复核 HITL 配置与致命错误四类定义，强化禁入红线"
            ),
            "direction": direction or "no_deviation",
            "urgency": "critical",
        }]

    # ── Phase 4: §5.3.2 framework revision records (new version, not overwrite) ──
    revision_records: list[dict[str, Any]] = []
    impacted_stages: list[str] = []
    rollback_target: Optional[str] = None

    if needs_revision:
        # Each suggestion becomes a revision record (§5.3.2 9-field template)
        for idx, sugg in enumerate(suggestions):
            record = _build_revision_record(
                index=idx,
                suggestion=sugg,
                gap=gap,
                abs_gap=abs_gap,
                direction=direction,
                trigger_source=TRIGGER_SHADOW_DEVIATION,
                evidence_refs=log.get("evidence_refs", []),
                rollback_version=current_version,
            )
            revision_records.append(record)

            # Map granularity → impacted downstream stages (stale标记)
            impacted = _granularity_to_impacted_stages(
                sugg["granularity"], risk_level
            )
            for stage in impacted:
                if stage not in impacted_stages:
                    impacted_stages.append(stage)

        rollback_target = current_version  # §5.3.2: rollback to current (pre-revision) version

        notes.append(
            f"§3.5.2 回溯校准：|gap|={abs_gap}pp 超过 3pp 阈值"
            + (f"（或致命错误率中断）" if fatal_interrupt else "")
            + f"；生成 {len(revision_records)} 条修订记录，"
            f"回滚目标={rollback_target}，影响阶段={impacted_stages}。"
            f"必须开新版本（{current_version}→next），不得覆盖旧结论。"
        )

    # ── Review status ──
    if needs_revision:
        review_status = "complete" if revision_records else "partial"
    else:
        review_status = "complete"

    # ── Notes for non-revision case ──
    if not needs_revision:
        rep_note = ""
        if representativeness:
            rep_note = f" §5.3.1 代表性={representativeness}（相对偏差率={rel_rate}）。"
        notes.append(
            f"式(7) |gap|={abs_gap}pp ≤ 3pp 阈值，无需修正。"
            + rep_note
        )

    return RetroCalibrationResult(
        gap=gap,
        abs_gap=abs_gap,
        direction=direction,
        needs_revision=needs_revision,
        new_version_required=needs_revision,
        revision_suggestions=suggestions,
        representativeness=representativeness,
        relative_deviation_rate=rel_rate,
        fatal_rate_interrupt=fatal_interrupt,
        revision_records=revision_records,
        rollback_target=rollback_target,
        impacted_stages=impacted_stages,
        review_status=review_status,
        extraction_notes=notes,
    )


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _build_revision_record(
    *,
    index: int,
    suggestion: dict[str, Any],
    gap: Optional[float],
    abs_gap: Optional[float],
    direction: Optional[str],
    trigger_source: str,
    evidence_refs: list[str],
    rollback_version: str,
) -> dict[str, Any]:
    """Build a §5.3.2 9-field framework revision record."""
    granularity = suggestion.get("granularity", "")
    # attribution_direction maps granularity → §5.3.2 four-direction
    direction_map = {
        REVISION_GRANULARITY_SAMPLE: "样本",
        REVISION_GRANULARITY_TASK: "任务拆解",
        REVISION_GRANULARITY_THRESHOLD: "SLA",
        REVISION_GRANULARITY_RULE: "HITL",
    }
    return {
        "revision_id": f"rev-{index + 1:03d}",
        "trigger_source": trigger_source,
        "deviation_magnitude": f"{abs_gap}pp" if abs_gap is not None else None,
        "attribution_direction": direction_map.get(granularity, granularity),
        "revised_item": suggestion.get("action", ""),
        "evidence_ref": evidence_refs[index] if index < len(evidence_refs) else "",
        "rollback_target": rollback_version,
        "approval_status": APPROVAL_PENDING,
        "impacted_stages": _granularity_to_impacted_stages(granularity, None),
        "granularity": granularity,
        "urgency": suggestion.get("urgency", ""),
        "gap_direction": direction,
    }


def _granularity_to_impacted_stages(
    granularity: str, risk_level: Optional[str]
) -> list[str]:
    """Map revision granularity to impacted downstream stages (§5.3.2 stale标记).

    §5.3.2: "风险等级变更会影响阶段二、三、四的输出，必须触发重算或stale标记"
    """
    if granularity == REVISION_GRANULARITY_RULE:
        # HITL changes → risk_level may change → impacts stages 2,3,4
        return ["stage1", "stage2", "stage3", "stage4"]
    elif granularity == REVISION_GRANULARITY_THRESHOLD:
        # Target SLA changes → impacts stage 3 (actual comparison) + stage 4 (decision)
        return ["stage2", "stage3", "stage4"]
    elif granularity == REVISION_GRANULARITY_SAMPLE:
        # Sample changes → impacts stage 3 (probe re-run)
        return ["stage3"]
    elif granularity == REVISION_GRANULARITY_TASK:
        # Task decomposition changes → impacts stage 3 (rubric re-design)
        return ["stage3"]
    return []


def _num(value: Any) -> Optional[float]:
    """Extract a float from a value, rejecting bool/None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
