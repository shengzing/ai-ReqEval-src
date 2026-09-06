"""Sub-agents for Stage 2-3 analysis — LLM extraction + formulas.

Stage 2 (P1):
  * ``impl_tax_estimator`` — extracts 式(1) seven-category implementation-
    tax items from evidence materials (post-loan SOP, audit checklists,
    shift schedules) and validates them against the formulas package.
  * ``value_net_builder`` — constructs the e3-value value-exchange
    network (four actors, 12 primitives) and runs the reciprocity check.

Stage 3 (P2):
  * ``atomic_task_decomposer`` — decomposes SOP process nodes into
    measurable atomic tasks (§3.4.1) with dual-axis annotation
    (non_routine, interdependence) and sla_dim tags.
  * ``rubric_designer`` — designs the three-dimension scoring rubric
    (§3.4.2: qual/eff/gov, 4-tier grade scale, hard/soft constraint
    flags) anchored to atomic tasks.

Stage 3b (P3):
  * ``probe_scorer`` — dual-rater independent scoring + ICC(2,k)
    reliability gate (§3.4.2: ICC ≥ 0.70, divergence ≥ 1 tier flagged).
  * ``jagged_frontier`` — frontier-in/out SLA stratification + alert
    (§3.4.3: out-share ≥ 40%, gap > 5pp → alert).
  * ``trust_calibration`` — misuse/disuse/skill-degradation detection
    (§3.4.2: divergence < 5% → misuse, > 30% → disuse, blind < 90% →
    retraining).

Stage 4 (P4):
  * ``retro_calibration`` — retroactive calibration agent (§3.5.2 步骤9):
    式(7) retro gap + §5.3.2 framework revision records (new version, not
    overwrite) + §5.3.1 representativeness grading + §5.3.2 fatal-rate
    interruption.
  * ``evidence_fusion`` — three-dimension evidence fusion (§3.5.1):
    per-task fusion table (行=原子任务, 列=三维证据) + 否决级/参考级/
    决策级 strength grading + cross-dimension conflict detection.
  * ``sts_diagnostic`` — STS six-variable social-subsystem diagnostic
    (§3.2.1, placeholder pending M1 interviews): reserves six-var field
    structure, no numeric thresholds pre-filled.

Design constraints (CLAUDE.md):
  * These are Sub-agents mounted on the existing 4 stage-level Skills —
    they are NOT standalone 9-Agent targets.  The 9-Agent architecture
    remains a future-state description.
  * Pure-function formula calls (``compute_implementation_tax``,
    ``check_reciprocity``, ``compute_actual_sla``) are the single source
    of truth; these agents only handle LLM extraction/judgment and hand
    off to the formulas.
  * Delphi prior seed values are annotated "初始参考值，待 M2-M4 实证标定".
"""

from __future__ import annotations

from .impl_tax_estimator import ImplTaxEstimatorResult, estimate_implementation_tax
from .value_net_builder import ValueNetResult, build_value_net
from .atomic_task_decomposer import (
    AtomicTaskDecomposerResult,
    decompose_atomic_tasks,
)
from .rubric_designer import (
    RubricDesignerResult,
    design_rubric,
)
from .probe_scorer import (
    ProbeScorerResult,
    score_probe_samples,
)
from .jagged_frontier import (
    JaggedFrontierResult,
    analyze_jagged_frontier,
)
from .trust_calibration import (
    TrustCalibrationResult,
    calibrate_trust,
)
from .retro_calibration import (
    RetroCalibrationResult,
    calibrate_retrospective,
)
from .evidence_fusion import (
    EvidenceFusionResult,
    fuse_three_dim_evidence,
)
from .sts_diagnostic import (
    STSDiagnosticResult,
    diagnose_sts_subsystem,
)

__all__ = [
    # Stage 2 (P1)
    "ImplTaxEstimatorResult",
    "estimate_implementation_tax",
    "ValueNetResult",
    "build_value_net",
    # Stage 3 (P2)
    "AtomicTaskDecomposerResult",
    "decompose_atomic_tasks",
    "RubricDesignerResult",
    "design_rubric",
    # Stage 3b (P3)
    "ProbeScorerResult",
    "score_probe_samples",
    "JaggedFrontierResult",
    "analyze_jagged_frontier",
    "TrustCalibrationResult",
    "calibrate_trust",
    # Stage 4 (P4)
    "RetroCalibrationResult",
    "calibrate_retrospective",
    "EvidenceFusionResult",
    "fuse_three_dim_evidence",
    "STSDiagnosticResult",
    "diagnose_sts_subsystem",
]

