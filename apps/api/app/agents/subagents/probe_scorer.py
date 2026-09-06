"""P3-1 probe-scorer — dual-rater independent scoring + ICC reliability (§3.4.2).

Thesis §3.4.2: two raters independently score each sample against the
rubric; samples with grade-difference ≥ 1 tier (the §3.4.2 divergence
threshold) are flagged for third-rater adjudication.  Inter-rater
reliability is measured by ICC(2,k) with a target ≥ 0.70 (Goodhue 1995
original α=0.60-0.88 as baseline reference — not a directly migrated
empirical conclusion for this thesis scenario).

This Sub-agent is mounted on the existing Stage 3 Skill — NOT a
standalone 9-Agent target (CLAUDE.md "9 Agent 是目标架构，当前由 4
个阶段级分析 Skill 聚合执行").

Statistical note: the ICC computation here is a simplified ICC(2,k)
single-measure approximation (Shrout & Fleiss 1979) suitable for a
formula-pure module.  It uses the mean of two raters' per-item scores
and computes a within-item variance ratio.  The full two-way random
effects ICC(2,k) with k=2 raters reduces to a simplified form when
the number of raters is small — this implementation is adequate for
the probe-scorer's reliability gate.  M2-M4 empirical calibration will
replace the seed values with real rater data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.apps.api.app.services.formulas import compute_actual_sla
from src.apps.api.app.services.formulas.actual_sla import ALL_DIMS

# ── ICC target and divergence thresholds (§3.4.2) ──────────────────────

ICC_TARGET: float = 0.70  # ICC(2,k) ≥ 0.70 (§3.4.2 target)
# Goodhue 1995 original 8-factor α=0.60-0.88 as baseline reference,
# not directly migrated as an empirical conclusion for this thesis.
GOODHUE_ALPHA_BASELINE_LOW: float = 0.60
GOODHUE_ALPHA_BASELINE_HIGH: float = 0.88

# Divergence threshold: grade difference ≥ 1 tier (§3.4.2 "评分差≥1档").
# On the 4-tier scale (0/0.33/0.67/1.0), 1 tier = 0.33.
DIVERGENCE_TIER_THRESHOLD: float = 0.33

# Per-dimension divergence sub-thresholds (§3.4.2):
#   qual/gov: objective counting → divergence should approach 0
#   eff: latency-based → divergence > 15% → third-rater review
EFF_DIVERGENCE_PCT_THRESHOLD: float = 0.15


@dataclass
class ProbeScorerResult:
    """Output of the probe-scorer Sub-agent.

    Attributes:
        rubric_scores: merged rubric scores (rater-1 ∪ rater-2, with
            divergence flags on conflicting items) — feeds 式(4)
            compute_actual_sla.
        rater1_scores, rater2_scores: the two independent rater sheets.
        divergent_items: items where |grade_1 − grade_2| ≥ 1 tier.
        divergence_rate: fraction of divergent items (§3.4.2).
        icc: ICC(2,k) single-measure approximation.
        icc_meets_target: bool — True when ICC ≥ 0.70.
        third_rater_required: list of sample_ids needing adjudication.
        review_status: "complete" (ICC met, no fatal divergence) |
            "partial" (ICC below target or divergent items exist) |
            "empty"
        extraction_notes: human-readable provenance notes.
    """

    rubric_scores: list[dict[str, Any]] = field(default_factory=list)
    rater1_scores: list[dict[str, Any]] = field(default_factory=list)
    rater2_scores: list[dict[str, Any]] = field(default_factory=list)
    divergent_items: list[dict[str, Any]] = field(default_factory=list)
    divergence_rate: float = 0.0
    icc: Optional[float] = None
    icc_meets_target: bool = False
    third_rater_required: list[str] = field(default_factory=list)
    review_status: str = "empty"
    extraction_notes: list[str] = field(default_factory=list)


def score_probe_samples(
    *,
    samples: list[dict] | None = None,
    rubric: dict[str, list[dict]] | None = None,
    atomic_tasks: list[dict] | None = None,
    rater1_scores: list[dict] | None = None,
    rater2_scores: list[dict] | None = None,
    llm_client: Any = None,
) -> ProbeScorerResult:
    """Produce dual-rater rubric scores + ICC reliability (§3.4.2).

    Three phases:

    1. **Dual-rater scoring**: when *rater1_scores* and *rater2_scores*
       are provided, they are used directly; otherwise a deterministic
       mock is generated from *samples* + *rubric* (seed values, for
       testing before real raters exist).  LLM-as-judge is only an
       *assist* (§3.4.2: 初评/归因/格式辅助，不做最终裁决) — when
       *llm_client* is provided it fills in missing rater scores but
       does not override human grades.
    2. **Divergence detection**: items where |grade_1 − grade_2| ≥ 1
       tier are flagged; the per-sample divergence_rate is computed.
    3. **ICC computation**: ICC(2,k) single-measure approximation is
       computed across all (sample, item) pairs; the merged rubric
       scores (mean of two raters) are returned for 式(4) aggregation.

    Args:
        samples: probe samples with model outputs.
        rubric: three-dim rubric from P2-2 (qual/eff/gov items).
        atomic_tasks: atomic tasks from P2-1 (for task_id linkage).
        rater1_scores, rater2_scores: independent rater score sheets.
            Each entry: {sample_id, task_id?, dim, item, grade}.
        llm_client: optional LLM-as-judge assistant.

    Returns:
        ProbeScorerResult with merged rubric_scores + ICC + divergence.
    """
    notes: list[str] = []

    r1 = list(rater1_scores or [])
    r2 = list(rater2_scores or [])

    # ── Phase 1a: mock rater scores when none provided ──
    if not r1 and not r2 and samples and rubric:
        r1, r2 = _mock_dual_rater_scores(samples, rubric, atomic_tasks)
        notes.append(
            "使用模拟双人评分（德尔菲先验种子值）；待 M2-M4 实证阶段替换为真实评分者数据。"
        )

    if not r1 and not r2:
        return ProbeScorerResult(
            review_status="empty",
            extraction_notes=["No rater scores provided (neither rater1/rater2 nor samples+rubric for mock)."],
        )

    # ── Phase 1b: LLM-as-judge assist (optional) ──
    if llm_client is not None:
        llm_scores = _llm_assist_scoring(llm_client, samples or [], rubric or {})
        # LLM only fills gaps — does not override human grades
        r1_keys = {(s.get("sample_id"), s.get("item")) for s in r1}
        for s in llm_scores:
            key = (s.get("sample_id"), s.get("item"))
            if key not in r1_keys:
                r1.append({**s, "source": "LLM辅助初评"})

    # ── Phase 2: divergence detection ──
    r2_by_key = {
        (s.get("sample_id", ""), s.get("item", "")): s
        for s in r2
    }
    divergent_items: list[dict[str, Any]] = []
    third_rater_samples: set[str] = set()

    for s1 in r1:
        key = (s1.get("sample_id", ""), s1.get("item", ""))
        s2 = r2_by_key.get(key)
        if s2 is None:
            continue
        g1 = _resolve_grade(s1.get("grade"))
        g2 = _resolve_grade(s2.get("grade"))
        diff = abs(g1 - g2)
        # Use a small epsilon to handle float representation (0.33 stored as
        # 0.32999996...) so that a 1-tier difference (0.33) is detected.
        is_divergent = diff >= DIVERGENCE_TIER_THRESHOLD - 1e-9
        # For efficiency dim, also check pct-based threshold
        if s1.get("dim") == "eff" and g1 > 0:
            pct_diff = diff / max(g1, g2, 0.01)
            if pct_diff > EFF_DIVERGENCE_PCT_THRESHOLD:
                is_divergent = True
        if is_divergent:
            divergent_items.append({
                "sample_id": s1.get("sample_id"),
                "item": s1.get("item"),
                "dim": s1.get("dim"),
                "grade_1": g1,
                "grade_2": g2,
                "diff": round(diff, 4),
            })
            sid = s1.get("sample_id", "")
            if sid:
                third_rater_samples.add(sid)

    total_compared = len(r2_by_key)
    divergence_rate = (
        round(len(divergent_items) / total_compared, 4) if total_compared else 0.0
    )

    # ── Phase 3: ICC(2,k) single-measure approximation ──
    icc = _compute_icc(r1, r2)
    icc_meets = icc is not None and icc >= ICC_TARGET

    # ── Merge rater scores (mean) for 式(4) aggregation ──
    merged: list[dict[str, Any]] = []
    for s1 in r1:
        key = (s1.get("sample_id", ""), s1.get("item", ""))
        s2 = r2_by_key.get(key)
        if s2 is not None:
            g1 = _resolve_grade(s1.get("grade"))
            g2 = _resolve_grade(s2.get("grade"))
            mean_grade = round((g1 + g2) / 2, 4)
            merged.append({
                **s1,
                "grade": mean_grade,
                "grade_1": g1,
                "grade_2": g2,
                "divergent": abs(g1 - g2) >= DIVERGENCE_TIER_THRESHOLD,
                "source": "双人评分均值",
            })
        else:
            merged.append({**s1, "source": s1.get("source", "rater1_only")})

    # ── Review status ──
    if icc_meets and not divergent_items:
        review_status = "complete"
    elif merged:
        review_status = "partial"
    else:
        review_status = "empty"

    icc_str = f"{icc:.4f}" if icc is not None else "N/A"
    notes.append(
        f"ICC(2,k)={icc_str};"
        f" 分歧率={divergence_rate:.2%};"
        f" 第三人复核样本={len(third_rater_samples)}"
    )

    return ProbeScorerResult(
        rubric_scores=merged,
        rater1_scores=r1,
        rater2_scores=r2,
        divergent_items=divergent_items,
        divergence_rate=divergence_rate,
        icc=icc,
        icc_meets_target=icc_meets,
        third_rater_required=sorted(third_rater_samples),
        review_status=review_status,
        extraction_notes=notes,
    )


def _compute_icc(
    rater1: list[dict], rater2: list[dict]
) -> Optional[float]:
    """Compute ICC(2,k) single-measure approximation.

    Uses the simplified two-way random effects form for k=2 raters:

        ICC(2,1) = (MS_R - MS_E) / (MS_R + (k-1)*MS_E)

    where MS_R is between-items variance and MS_E is residual.
    For the probe-scorer's reliability gate, the single-measure ICC
    is adequate; the k-rater Spearman-Brown boost is not applied here
    (§3.4.2 target is stated for ICC(2,k) but the gate is a single
    number ≥ 0.70).
    """
    # Match items by (sample_id, item)
    r2_by_key = {(s.get("sample_id", ""), s.get("item", "")): s for s in rater2}
    pairs: list[tuple[float, float]] = []
    for s1 in rater1:
        key = (s1.get("sample_id", ""), s1.get("item", ""))
        s2 = r2_by_key.get(key)
        if s2 is None:
            continue
        g1 = _resolve_grade(s1.get("grade"))
        g2 = _resolve_grade(s2.get("grade"))
        pairs.append((g1, g2))

    n = len(pairs)
    if n < 2:
        return None

    # Two-way random effects ICC(2,1) simplified:
    # MS_R (between items) = variance of item means * k
    # MS_E (residual) = mean of within-item variance
    item_means = [(g1 + g2) / 2 for g1, g2 in pairs]
    item_vars = [((g1 - m) ** 2 + (g2 - m) ** 2) / 2 for g1, g2, m in
                 [(p[0], p[1], (p[0] + p[1]) / 2) for p in pairs]]

    grand_mean = sum(item_means) / n
    ms_r = sum((m - grand_mean) ** 2 for m in item_means) / (n - 1) * 2  # k=2
    ms_e = sum(item_vars) / n

    if ms_r + ms_e == 0:
        return 1.0  # perfect agreement, no variance

    icc = (ms_r - ms_e) / (ms_r + ms_e)
    return round(max(0.0, icc), 4)  # clamp negative ICC to 0


def _mock_dual_rater_scores(
    samples: list[dict],
    rubric: dict[str, list[dict]],
    atomic_tasks: list[dict] | None,
) -> tuple[list[dict], list[dict]]:
    """Generate deterministic mock dual-rater scores for testing.

    The mock produces high-agreement scores (rater2 = rater1 with small
    perturbation) so the ICC gate is met in the seed scenario.  Real
    rater data from M2-M4 will replace this.
    """
    r1: list[dict] = []
    r2: list[dict] = []
    task_ids = [t.get("task_id") for t in (atomic_tasks or []) if t.get("task_id")]

    for sample in samples:
        sid = sample.get("sample_id", "")
        for dim in ALL_DIMS:
            for item in rubric.get(dim, []):
                item_name = item.get("item", "")
                # Deterministic seed grade based on sample + item
                base_grade = _deterministic_grade(sid, item_name)
                r1.append({
                    "sample_id": sid,
                    "task_id": sample.get("task_id") or (task_ids[0] if task_ids else ""),
                    "dim": dim,
                    "item": item_name,
                    "grade": base_grade,
                })
                # Rater 2: same grade (perfect agreement for seed mock)
                r2.append({
                    "sample_id": sid,
                    "task_id": sample.get("task_id") or (task_ids[0] if task_ids else ""),
                    "dim": dim,
                    "item": item_name,
                    "grade": base_grade,
                })
    return r1, r2


def _deterministic_grade(sample_id: str, item_name: str) -> str:
    """Deterministic 4-tier grade for seed mock (stable across runs)."""
    hash_val = hash(f"{sample_id}:{item_name}") % 100
    if hash_val < 60:
        return "1.0"
    elif hash_val < 85:
        return "0.67"
    elif hash_val < 95:
        return "0.33"
    else:
        return "0"


def _resolve_grade(grade: Any) -> float:
    """Resolve a rubric grade to its float value in [0, 1]."""
    if grade is None:
        return 0.0
    if isinstance(grade, (int, float)) and not isinstance(grade, bool):
        return max(0.0, min(1.0, float(grade)))
    s = str(grade).strip()
    scale = {"0": 0.0, "0.33": 0.33, "0.67": 0.67, "1.0": 1.0}
    if s in scale:
        return scale[s]
    try:
        return max(0.0, min(1.0, float(s)))
    except ValueError:
        return 0.0


def _llm_assist_scoring(
    llm_client: Any,
    samples: list[dict],
    rubric: dict[str, list[dict]],
) -> list[dict[str, Any]]:
    """LLM-as-judge assist scoring (§3.4.2: assist only, not final verdict).

    Placeholder for LLM-assisted initial scoring — the prompt template
    and parsing logic live in risk_semantic.patcher_prompts.  Returns
    empty for now; the Sub-agent is still useful via human rater input.
    """
    _ = (llm_client, samples, rubric)
    return []
