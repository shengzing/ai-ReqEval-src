"""Semantic process-node enricher — LLM-augmented owner_role /
human_review_required / output binding.

When the LLM client is configured, sends (nodes, participants) to the LLM for
semantic enrichment. When unconfigured (or on LLM error), falls back to the
deterministic keyword logic used by the pre-upgrade
``registry._enrich_process_nodes`` so ``_NoLLM()`` runs are byte-identical.
"""

from __future__ import annotations

import logging
from typing import Any

from src.apps.api.app.agents.risk_semantic.models import NodeEnrichmentReport
from src.apps.api.app.agents.risk_semantic.node_enricher_prompts import (
    NODE_ENRICHER_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def enrich_process_nodes_semantic(
    nodes: list[dict[str, Any]],
    participants: list[dict[str, Any]],
    *,
    llm_client: Any = None,
    input_objects: list[str] | None = None,
    output_objects: list[str] | None = None,
    manual_review_points: list[str] | None = None,
    audit_requirements: list[str] | None = None,
) -> NodeEnrichmentReport:
    """Enrich process nodes with owner_role / human_review_required / output.

    Mirrors the signature surface of ``registry._enrich_process_nodes`` so it
    can drop in as a replacement. The fallback path delegates to the original
    keyword-based enricher for byte-identical output.

    Args:
        nodes: Raw process node candidates (node_id, name, ...).
        participants: Parsed participants (role, responsibility, evidence_refs).
        llm_client: Optional HarnessLLMClient.
        input_objects / output_objects / manual_review_points / audit_requirements:
            Context lists used by the fallback enricher to populate node
            input/output/audit_fields. The LLM path ignores them (the LLM
            infers output from node semantics).

    Returns:
        NodeEnrichmentReport with enriched nodes + source label.
    """
    if not nodes:
        return NodeEnrichmentReport(nodes=[], source="fallback")

    llm_result = _try_llm_enrich(
        nodes,
        participants=participants,
        llm_client=llm_client,
    )
    if llm_result is not None:
        # Re-apply deterministic input/output/audit_fields context on top of
        # the LLM's owner_role/human_review_required/output verdicts, so we
        # don't lose the structured context the fallback enricher provides.
        return NodeEnrichmentReport(
            nodes=_apply_structured_context(
                llm_result,
                input_objects=input_objects or [],
                output_objects=output_objects or [],
                manual_review_points=manual_review_points or [],
                audit_requirements=audit_requirements or [],
            ),
            source="llm",
        )

    # Deterministic fallback — byte-identical to pre-upgrade _enrich_process_nodes
    from src.apps.api.app.agents.tools.registry import _enrich_process_nodes

    enriched = _enrich_process_nodes(
        nodes,
        input_objects=input_objects or [],
        output_objects=output_objects or [],
        participants=participants,
        manual_review_points=manual_review_points or [],
        audit_requirements=audit_requirements or [],
    )
    # Tag each node with the enrichment source for observability (not a contract
    # field — registry.py strips internal-only keys before serializing).
    for node in enriched:
        node["_enrich_source"] = "fallback"
    return NodeEnrichmentReport(nodes=enriched, source="fallback")


# ── LLM path ───────────────────────────────────────────────────────────────


def _try_llm_enrich(
    nodes: list[dict[str, Any]],
    *,
    participants: list[dict[str, Any]],
    llm_client: Any = None,
) -> list[dict[str, Any]] | None:
    """Attempt LLM-based enrichment. Returns None on failure (→ fallback)."""
    if llm_client is None:
        return None

    roles = [
        str(p.get("role", "")) for p in participants if isinstance(p, dict)
    ]

    node_payload = [
        {
            "node_id": str(n.get("node_id", "")),
            "name": str(n.get("name", "")),
            "input": list(n.get("input", []) or []),
            "output": list(n.get("output", []) or []),
        }
        for n in nodes
    ]

    user_payload = {
        "nodes": node_payload,
        "participants": roles,
    }

    try:
        response = llm_client.complete_json(
            system_prompt=NODE_ENRICHER_SYSTEM_PROMPT,
            user_payload=user_payload,
        )
    except Exception:
        logger.warning("LLM node enrichment failed, using fallback", exc_info=True)
        return None

    if not response:
        return None

    return _normalize_llm_output(response, nodes=nodes, roles=roles)


def _normalize_llm_output(
    response: dict[str, Any],
    *,
    nodes: list[dict[str, Any]],
    roles: list[str],
) -> list[dict[str, Any]] | None:
    """Normalize LLM JSON response into enriched nodes.

    Returns None if the shape is unusable — caller falls back.
    """
    raw_nodes = response.get("nodes", [])
    if not isinstance(raw_nodes, list):
        return None
    if len(raw_nodes) != len(nodes):
        # Length mismatch → trust the deterministic fallback
        logger.warning(
            "LLM node enrichment returned %d nodes, expected %d; using fallback",
            len(raw_nodes), len(nodes),
        )
        return None

    role_set = set(roles)
    enriched: list[dict[str, Any]] = []
    for original, raw in zip(nodes, raw_nodes):
        if not isinstance(raw, dict):
            return None
        node = dict(original)
        node.setdefault("input", list(original.get("input", []) or []))
        node.setdefault("output", list(original.get("output", []) or []))
        node.setdefault("system_refs", list(original.get("system_refs", []) or []))
        node.setdefault("audit_fields", list(original.get("audit_fields", []) or []))

        # owner_role — must be an existing participant role or empty
        raw_role = str(raw.get("owner_role", "")).strip()
        node["owner_role"] = raw_role if raw_role in role_set else ""

        # human_review_required — must be a bool
        raw_hrr = raw.get("human_review_required")
        node["human_review_required"] = bool(raw_hrr) if isinstance(raw_hrr, bool) else False

        # output — list of strings
        raw_output = raw.get("output", [])
        if isinstance(raw_output, list):
            node["output"] = [str(o) for o in raw_output if o]
        # else: keep original output

        node["_enrich_source"] = "llm"
        enriched.append(node)

    return enriched


def _apply_structured_context(
    nodes: list[dict[str, Any]],
    *,
    input_objects: list[str],
    output_objects: list[str],
    manual_review_points: list[str],
    audit_requirements: list[str],
) -> list[dict[str, Any]]:
    """Re-apply the deterministic input/output/audit_fields context on top of
    LLM-verdict nodes. Mirrors the post-processing block of
    ``registry._enrich_process_nodes`` (input to first node, output to nodes
    flagged by the LLM, audit_fields to human_review_required nodes)."""
    if not nodes:
        return nodes

    for idx, node in enumerate(nodes):
        if idx == 0 and input_objects and not node.get("input"):
            node["input"] = list(input_objects)
        # If the LLM marked output but didn't fill it, and output_objects exist,
        # attach them. We avoid clobbering LLM-provided output lists.
        if not node.get("output") and output_objects and node.get("human_review_required") is False:
            # only auto-attach output to non-review nodes flagged by LLM as
            # having output semantics; conservative: attach to last node if none
            pass
        if node.get("human_review_required") is True:
            if manual_review_points and not node.get("input"):
                node["input"] = list(manual_review_points)
            if audit_requirements and not node.get("audit_fields"):
                node["audit_fields"] = list(audit_requirements)

    # Ensure at least the last node carries output objects if no node does
    if output_objects and not any(n.get("output") for n in nodes):
        nodes[-1]["output"] = list(output_objects)

    return nodes
