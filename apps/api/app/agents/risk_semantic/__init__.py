"""Risk semantic analysis package.

Provides LLM-augmented risk identification, evidence chain verification,
confidence distributions, and a dynamic risk vocabulary.

All features degrade gracefully: when the LLM client is unconfigured,
deterministic (keyword/rule-based) fallbacks produce identical output
to the pre-refactor system.
"""

from __future__ import annotations

from src.apps.api.app.agents.risk_semantic.vocabulary import RiskVocabulary

# Lazy imports for modules that depend on optional LLM client
def classify_risk_semantic(*args: object, **kwargs: object) -> object:
    """Semantic risk classification — lazy-imported to avoid import errors."""
    from src.apps.api.app.agents.risk_semantic.classifier import classify_risk_semantic as _fn
    return _fn(*args, **kwargs)


def verify_evidence_chain(*args: object, **kwargs: object) -> object:
    """Evidence chain verification — lazy-imported."""
    from src.apps.api.app.agents.risk_semantic.verifier import verify_evidence_chain as _fn
    return _fn(*args, **kwargs)


def compute_risk_confidence_distribution(*args: object, **kwargs: object) -> object:
    """Confidence distribution computation — lazy-imported."""
    from src.apps.api.app.agents.risk_semantic.confidence import compute_risk_confidence_distribution as _fn
    return _fn(*args, **kwargs)


__all__ = [
    "classify_risk_semantic",
    "compute_risk_confidence_distribution",
    "verify_evidence_chain",
    "RiskVocabulary",
]
