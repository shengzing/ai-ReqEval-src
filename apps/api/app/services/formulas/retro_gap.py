"""式(7) Retroactive gap calculator — probe vs retro Actual SLA (§3.5.2).

Thesis §3.5.2 式(7):

    gap = SLA_act,probe − SLA_act,retro

Where ``SLA_act,retro`` shares the same caliber as 式(4) (same w_d,
same Rubric version).  ``gap > 0`` means the probe overestimated (probe
scored higher than the retro/shadow run); ``gap < 0`` means the probe
underestimated.

When ``|gap|`` exceeds the acceptable interval (≤ 3 percentage points
in the SLA-percentage caliber, i.e. ≤ 0.03 in the normalized caliber),
revision suggestions are generated at rule / threshold / sample / task
granularity, and a *new version* is produced rather than overwriting
the old conclusion (§3.5.2: "生成规则、阈值、样本或任务粒度修正建议，
并形成新版本而非覆盖旧结论").

§5.3.2 four-direction偏差归因 (deviation attribution):
  1. 样本代表性不足 (sample) — probe sample not covering high-freq
  2. 任务拆解粒度不当 (task) — atomic task granularity too coarse/fine
  3. 目标SLA设定偏差 (threshold/sla) — param source/interval issue
  4. HITL配置过强或过弱 (rule) — HITL intensity mismatch

Caliber separation note: 式(7) absolute gap (pp) vs §5.3.1 relative
deviation rate |T1−T0|/T0 are two calibers of the same retro
calibration — the former judges revision trigger by pp absolute value
(threshold 3pp), the latter judges representativeness by relative ratio
(thresholds 10%/30%).  They are NOT mixed.

Pure module — no FastAPI, repository, or LLM imports.  Parameters
marked "初始参考值" are Delphi priors pending M2-M4 empirical
calibration; they must not be presented as confirmed case results.
"""

from __future__ import annotations

from typing import Any, Optional

from .thresholds import RETRO_GAP_ACCEPTABLE_PCT

# ── §5.3.2 four-direction attribution (revision granularity) ─────────

# Revision suggestion granularity types (§3.5.2: rule/threshold/sample/task).
# Mapped to §5.3.2 four-direction attribution.
REVISION_GRANULARITY_RULE = "rule"        # HITL配置过强或过弱 → 调整HITL强度映射
REVISION_GRANULARITY_THRESHOLD = "threshold"  # 目标SLA设定偏差 → 重新校核参数
REVISION_GRANULARITY_SAMPLE = "sample"    # 样本代表性不足 → 补充边界样本
REVISION_GRANULARITY_TASK = "task"        # 任务拆解粒度不当 → 重新拆解原子任务

ALL_REVISION_GRANULARITIES: tuple[str, ...] = (
    REVISION_GRANULARITY_RULE,
    REVISION_GRANULARITY_THRESHOLD,
    REVISION_GRANULARITY_SAMPLE,
    REVISION_GRANULARITY_TASK,
)

# ── Gap direction interpretation (§3.5.2) ──────────────────────────────

GAP_DIRECTION_OVERESTIMATE = "probe_overestimate"  # gap > 0
GAP_DIRECTION_UNDERESTIMATE = "probe_underestimate"  # gap < 0
GAP_DIRECTION_ZERO = "no_deviation"  # gap == 0


# ═══════════════════════════════════════════════════════════════════════
# 式(7) retro gap
# ═══════════════════════════════════════════════════════════════════════


def compute_retro_gap(
    *,
    sla_act_probe: Optional[float] = None,
    sla_act_retro: Optional[float] = None,
    acceptable_pct: Optional[float] = None,
) -> dict[str, Any]:
    """Compute 式(7) gap = SLA_act,probe − SLA_act,retro (§3.5.2).

    Args:
        sla_act_probe: probe Actual SLA (T0, percentage points).
        sla_act_retro: retro/shadow-run Actual SLA (T1, percentage points).
        acceptable_pct: acceptable |gap| threshold in pp; defaults to
            ``RETRO_GAP_ACCEPTABLE_PCT`` (3.0 pp from §3.5.2).

    Returns:
        Dict with:

        * ``gap`` — float, SLA_act,probe − SLA_act,retro (pp).
        * ``abs_gap`` — float, |gap|.
        * ``direction`` — probe_overestimate | probe_underestimate |
          no_deviation.
        * ``relative_deviation_rate`` — |gap| / SLA_act,retro (§5.3.1
          caliber, for representativeness grading — NOT used for the
          revision trigger; the trigger uses abs_gap vs acceptable_pct).
        * ``needs_revision`` — bool, True when |gap| > acceptable_pct.
        * ``revision_suggestions`` — list of {granularity, action,
          direction, urgency}; non-empty when needs_revision.
        * ``new_version_required`` — bool, alias of needs_revision (§3.5.2:
          生成新版本而非覆盖旧结论).
        * ``caliber_note`` — str, 式(7) absolute-gap vs §5.3.1
          relative-rate caliber separation note.
        * ``missing`` — list of missing input fields.
    """
    threshold = (
        acceptable_pct
        if acceptable_pct is not None
        else RETRO_GAP_ACCEPTABLE_PCT
    )

    missing: list[str] = []
    if sla_act_probe is None:
        missing.append("sla_act_probe")
    if sla_act_retro is None:
        missing.append("sla_act_retro")

    if missing:
        return {
            "gap": None,
            "abs_gap": None,
            "direction": None,
            "relative_deviation_rate": None,
            "needs_revision": False,
            "revision_suggestions": [],
            "new_version_required": False,
            "acceptable_pct": threshold,
            "caliber_note": (
                "式(7) 绝对偏差 gap(pp) 判修正触发（阈值 3pp）；"
                "§5.3.1 相对偏差率 |T1-T0|/T0 判代表性分档（阈值 10%/30%），"
                "两者不混用。"
            ),
            "missing": missing,
        }

    probe = float(sla_act_probe)
    retro = float(sla_act_retro)

    gap = round(probe - retro, 2)
    abs_gap = round(abs(gap), 2)

    # Direction (§3.5.2: gap>0 probe overestimate, gap<0 underestimate)
    if gap > 0:
        direction = GAP_DIRECTION_OVERESTIMATE
    elif gap < 0:
        direction = GAP_DIRECTION_UNDERESTIMATE
    else:
        direction = GAP_DIRECTION_ZERO

    # Relative deviation rate (§5.3.1 caliber — representativeness, not trigger)
    rel_rate: Optional[float]
    if retro > 0:
        rel_rate = round(abs_gap / retro, 4)
    else:
        rel_rate = None  # retro=0 → undefined; avoid div-by-zero

    # Revision trigger: |gap| > acceptable_pct (式(7) absolute caliber)
    needs_revision = abs_gap > threshold

    # Revision suggestions (§3.5.2 + §5.3.2 four-direction attribution)
    suggestions: list[dict[str, Any]] = []
    if needs_revision:
        suggestions = _build_revision_suggestions(gap=gap, direction=direction)

    return {
        "gap": gap,
        "abs_gap": abs_gap,
        "direction": direction,
        "relative_deviation_rate": rel_rate,
        "needs_revision": needs_revision,
        "new_version_required": needs_revision,  # §3.5.2: new version, not overwrite
        "revision_suggestions": suggestions,
        "acceptable_pct": threshold,
        "caliber_note": (
            "式(7) 绝对偏差 gap(pp) 判修正触发（阈值 3pp）；"
            "§5.3.1 相对偏差率 |T1-T0|/T0 判代表性分档（阈值 10%/30%），"
            "两者不混用。"
        ),
        "missing": [],
    }


# ═══════════════════════════════════════════════════════════════════════
# Revision suggestion builder (§3.5.2 + §5.3.2 four-direction attribution)
# ═══════════════════════════════════════════════════════════════════════


def _build_revision_suggestions(
    *,
    gap: float,
    direction: str,
) -> list[dict[str, Any]]:
    """Build revision suggestions at rule/threshold/sample/task granularity.

    §5.3.2 four-direction attribution maps to §3.5.2 four granularity
    types.  All four directions are listed when revision is triggered;
    the ``urgency`` field reflects which directions are most likely
    given the gap direction:

      * probe_overestimate (gap>0, probe scored higher than retro) →
        sample representativeness is the primary suspect (probe sample
        too easy / not covering real-run high-freq cases), with task
        granularity and threshold (target SLA) as secondary.
      * probe_underestimate (gap<0, probe scored lower than retro) →
        threshold (target SLA too high) and rule (HITL too strict) are
        primary, with task granularity as secondary.

    Each suggestion: ``{granularity, action, direction, urgency}``.
    """
    suggestions: list[dict[str, Any]] = []

    if direction == GAP_DIRECTION_OVERESTIMATE:
        # gap>0: probe overestimate — probe sample too easy
        suggestions.append({
            "granularity": REVISION_GRANULARITY_SAMPLE,
            "action": (
                "补充边界样本与高频情形样本，扩大探针覆盖度"
                "（探针高估，真实运行中存在未覆盖的高频情形）"
            ),
            "direction": direction,
            "urgency": "high",
        })
        suggestions.append({
            "granularity": REVISION_GRANULARITY_TASK,
            "action": "重新拆解原子任务，调整粒度至可测试层面",
            "direction": direction,
            "urgency": "medium",
        })
        suggestions.append({
            "granularity": REVISION_GRANULARITY_THRESHOLD,
            "action": "重新校核参数来源，扩大敏感性分析区间（目标 SLA 可能偏低）",
            "direction": direction,
            "urgency": "medium",
        })
        suggestions.append({
            "granularity": REVISION_GRANULARITY_RULE,
            "action": "复核 HITL 强度映射是否过弱导致复核未暴露问题",
            "direction": direction,
            "urgency": "low",
        })
    elif direction == GAP_DIRECTION_UNDERESTIMATE:
        # gap<0: probe underestimate — target SLA too high or HITL too strict
        suggestions.append({
            "granularity": REVISION_GRANULARITY_THRESHOLD,
            "action": "重新校核目标 SLA 参数来源，扩大敏感性分析区间（目标 SLA 可能偏高）",
            "direction": direction,
            "urgency": "high",
        })
        suggestions.append({
            "granularity": REVISION_GRANULARITY_RULE,
            "action": "调整 HITL 强度映射（L3 mandatory 不可降级，复核其他档位是否过严）",
            "direction": direction,
            "urgency": "high",
        })
        suggestions.append({
            "granularity": REVISION_GRANULARITY_TASK,
            "action": "重新拆解原子任务，调整粒度至可测试层面",
            "direction": direction,
            "urgency": "medium",
        })
        suggestions.append({
            "granularity": REVISION_GRANULARITY_SAMPLE,
            "action": "复核探针样本是否过难，补充常规情形样本平衡覆盖度",
            "direction": direction,
            "urgency": "low",
        })
    else:
        # gap==0 should not trigger needs_revision, but guard anyway
        suggestions.append({
            "granularity": REVISION_GRANULARITY_SAMPLE,
            "action": "偏差为零，无需修正（仅作记录）",
            "direction": direction,
            "urgency": "none",
        })

    return suggestions
