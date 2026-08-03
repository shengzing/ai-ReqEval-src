"""Service-facing runner for the LangGraph skill harness."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from src.apps.api.app.agents.harness.graph import build_skill_graph
from src.apps.api.app.agents.harness.llm import HarnessLLMClient
from src.apps.api.app.agents.harness.models import (
    HarnessExecutionResult,
)
from src.apps.api.app.agents.harness.state import GRAPH_VERSION, HarnessState
from src.apps.api.app.agents.skills.registry import SkillDefinition
from src.apps.api.app.agents.tools.registry import ToolResult
from src.apps.api.app.services.settings_service import settings_snapshot
from src.apps.api.app.services.tool_service import invoke_tool


# MemorySaver is intentionally process-local. A durable checkpoint store and
# an API-level resume workflow are separate work; do not silently resume from
# an empty saver when a process has already lost the checkpoint.
_HITL_CHECKPOINTS: dict[str, Any] = {}


def _hash_prompt_body(body: str) -> str:
    """Stable SHA-256 hex of the prompt body bytes."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class HarnessConfig:
    allow_llm_planning: bool = True
    allow_llm_final_decision: bool = True
    fail_fast: bool = False
    enable_hitl: bool = False  # When True, graph pauses at maybe_interrupt for human review


def _state_to_result(state: HarnessState) -> HarnessExecutionResult:
    return HarnessExecutionResult(state=dict(state))


def run_skill_harness(
    *,
    skill: SkillDefinition,
    goal: str,
    stage_name: str,
    enabled_tools: list[str],
    enabled_subagents: list[str] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    vision_results: list[dict[str, Any]] | None = None,
    previous_stage_result: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    llm_client: HarnessLLMClient | None = None,
    tool_invoker: Callable[..., ToolResult] | None = None,
    config: HarnessConfig | None = None,
    auto_run_condition: str | None = None,
) -> HarnessExecutionResult | tuple[HarnessExecutionResult, str]:
    """Execute the skill harness.

    When ``config.enable_hitl`` is True, the graph uses a MemorySaver
    checkpointer and pauses before ``maybe_interrupt``.  In that case the
    return value is a ``(result, thread_id)`` tuple so the caller can later
    resume the graph with :func:`resume_skill_harness`.

    When HITL is disabled (default), returns a plain
    :class:`HarnessExecutionResult` as before.

    ``auto_run_condition`` overrides the skill's default condition for the
    autoresearch graph node (``"manual"`` | ``"on_inputs_ready"`` |
    ``"auto"``).
    """
    runtime_config = config or HarnessConfig()
    client = llm_client or HarnessLLMClient()
    context_payload = context or {}
    initial_state: HarnessState = {
        "graph_version": GRAPH_VERSION,
        "project_id": str(context_payload.get("project_id", "")),
        "stage_id": str(context_payload.get("stage_id", "")),
        "run_id": str(context_payload.get("run_id", "")),
        "goal": goal,
        "stage_name": stage_name,
        "config_version_id": str(context_payload.get("config_version_id", "")),
        "skill_name": skill.name,
        "skill_version": str(context_payload.get("skill_version", "")),
        "allowed_tools": list(skill.allowed_tools),
        "enabled_tools": list(enabled_tools),
        "enabled_subagents": list(enabled_subagents or []),
        "evidence_items": list(evidence_items or []),
        "vision_results": list(vision_results or []),
        "previous_stage_result": previous_stage_result,
        "messages": [],
        "traces": [],
        "auto_run_condition": auto_run_condition or skill.auto_run_condition,
        # L1-A: populate prompt runtime fields from the project's published
        # settings so graph.py can read them instead of the hardcoded fallback
        # strings. Falls back to empty dicts when project_id is missing (e.g.
        # ad-hoc test runs).
    }
    project_id = str(context_payload.get("project_id", ""))
    prompt_templates: dict[str, str] = {}
    prompt_versions: dict[str, str] = {}
    prompt_hashes: dict[str, str] = {}
    if project_id:
        try:
            snapshot = settings_snapshot(
                project_id,
                stage_id=str(context_payload.get("stage_id", "")) or None,
                config_version_id=context_payload.get("config_version_id"),
            )
            bodies = snapshot.get("prompt_bodies") or {}
            refs = snapshot.get("prompt_refs") or []
            for ref in refs:
                prompt_id = ref.get("id", "")
                if prompt_id in bodies:
                    prompt_templates[prompt_id] = bodies[prompt_id]
                    prompt_versions[prompt_id] = ref.get("version", "v1")
                    prompt_hashes[prompt_id] = _hash_prompt_body(bodies[prompt_id])
        except Exception:
            # snapshot may fail in unit tests without a project; keep empty
            prompt_templates = {}
            prompt_versions = {}
            prompt_hashes = {}
    initial_state["prompt_templates"] = prompt_templates
    initial_state["prompt_versions"] = prompt_versions
    initial_state["prompt_hashes"] = prompt_hashes

    checkpointer = None
    thread_id = ""
    if runtime_config.enable_hitl:
        checkpointer = MemorySaver()
        thread_id = context_payload.get("thread_id") or f"thread-{uuid4().hex[:12]}"
        _HITL_CHECKPOINTS[thread_id] = checkpointer
        initial_state["thread_id"] = thread_id
        initial_state["human_input"] = context_payload.get("human_input")

    graph = build_skill_graph(
        llm_client=client,
        tool_invoker=tool_invoker or invoke_tool,
        fail_fast=runtime_config.fail_fast,
        allow_llm_planning=runtime_config.allow_llm_planning,
        allow_llm_final_decision=runtime_config.allow_llm_final_decision,
        checkpointer=checkpointer,
    )

    graph_config = {}
    if checkpointer is not None:
        graph_config["configurable"] = {"thread_id": thread_id}

    final_state = graph.invoke(initial_state, config=graph_config)
    result = _state_to_result(final_state)

    if runtime_config.enable_hitl:
        return result, thread_id
    return result


def resume_skill_harness(
    *,
    thread_id: str,
    human_input: dict[str, Any] | None = None,
    llm_client: HarnessLLMClient | None = None,
    tool_invoker: Callable[..., ToolResult] | None = None,
    checkpointer: Any | None = None,
    fail_fast: bool = False,
) -> HarnessExecutionResult:
    """Resume a previously interrupted graph execution.

    Call this after the human reviewer has provided their input.  The graph
    continues from the ``maybe_interrupt`` node with the human decision.
    """
    client = llm_client or HarnessLLMClient()
    cp = checkpointer or _HITL_CHECKPOINTS.get(thread_id)
    if cp is None:
        raise ValueError("HITL checkpoint is unavailable; start a new harness run or provide its checkpointer.")

    graph = build_skill_graph(
        llm_client=client,
        tool_invoker=tool_invoker or invoke_tool,
        fail_fast=fail_fast,
        checkpointer=cp,
    )

    graph_config = {"configurable": {"thread_id": thread_id}}
    # A dict passed to invoke starts a fresh graph invocation. Update the
    # paused checkpoint first, then invoke(None) to continue at the interrupt.
    # The graph currently uses ``StateGraph(dict)``; a partial update replaces
    # the root dict, so preserve the paused state explicitly before adding the
    # human input.
    paused_state = dict(graph.get_state(graph_config).values)
    if not paused_state:
        raise ValueError("HITL checkpoint has no paused state to resume.")
    graph.update_state(
        graph_config,
        {**paused_state, "human_input": human_input or {}},
    )
    final_state = graph.invoke(None, config=graph_config)
    _HITL_CHECKPOINTS.pop(thread_id, None)
    return _state_to_result(final_state)
