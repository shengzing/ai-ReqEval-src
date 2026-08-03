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


def extract_risk_artifacts(*args: object, **kwargs: object) -> object:
    """Risk-artifact extraction (risk items / fatal errors / evidence bindings
    / scenario_type) — lazy-imported."""
    from src.apps.api.app.agents.risk_semantic.extractor import extract_risk_artifacts as _fn
    return _fn(*args, **kwargs)


def enrich_process_nodes_semantic(*args: object, **kwargs: object) -> object:
    """Process-node semantic enrichment (owner_role / human_review_required /
    output) — lazy-imported."""
    from src.apps.api.app.agents.risk_semantic.node_enricher import enrich_process_nodes_semantic as _fn
    return _fn(*args, **kwargs)


def bind_risk_to_node_semantic(*args: object, **kwargs: object) -> object:
    """Risk → process-node semantic binding — lazy-imported."""
    from src.apps.api.app.agents.risk_semantic.binder import bind_risk_to_node_semantic as _fn
    return _fn(*args, **kwargs)


def review_risk_semantic(*args: object, **kwargs: object) -> object:
    """Risk review second-opinion (LLM) — lazy-imported."""
    from src.apps.api.app.agents.risk_semantic.reviewer import review_risk_semantic as _fn
    return _fn(*args, **kwargs)


def build_semantic_patch(*args: object, **kwargs: object) -> object:
    """Semantic patch builder (LLM) — lazy-imported."""
    from src.apps.api.app.agents.risk_semantic.patcher import build_semantic_patch as _fn
    return _fn(*args, **kwargs)


__all__ = [
    "bind_risk_to_node_semantic",
    "build_semantic_patch",
    "classify_risk_semantic",
    "compute_risk_confidence_distribution",
    "enrich_process_nodes_semantic",
    "extract_risk_artifacts",
    "review_risk_semantic",
    "verify_evidence_chain",
    "RiskVocabulary",
]
