"""P3-3 trust-calibration — misuse/disuse detection (§3.4.2).

Thesis §3.4.2 (Lee&See 2004, DOI 10.1518/hfes.46.1.50.30392): trust
calibration is the theoretical lens — not just an engineering operation
— for detecting two failure modes:

  * **misuse (过度依赖/橡皮图章)**: raters rubber-stamp model outputs.
    Signal: divergence_rate < 5% (suspiciously low) → trigger audit
    sampling.  Also: adoption_rate > 95% → suspected misuse.
  * **disuse (依赖不足/价值未兑现)**: raters reject model outputs
    wholesale.  Signal: divergence_rate > 30% → possible disuse or
    rubric ambiguity → recalibrate.  Also: adoption_rate < 50% →
    suspected disuse → technical review.

  * **blind-sample injection**: quarterly 5-10% known-error samples
    (including fatal errors) → hit_rate < 90% → skill degradation →
    retraining.

This Sub-agent takes the probe-scorer's divergence data + human
correction records and produces the trust-calibration verdict.

Mounted on the existing Stage 3 Skill — NOT a standalone 9-Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── Trust calibration thresholds (§3.4.2) ─────────────────────────────

DIVERGENCE_MISUSE_MAX: float = 0.05   # < 5% → misuse suspected
DIVERGENCE_DISUSE_MIN: float = 0.30  # > 30% → disuse or rubric ambiguity
DIVERGENCE_NORMAL_LOW: float = 0.05
DIVERGENCE_NORMAL_HIGH: float = 0.30

ADOPTION_MISUSE_MIN: float = 0.95   # > 95% → misuse suspected
ADOPTION_DISUSE_MAX: float = 0.50   # < 50% → disuse suspected

BLIND_SAMPLE_MIN_SHARE: float = 0.05  # 5% of samples
BLIND_SAMPLE_MAX_SHARE: float = 0.10  # 10% of samples
BLIND_SAMPLE_HIT_TARGET: float = 0.90  # < 90% → skill degradation


@dataclass
class TrustCalibrationResult:
    """Output of the trust-calibration Sub-agent.

    Attributes:
        divergence_rate: fraction of divergent items (from probe-scorer).
        adoption_rate: fraction of samples human left unmodified.
        blind_sample_hit_rate: fraction of injected known-error samples
            correctly flagged.
        misuse_suspect: bool — True when divergence < 5% or adoption > 95%.
        disuse_suspect: bool — True when divergence > 30% or adoption < 50%.
        skill_degradation: bool — True when blind-sample hit < 90%.
        audit_sampling_required: bool — True when misuse suspected.
        rubric_recalibration_required: bool — True when disuse or
            divergence > 30%.
        retraining_required: bool — True when skill degradation detected.
        trust_verdict: "calibrated" | "misuse_suspected" |
            "disuse_suspected" | "skill_degradation".
        review_status: "complete" | "partial" | "empty".
        extraction_notes: human-readable notes.
    """

    divergence_rate: float = 0.0
    adoption_rate: Optional[float] = None
    blind_sample_hit_rate: Optional[float] = None
    misuse_suspect: bool = False
    disuse_suspect: bool = False
    skill_degradation: bool = False
    audit_sampling_required: bool = False
    rubric_recalibration_required: bool = False
    retraining_required: bool = False
    trust_verdict: str = "calibrated"
    review_status: str = "empty"
    extraction_notes: list[str] = field(default_factory=list)


def calibrate_trust(
    *,
    rubric_scores: list[dict] | None = None,
    divergent_items: list[dict] | None = None,
    human_corrections: list[dict] | None = None,
    blind_samples: list[dict] | None = None,
    divergence_rate: float | None = None,
) -> TrustCalibrationResult:
    """Detect misuse/disuse/skill-degradation (§3.4.2).

    Args:
        rubric_scores: merged rubric scores (for total count).
        divergent_items: from probe-scorer (items with grade-diff ≥ 1 tier).
        human_corrections: per-sample records {sample_id, modified(bool)}.
        blind_samples: injected known-error records {sample_id, hit(bool)}.
        divergence_rate: pre-computed divergence rate (if not provided,
            computed from divergent_items / rubric_scores).

    Returns:
        TrustCalibrationResult with misuse/disuse/degradation flags.
    """
    notes: list[str] = []

    # ── Divergence rate ──
    if divergence_rate is None:
        total = len(rubric_scores or [])
        div_count = len(divergent_items or [])
        div_rate = round(div_count / total, 4) if total else 0.0
    else:
        div_rate = divergence_rate

    # ── Adoption rate (model outputs left unmodified by humans) ──
    adoption_rate: Optional[float] = None
    if human_corrections:
        total = len(human_corrections)
        unmodified = sum(1 for c in human_corrections if not c.get("modified", False))
        adoption_rate = round(unmodified / total, 4) if total else None

    # ── Blind-sample hit rate ──
    blind_hit_rate: Optional[float] = None
    if blind_samples:
        total = len(blind_samples)
        hits = sum(1 for s in blind_samples if s.get("hit", False))
        blind_hit_rate = round(hits / total, 4) if total else None

    # ── Misuse detection ──
    misuse = False
    misuse_reasons: list[str] = []
    if div_rate < DIVERGENCE_MISUSE_MAX:
        misuse = True
        misuse_reasons.append(f"分歧率 {div_rate:.2%} < {DIVERGENCE_MISUSE_MAX:.0%}")
    if adoption_rate is not None and adoption_rate > ADOPTION_MISUSE_MIN:
        misuse = True
        misuse_reasons.append(f"采纳率 {adoption_rate:.2%} > {ADOPTION_MISUSE_MIN:.0%}")

    # ── Disuse detection ──
    disuse = False
    disuse_reasons: list[str] = []
    if div_rate > DIVERGENCE_DISUSE_MIN:
        disuse = True
        disuse_reasons.append(f"分歧率 {div_rate:.2%} > {DIVERGENCE_DISUSE_MIN:.0%}")
    if adoption_rate is not None and adoption_rate < ADOPTION_DISUSE_MAX:
        disuse = True
        disuse_reasons.append(f"采纳率 {adoption_rate:.2%} < {ADOPTION_DISUSE_MAX:.0%}")

    # ── Skill degradation ──
    degradation = False
    if blind_hit_rate is not None and blind_hit_rate < BLIND_SAMPLE_HIT_TARGET:
        degradation = True
        notes.append(
            f"盲样命中率 {blind_hit_rate:.2%} < {BLIND_SAMPLE_HIT_TARGET:.0%}；"
            f"判定技能退化，触发再培训。"
        )

    # ── Trust verdict ──
    if degradation:
        verdict = "skill_degradation"
    elif misuse:
        verdict = "misuse_suspected"
    elif disuse:
        verdict = "disuse_suspected"
    else:
        verdict = "calibrated"

    # ── Action flags ──
    audit_sampling = misuse
    recalibration = disuse or (div_rate > DIVERGENCE_DISUSE_MIN)
    retraining = degradation

    if misuse:
        notes.append("疑似 misuse（橡皮图章）：" + "；".join(misuse_reasons) + "。触发抽检。")
    if disuse:
        notes.append("疑似 disuse（价值未兑现）：" + "；".join(disuse_reasons) + "。触发量规校准或技术复核。")

    # ── Review status ──
    if (divergence_rate is not None or rubric_scores) and verdict != "calibrated":
        review_status = "partial"
    elif divergence_rate is not None or rubric_scores:
        review_status = "complete"
    else:
        review_status = "empty"

    return TrustCalibrationResult(
        divergence_rate=div_rate,
        adoption_rate=adoption_rate,
        blind_sample_hit_rate=blind_hit_rate,
        misuse_suspect=misuse,
        disuse_suspect=disuse,
        skill_degradation=degradation,
        audit_sampling_required=audit_sampling,
        rubric_recalibration_required=recalibration,
        retraining_required=retraining,
        trust_verdict=verdict,
        review_status=review_status,
        extraction_notes=notes,
    )
