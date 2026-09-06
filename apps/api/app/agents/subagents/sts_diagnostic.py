"""P4-4 sts-diagnostic — STS six-variable social-subsystem diagnostic (§3.2.1).

Thesis §3.2.1 STS 六变量社会子系统诊断维度 (Trist&Bamforth 1951,
Emery 1959): the six variables are:

  1. 自律性 (autonomy)
  2. 责任 (responsibility)
  3. 任务整体性 (task wholeness)
  4. 多样性 (variety)
  5. 社会支持 (social support)
  6. 边界跨越 (boundary spanning)

§3.2.1 判据: L3 scenarios must confirm — via business/risk/compliance
role interviews — that 自律性, 责任, 社会支持 have no major defects
before proceeding to step 2.  Major defects → degrade to "social-
subsystem defect scenario" → step 2 must strengthen social-subsystem
design.

**This is a placeholder Sub-agent** (§3.2.1: 访谈输入待 M1).  The six
variables are *qualitative diagnostic dimensions pending M1 interview
填充* — no numeric thresholds are pre-filled (the original numeric
thresholds 自律性≥4/责任=5/社会支持≥4 lack interview evidence and have
been changed to qualitative criteria).  This agent reserves the field
structure and interface; actual diagnostic values come from M1
interviews and are not system-generated.

Mounted on the existing Stage 1 Skill — NOT a standalone 9-Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── STS six variables (§3.2.1) ─────────────────────────────────────────

STS_VAR_AUTONOMY = "自律性"
STS_VAR_RESPONSIBILITY = "责任"
STS_VAR_TASK_WHOLENESS = "任务整体性"
STS_VAR_VARIETY = "多样性"
STS_VAR_SOCIAL_SUPPORT = "社会支持"
STS_VAR_BOUNDARY_SPANNING = "边界跨越"

STS_SIX_VARS: tuple[str, ...] = (
    STS_VAR_AUTONOMY,
    STS_VAR_RESPONSIBILITY,
    STS_VAR_TASK_WHOLENESS,
    STS_VAR_VARIETY,
    STS_VAR_SOCIAL_SUPPORT,
    STS_VAR_BOUNDARY_SPANNING,
)

# §3.2.1 判据: L3 场景须在自律性、责任、社会支持三个维度无重大缺陷
STS_L3_CRITICAL_VARS: tuple[str, ...] = (
    STS_VAR_AUTONOMY,
    STS_VAR_RESPONSIBILITY,
    STS_VAR_SOCIAL_SUPPORT,
)

# Major-defect severity levels (§3.2.1 定性判据, not numeric thresholds)
DEFECT_NONE = "无缺陷"
DEFECT_MINOR = "轻微缺陷"
DEFECT_MAJOR = "重大缺陷"


@dataclass
class STSDiagnosticResult:
    """Output of the STS-diagnostic Sub-agent (§3.2.1 placeholder).

    Attributes:
        sts_six_vars: dict of six STS variables → {defect_level, notes}.
            Values are *None* until M1 interview data is provided — this
            agent reserves the field structure but does NOT pre-fill
            numeric thresholds (§3.2.1: 定性诊断维度，待 M1 访谈填值).
        major_defects: list of {variable, defect_level, notes} for
            variables with major defects.  Empty when no major defects.
        l3_critical_vars_pass: bool — True when all three L3-critical
            variables (自律性/责任/社会支持) have no major defects.
            None when interview data not yet provided.
        social_subsystem_defect: bool — True when major defects exist →
            §3.2.1 "降为社会子系统缺陷场景，须在步骤 2 补强社会子系统设计".
        interview_pending: bool — True when M1 interview data not yet
            provided (placeholder mode).
        review_status: "complete" | "partial" | "empty".
        extraction_notes: human-readable provenance notes.
    """

    sts_six_vars: dict[str, dict[str, Any]] = field(default_factory=dict)
    major_defects: list[dict[str, Any]] = field(default_factory=list)
    l3_critical_vars_pass: Optional[bool] = None
    social_subsystem_defect: bool = False
    interview_pending: bool = True
    review_status: str = "empty"
    extraction_notes: list[str] = field(default_factory=list)


def diagnose_sts_subsystem(
    *,
    risk_level: Optional[str] = None,
    interview_data: dict[str, Any] | None = None,
) -> STSDiagnosticResult:
    """Diagnose the STS six-variable social subsystem (§3.2.1).

    **Placeholder mode**: when *interview_data* is None or empty, the
    agent reserves the six-variable field structure with all values set
    to None (待 M1 访谈填值) — no numeric thresholds are pre-filled.

    When *interview_data* is provided (post-M1), each variable's
    ``defect_level`` (无缺陷/轻微缺陷/重大缺陷) is read from the
    interview data and the §3.2.1 判据 is applied:

      * L3 scenarios: 自律性/责任/社会支持 三个维度无重大缺陷 → pass
      * Any major defect in critical vars → social_subsystem_defect=True
        → step 2 must strengthen social-subsystem design

    Args:
        risk_level: L1/L2/L3 — determines which critical vars apply.
        interview_data: dict mapping STS variable names to
            {defect_level, notes}.  None/empty → placeholder mode.

    Returns:
        STSDiagnosticResult with six-var structure + major defects.
    """
    notes: list[str] = []

    # ── Initialize six-var structure with None (placeholder) ──
    sts_six_vars: dict[str, dict[str, Any]] = {
        var: {"defect_level": None, "notes": ""}
        for var in STS_SIX_VARS
    }

    # ── Placeholder mode: no interview data ──
    if not interview_data:
        notes.append(
            "§3.2.1 STS 六变量为定性诊断维度，待 M1 访谈填值；"
            "当前为预留字段结构，不预填数值阈值。"
        )
        return STSDiagnosticResult(
            sts_six_vars=sts_six_vars,
            interview_pending=True,
            review_status="empty",
            extraction_notes=notes,
        )

    # ── Fill from interview data (post-M1) ──
    major_defects: list[dict[str, Any]] = []
    for var in STS_SIX_VARS:
        entry = interview_data.get(var, {})
        defect_level = entry.get("defect_level", DEFECT_NONE)
        var_notes = entry.get("notes", "")
        sts_six_vars[var] = {
            "defect_level": defect_level,
            "notes": var_notes,
        }
        if defect_level == DEFECT_MAJOR:
            major_defects.append({
                "variable": var,
                "defect_level": defect_level,
                "notes": var_notes,
            })

    # ── §3.2.1 判据: L3 critical vars (自律性/责任/社会支持) ──
    l3_pass: Optional[bool] = None
    social_defect = False
    if risk_level == "L3":
        critical_major = [
            md for md in major_defects
            if md["variable"] in STS_L3_CRITICAL_VARS
        ]
        l3_pass = len(critical_major) == 0
        social_defect = len(critical_major) > 0
        if social_defect:
            notes.append(
                "§3.2.1 判据：L3 场景 "
                + "、".join(md["variable"] for md in critical_major)
                + " 存在重大缺陷，降为社会子系统缺陷场景，"
                "须在步骤 2 补强社会子系统设计。"
            )
        else:
            notes.append(
                "§3.2.1 判据：L3 场景自律性/责任/社会支持三个维度无重大缺陷，"
                "可继续步骤 2。"
            )

    # ── Review status ──
    if major_defects:
        review_status = "partial"
    else:
        review_status = "complete"

    return STSDiagnosticResult(
        sts_six_vars=sts_six_vars,
        major_defects=major_defects,
        l3_critical_vars_pass=l3_pass,
        social_subsystem_defect=social_defect,
        interview_pending=False,
        review_status=review_status,
        extraction_notes=notes,
    )
