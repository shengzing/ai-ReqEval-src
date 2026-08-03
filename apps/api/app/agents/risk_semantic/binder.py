"""Semantic risk → process-node binding — LLM-augmented binding of risk items
and HITL rules to process node IDs.

When the LLM client is configured, asks the LLM to pick the most relevant
node for a given risk description. When unconfigured (or on LLM error), falls
back to the keyword-based ``_risk_binding_keywords`` + ``_find_process_node_id``
logic from ``skill_service`` so ``_NoLLM()`` runs are byte-identical.
"""

from __future__ import annotations

import logging
from typing import Any

from src.apps.api.app.agents.risk_semantic.binder_prompts import (
    RISK_NODE_BINDER_SYSTEM_PROMPT,
)
from src.apps.api.app.agents.risk_semantic.models import NodeBindingResult

logger = logging.getLogger(__name__)


def bind_risk_to_node_semantic(
    risk_description: str,
    process_nodes: list[dict[str, Any]],
    *,
    llm_client: Any = None,
    preferred_keywords: tuple[str, ...] | None = None,
    fallback_to_review: bool = True,
) -> NodeBindingResult:
    """Bind a risk item / HITL rule to a process node.

    Args:
        risk_description: Concatenated description/impact/audit_need text.
        process_nodes: List of process node dicts (node_id, name,
            owner_role, human_review_required).
        llm_client: Optional HarnessLLMClient. When None or unconfigured,
            keyword fallback is used.
        preferred_keywords: Optional pre-computed keywords (used by the
            fallback path to mirror the original ``_find_process_node_id``
            behavior). When None, the fallback calls
            ``_risk_binding_keywords`` itself.
        fallback_to_review: Whether the fallback falls back to a review-flagged
            node when no keyword matches.

    Returns:
        NodeBindingResult with node_id + source label.
    """
    if not process_nodes:
        return NodeBindingResult(node_id="", source="fallback")

    llm_result = _try_llm_bind(
        risk_description, process_nodes=process_nodes, llm_client=llm_client
    )
    if llm_result is not None:
        return llm_result

    return _fallback_bind(
        risk_description,
        process_nodes=process_nodes,
        preferred_keywords=preferred_keywords,
        fallback_to_review=fallback_to_review,
    )


# ── LLM path ───────────────────────────────────────────────────────────────


def _try_llm_bind(
    risk_description: str,
    *,
    process_nodes: list[dict[str, Any]],
    llm_client: Any = None,
) -> NodeBindingResult | None:
    """Attempt LLM-based binding. Returns None on failure (→ fallback)."""
    if llm_client is None:
        return None

    candidate_nodes = [
        {
            "node_id": str(n.get("node_id", "")),
            "name": str(n.get("name", "")),
            "owner_role": str(n.get("owner_role", "")),
            "human_review_required": bool(n.get("human_review_required")),
        }
        for n in process_nodes
    ]

    user_payload = {
        "risk_description": risk_description[:500],
        "candidate_nodes": candidate_nodes,
    }

    try:
        response = llm_client.complete_json(
            system_prompt=RISK_NODE_BINDER_SYSTEM_PROMPT,
            user_payload=user_payload,
        )
    except Exception:
        logger.warning("LLM risk-node binding failed, using fallback", exc_info=True)
        return None

    if not response:
        return None

    return _normalize_llm_output(response, process_nodes=process_nodes)


def _normalize_llm_output(
    response: dict[str, Any],
    *,
    process_nodes: list[dict[str, Any]],
) -> NodeBindingResult | None:
    """Normalize LLM JSON response. Returns None if unusable → caller falls back."""
    raw_node_id = str(response.get("node_id", "")).strip()
    valid_ids = {str(n.get("node_id", "")) for n in process_nodes}
    if raw_node_id and raw_node_id not in valid_ids:
        # LLM fabricated a node_id — refuse and fall back
        logger.warning("LLM returned unknown node_id %r, using fallback", raw_node_id)
        return None
    return NodeBindingResult(node_id=raw_node_id, source="llm")


# ── Fallback path (byte-identical to pre-upgrade skill_service binding) ────


def _fallback_bind(
    risk_description: str,
    *,
    process_nodes: list[dict[str, Any]],
    preferred_keywords: tuple[str, ...] | None,
    fallback_to_review: bool = True,
) -> NodeBindingResult:
    """Deterministic fallback using the original keyword + review-node logic.

    Delegates to ``skill_service._find_process_node_id`` (and its
    ``_risk_binding_keywords`` helper when no pre-computed keywords were
    supplied) so the unconfigured-LLM path is identical to pre-upgrade.
    """
    from src.apps.api.app.services.skill_service import (
        _find_process_node_id,
        _risk_binding_keywords,
    )

    if preferred_keywords is None:
        preferred_keywords = _risk_binding_keywords(risk_description)

    node_id = _find_process_node_id(
        process_nodes,
        preferred_keywords=preferred_keywords,
        fallback_to_review=fallback_to_review,
    )
    return NodeBindingResult(node_id=node_id, source="fallback")
