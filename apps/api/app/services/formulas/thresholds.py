"""Threshold constants — single source of truth for risk-graded thresholds.

All values correspond to thesis §3.3-§3.5 formula parameters.  Values
marked "initial reference value" are Delphi priors pending M2-M4
empirical calibration; they must not be presented as confirmed case
results (per CLAUDE.md "engineering capability cannot replace research
milestone completion").
"""

from __future__ import annotations

from typing import NamedTuple


# ── 式(5) hard-constraint thresholds (§3.5.2) ────────────────────────

# General error rate ceiling e_crit_max(R): L1=0.15, L2=0.10, L3=0.05.
# "风险越高、硬约束越严" cascade.
E_CRIT_MAX_BY_RISK: dict[str, float] = {
    "L1": 0.15,
    "L2": 0.10,
    "L3": 0.05,
}

# Overall audit completeness floor A_audit_min(R): L1=0.70, L2=0.85, L3=0.95.
A_AUDIT_MIN_BY_RISK: dict[str, float] = {
    "L1": 0.70,
    "L2": 0.85,
    "L3": 0.95,
}


# ── 式(1) implementation-tax ρ(H) cascade (§3.3.2) ───────────────────

# Review ratio ρ_review(H) by HITL intensity.
# none=0 (no review), standard=0.5 (sample review),
# strict=1.0 (full review), mandatory=1.0 (full + second review).
RHO_H_BY_HITL: dict[str, float] = {
    "none": 0.0,
    "standard": 0.5,
    "strict": 1.0,
    "mandatory": 1.0,
}


# ── 式(3) target SLA floor (§3.3.3) ───────────────────────────────────

# Comprehensive SLA floor by risk level (matches alignment_service
# TARGET_SLA_FLOOR_BY_RISK for backward compatibility).
SLA_FLOOR_BY_RISK: dict[str, float] = {
    "L1": 85.0,
    "L2": 90.0,
    "L3": 95.0,
}

# Per-dimension SLA floor SLA_floor,d(R): qual/eff/gov.
# 初始参考值，待 M2-M4 实证标定 — Delphi prior pending calibration.
SLA_FLOOR_BY_DIM_BY_RISK: dict[str, dict[str, float]] = {
    "L1": {"qual": 85.0, "eff": 80.0, "gov": 85.0},
    "L2": {"qual": 90.0, "eff": 85.0, "gov": 90.0},
    "L3": {"qual": 95.0, "eff": 90.0, "gov": 95.0},
}

# Net-value disaster floor V_min(R): must be significantly below 0 to
# preserve discriminative space (§3.3.3, §3.5.2).
# 初始参考值，待 M2-M4 实证标定.
V_MIN_BY_RISK: dict[str, float] = {
    "L1": -30.0,
    "L2": -50.0,
    "L3": -80.0,
}

# Net-value ceiling V_max: Delphi upper-quartile prior.
# 初始参考值，待 M2-M4 实证标定.
V_MAX_DEFAULT: float = 200.0

# Per-dimension allocation coefficient α_d (§3.3.3 式(3)).
# 初始参考值，待德尔菲标定.
ALPHA_D_DEFAULT: dict[str, float] = {
    "qual": 2.0,
    "eff": 4.0,
    "gov": 3.0,
}


# ── 式(3a)/(4) three-dimension weights w_d (§3.3.3, §3.4.4) ──────────

# w_d for target SLA aggregation and actual SLA aggregation (shared).
# L3 governance weight w_gov ≥ 0.3 (§3.4.4).
W_D_DEFAULT: dict[str, float] = {
    "qual": 0.4,
    "eff": 0.3,
    "gov": 0.3,
}


# ── §3.2.4 audit fields (8-item enumeration for loan-post scenario) ────

class AuditField(NamedTuple):
    """A structured audit-trail field (§3.2.4)."""
    field_id: str
    name: str
    required: bool
    critical: bool  # critical fields require zero-missing (100% completeness)


# Loan-post scenario: 8 fields. AML scenarios add a 9th (regulatory
# reporting flow). The old 4-item version is a historical draft, not
# the current standard.
CRITICAL_AUDIT_FIELDS: tuple[AuditField, ...] = (
    AuditField("af-1", "输入材料版本", required=True, critical=True),
    AuditField("af-2", "AI输出", required=True, critical=True),
    AuditField("af-3", "复核人及复核意见", required=True, critical=True),
    AuditField("af-4", "时间戳", required=True, critical=True),
    AuditField("af-5", "推理路径", required=True, critical=True),
    AuditField("af-6", "阈值触发记录", required=True, critical=True),
    AuditField("af-7", "AI生成内容显著标识", required=True, critical=True),
    AuditField("af-8", "日志保存期限", required=True, critical=True),
)

# Field names requiring the "explicit_watermark" enum value (§3.2.4).
WATERMARK_FIELD_NAME: str = "AI生成内容显著标识"

# Field names requiring the "business_lifetime" enum value (§3.2.4).
RETENTION_FIELD_NAME: str = "日志保存期限"


# ── 式(7) retrospective gap threshold (§3.5.2) ──────────────────────

# Acceptable retrospective gap: |gap| ≤ 3 percentage points (§3.5.2 式(7)).
RETRO_GAP_ACCEPTABLE_PCT: float = 3.0


# ── 式(6) decision threshold (§3.5.2) ─────────────────────────────────

# gap_to_target_pct = Actual SLA − Target SLA (pp).
# Positive = meets/exceeds target; negative = falls short.
ACCEPTABLE_GAP_PCT: float = 5.0  # gap ≥ -5 is "within tolerance" for the old single-dim path
REJECTION_GAP_PCT: float = -20.0  # gap < -20 is "fundamental mismatch"


# ── Gap grading thresholds (§3.4.4) ────────────────────────────────────

# Relative gap = |Δ_sla| / SLA_tgt, as a fraction (0.05 = 5%).
GAP_GRADE_THRESHOLDS: dict[str, float] = {
    "micro": 0.05,     # ≤ 5%
    "significant": 0.10,  # 5% – 10%
    "large": 0.20,     # 10% – 20%
    # > 20% → severe
}
