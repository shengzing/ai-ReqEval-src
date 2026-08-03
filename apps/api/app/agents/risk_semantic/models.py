"""Data models for the risk semantic analysis package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Vocabulary models ──────────────────────────────────────────────────────


@dataclass
class RiskTerm:
    """A single risk term in the vocabulary.

    Attributes:
        canonical: The canonical (standard) form of the risk term.
        level: Risk level — "L2" or "L3".
        category: Semantic category — compliance, data, customer, model, operational.
        synonyms: Alternative phrases that map to this canonical term.
        children: Hierarchical sub-terms that inherit the parent's risk level.
        parent: Canonical name of the parent term, or None for top-level terms.
    """

    canonical: str
    level: str  # "L2" | "L3"
    category: str  # "compliance" | "data" | "customer" | "model" | "operational"
    synonyms: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    parent: str | None = None


@dataclass
class KeywordMatch:
    """Result of a vocabulary lookup operation.

    Attributes:
        term: The canonical risk term that was matched.
        matched_synonym: The synonym string that was actually found in the text,
            or None if the canonical form was matched directly.
        matched_child: The child term that was found, or None.
        level: The risk level of the matched term.
        category: The semantic category of the matched term.
        is_synonym: True if matched via a synonym rather than the canonical form.
        is_hierarchical: True if matched via a child term.
    """

    term: str
    matched_synonym: str | None
    matched_child: str | None
    level: str
    category: str
    is_synonym: bool
    is_hierarchical: bool


# ── Semantic risk classifier models ───────────────────────────────────────


@dataclass
class RiskBrief:
    """Context summary passed to the semantic risk classifier.

    Attributes:
        scenario_name: Name of the AI application scenario.
        combined_text: Full text extracted from evidence/vision items.
        keyword_hits_l3: L3 keyword matches after negation filtering.
        keyword_hits_l2: L2 keyword matches after negation filtering.
        negated_keywords: Keywords suppressed by negation context.
        known_risk_points: Risk items already identified by rule-based scanning.
        prohibited_conditions: Prohibited conditions extracted from evidence.
        boundary_flag: True when both L2 and L3 keywords co-occur.
    """

    scenario_name: str
    combined_text: str
    keyword_hits_l3: list[str] = field(default_factory=list)
    keyword_hits_l2: list[str] = field(default_factory=list)
    negated_keywords: set[str] = field(default_factory=set)
    known_risk_points: list[str] = field(default_factory=list)
    prohibited_conditions: list[str] = field(default_factory=list)
    boundary_flag: bool = False


@dataclass
class SemanticRiskResult:
    """Result of semantic risk classification.

    Attributes:
        risk_level: Final risk level — MUST be in RISK_LEVELS (L1|L2|L3).
        hitl_level: Final HITL level — MUST be in HITL_LEVELS.
        risk_items_semantic: Additional risk items identified by LLM (beyond keyword hits).
        confidence: Classifier confidence in [0, 1].
        reasoning: Human-readable reasoning for the classification.
        boundary_flag: True when the classifier detects a boundary scenario.
        source: "llm" when LLM was used, "fallback" for deterministic fallback.
    """

    risk_level: str
    hitl_level: str
    risk_items_semantic: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""
    boundary_flag: bool = False
    source: str = "fallback"


# ── Confidence distribution models ────────────────────────────────────────


@dataclass
class RiskConfidenceDistribution:
    """Probability distribution over risk levels.

    Attributes:
        L1: Probability of L1 classification.
        L2: Probability of L2 classification.
        L3: Probability of L3 classification.
        dominant_level: The level with highest probability (must match risk_level).
        boundary_flag: True when top-2 levels are within 0.15 of each other.
        source: "llm" or "heuristic" depending on how the distribution was computed.
    """

    L1: float
    L2: float
    L3: float
    dominant_level: str
    boundary_flag: bool
    source: str  # "llm" | "heuristic"

    def __post_init__(self) -> None:
        total = self.L1 + self.L2 + self.L3
        if abs(total - 1.0) > 0.05:
            raise ValueError(
                f"Confidence distribution must sum to ~1.0, got {total:.3f}"
            )


# ── Evidence chain verification models ─────────────────────────────────────


@dataclass
class EvidenceVerificationResult:
    """Result of verifying a single risk-item ↔ evidence pair.

    Attributes:
        risk_id: The risk item being verified.
        evidence_id: The evidence item being checked.
        supports: True if the evidence supports the risk item.
        confidence: Verification confidence in [0, 1].
        reasoning: Human-readable reasoning.
        source: "llm", "rule", or "fallback".
    """

    risk_id: str
    evidence_id: str
    supports: bool
    confidence: float
    reasoning: str
    source: str  # "llm" | "rule" | "fallback"


@dataclass
class EvidenceChainReport:
    """Aggregate report of evidence chain verification.

    Attributes:
        results: Per-risk-item verification results.
        overall_score: Fraction of risk items with supporting evidence.
        unverified_items: List of risk IDs without verified evidence.
    """

    results: list[EvidenceVerificationResult] = field(default_factory=list)
    overall_score: float = 0.0
    unverified_items: list[str] = field(default_factory=list)
