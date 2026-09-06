"""P1-5 value-net-builder — e3-value value-exchange network constructor.

Thesis §3.3.1-§3.3.3: the value-net builder constructs the e3-value model
(four actors, 12 primitives) and runs the reciprocity check (互惠原则:
no dangling ports).

Four actors (§3.3.1, risk/compliance merged):
  科技, 业务, 风险/合规, 运营

e3-value primitives (12): value activity, value port, value interface,
value exchange, market segment, scenario path, dependency path, etc.

Reciprocity (§3.3.3 互惠原则): every actor's in-ports must have a
corresponding source exchange, and out-ports a corresponding destination
exchange.  A "dangling port" (in-port with no source, or out-port with
no destination) is a reciprocity violation.

This Sub-agent is mounted on the existing Stage 2 Skill — NOT a
standalone 9-Agent target (CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.apps.api.app.services.formulas import (
    build_actor_net_value_table,
    check_reciprocity,
)
from src.apps.api.app.services.formulas.net_value import ACTORS


@dataclass
class ValueNetResult:
    """Output of the value-net-builder Sub-agent.

    Attributes:
        value_exchanges: list of e3-value value-exchange dicts
            ``{exchange_id, from_actor, to_actor, direction, ...}``
        value_ports: list of e3-value value-port dicts
            ``{port_id, actor, direction(in|out), ...}``
        actor_net_value: per-actor profitability table (§3.3.3)
        reciprocity_violations: list of dangling-port violations
        reciprocity_passed: bool — True if no violations
        aggregation_masking: bool — True if any actor net < 0
        masking_actors: actors with net_value_i < 0
        review_status: "complete" | "partial" | "empty"
        extraction_notes: provenance notes
    """

    value_exchanges: list[dict[str, Any]] = field(default_factory=list)
    value_ports: list[dict[str, Any]] = field(default_factory=list)
    actor_net_value: list[dict[str, Any]] = field(default_factory=list)
    reciprocity_violations: list[dict[str, Any]] = field(default_factory=list)
    reciprocity_passed: bool = True
    aggregation_masking: bool = False
    masking_actors: list[str] = field(default_factory=list)
    review_status: str = "empty"
    extraction_notes: list[str] = field(default_factory=list)


def build_value_net(
    *,
    actor_benefits: dict[str, float] | None = None,
    actor_costs: dict[str, float] | None = None,
    value_exchanges: list[dict] | None = None,
    value_ports: list[dict] | None = None,
    llm_client: Any = None,
) -> ValueNetResult:
    """Construct the e3-value network and run reciprocity + per-actor checks.

    The construction proceeds in three phases:

    1. **Port synthesis**: if value_ports are not explicitly provided,
       synthesize them from value_exchanges (every exchange implies an
       out-port on the from_actor and an in-port on the to_actor).
    2. **LLM extraction** (optional): when *llm_client* is provided,
       additional exchanges/ports are extracted from the scenario
       background and responsibility chain.  Unconfigured / LLM-failed
       runs degrade gracefully to explicit-input-only.
    3. **Formula validation**: the merged network is handed to
       ``check_reciprocity`` (pure function) for the dangling-port
       check, and ``build_actor_net_value_table`` for the per-actor
       profitability table.

    Args:
        actor_benefits: {actor: benefit_i} for the four actors.
        actor_costs: {actor: cost_i} for the four actors.
        value_exchanges: e3-value value-exchange dicts.
        value_ports: e3-value value-port dicts (optional; auto-synthesized).
        llm_client: optional LLM client for free-text extraction.

    Returns:
        ValueNetResult with the full network and validation results.
    """
    notes: list[str] = []
    actor_benefits = actor_benefits or {}
    actor_costs = actor_costs or {}
    exchanges = list(value_exchanges or [])
    ports = list(value_ports or [])

    # ── Phase 1: port synthesis ──
    if not ports and exchanges:
        ports = _synthesize_ports(exchanges)
        notes.append(f"从 {len(exchanges)} 条价值交换自动合成 {len(ports)} 个价值端口。")

    # ── Phase 2: LLM extraction (optional) ──
    llm_added = 0
    if llm_client is not None:
        llm_exchanges, llm_ports = _llm_extract_value_net(llm_client, exchanges, ports)
        if llm_exchanges:
            exchanges.extend(llm_exchanges)
            llm_added += len(llm_exchanges)
        if llm_ports:
            ports.extend(llm_ports)
        if llm_added:
            notes.append(f"LLM 抽取新增 {llm_added} 条价值交换。")

    # ── Phase 3a: reciprocity check (e3-value, §3.3.3) ──
    reciprocity_result = check_reciprocity(ports, exchanges)

    # ── Phase 3b: per-actor profitability (§3.3.3) ──
    actor_table_result = build_actor_net_value_table(actor_benefits, actor_costs)

    # Determine review status
    has_data = bool(exchanges) or bool(actor_benefits) or bool(actor_costs)
    if not has_data:
        review_status = "empty"
    elif reciprocity_result["passed"] and not actor_table_result["aggregation_masking"]:
        review_status = "complete"
    else:
        review_status = "partial"

    return ValueNetResult(
        value_exchanges=exchanges,
        value_ports=ports,
        actor_net_value=actor_table_result["table"],
        reciprocity_violations=reciprocity_result["reciprocity_violations"],
        reciprocity_passed=reciprocity_result["passed"],
        aggregation_masking=actor_table_result["aggregation_masking"],
        masking_actors=actor_table_result["masking_actors"],
        review_status=review_status,
        extraction_notes=notes,
    )


def _synthesize_ports(exchanges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Synthesize value ports from value exchanges.

    Every exchange implies an out-port on the from_actor and an in-port
    on the to_actor.  This is a 1:1 synthesis — the resulting ports are
    guaranteed to have matching exchanges, so reciprocity passes trivially.
    """
    ports: list[dict[str, Any]] = []
    for i, ex in enumerate(exchanges):
        from_actor = ex.get("from_actor")
        to_actor = ex.get("to_actor")
        exchange_id = ex.get("exchange_id", f"ex-{i}")
        if from_actor:
            ports.append({
                "port_id": f"out-{exchange_id}-{from_actor}",
                "actor": from_actor,
                "direction": "out",
                "exchange_id": exchange_id,
            })
        if to_actor:
            ports.append({
                "port_id": f"in-{exchange_id}-{to_actor}",
                "actor": to_actor,
                "direction": "in",
                "exchange_id": exchange_id,
            })
    return ports


def _llm_extract_value_net(
    llm_client: Any,
    existing_exchanges: list[dict],
    existing_ports: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Extract additional value exchanges/ports from free-text via LLM.

    Placeholder hook for LLM extraction — the actual prompt template and
    parsing logic live in risk_semantic.patcher_prompts.  For now, return
    empty; the Sub-agent is still useful via explicit inputs.
    """
    _ = (llm_client, existing_exchanges, existing_ports)  # silence unused
    return [], []
