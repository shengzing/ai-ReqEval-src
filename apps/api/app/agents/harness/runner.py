"""Service-facing runner for the LangGraph skill harness."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

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


# Durable HITL checkpoint storage.
#
# LangGraph checkpoints persist graph state so a paused human-in-the-loop run
# survives a process restart and can be resumed from the API. We back them with
# a single SQLite database (``data/history.db``, already gitignored) via the
# official ``langgraph-checkpoint-sqlite`` saver.
#
# The saver is a process-wide singleton (one SQLite connection guarded by the
# saver's internal lock). Callers pass a ``thread_id`` (``thread-{run_id}``)
# to address a specific paused run; the saver is never chosen per-run.
_DEFAULT_CHECKPOINT_PATH = Path("data/history.db")


def _default_checkpoint_path() -> Path:
    """Return the checkpoint DB path, creating the parent dir if needed."""
    path = _DEFAULT_CHECKPOINT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=8)
def _get_durable_saver(checkpoint_path: str | None = None) -> SqliteSaver:
    """Return a durable checkpoint saver for *checkpoint_path* (cached).

    Defaults to ``data/history.db`` when no path is given. Each distinct path
    gets its own cached saver/connection, so parallel tests using tmp_path
    backings do not collide. A single connection backs each saver; SqliteSaver
    serialises access with an internal lock, so ``check_same_thread=False``
    is safe here.
    """
    path_str = checkpoint_path or str(_default_checkpoint_path())
    conn = sqlite3.connect(path_str, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _saver_for(config: "HarnessConfig | None") -> SqliteSaver:
    """Pick the saver for a run; default config -> the shared default DB."""
    if config and config.checkpoint_path:
        return _get_durable_saver(config.checkpoint_path)
    return _get_durable_saver()


def discard_hitl_checkpoint(thread_id: str | None, *, checkpoint_path: str | None = None) -> None:
    """Delete the paused checkpoint for a thread after the run resumed cleanly.

    Keeps the audit trace in RunEvent/StageResult; only the resumable graph
    state is dropped. Safe to call when no checkpoint exists.
    """
    if not thread_id:
        return
    try:
        _get_durable_saver(checkpoint_path).delete_thread(thread_id)
    except Exception:
        # Best-effort cleanup; a missing thread must not crash the caller.
        pass


def has_hitl_checkpoint(thread_id: str | None, *, checkpoint_path: str | None = None) -> bool:
    """Return whether a paused checkpoint still exists for the thread.

    Probes the durable store directly so the answer is correct across process
    restarts (unlike the old in-memory dict, which lost state on restart).
    """
    if not thread_id:
        return False
    try:
        graph = build_skill_graph(
            llm_client=HarnessLLMClient(),
            tool_invoker=invoke_tool,
            fail_fast=False,
            checkpointer=_get_durable_saver(checkpoint_path),
        )
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        return bool(snapshot and snapshot.next)
    except Exception:
        return False


def _hash_prompt_body(body: str) -> str:
    """Stable SHA-256 hex of the prompt body bytes."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class HarnessConfig:
    allow_llm_planning: bool = True
    allow_llm_final_decision: bool = True
    fail_fast: bool = False
    enable_hitl: bool = False  # When True, graph pauses at maybe_interrupt for human review
    # Optional override for the durable checkpoint path. Defaults to
    # ``data/history.db``. Tests pass a tmp_path-backed path to isolate runs.
    checkpoint_path: str | None = None
    # Client-supplied identity string mirrored from the run policy. Used by the
    # resume route to refuse an unexpected resumer. NOTE: this is a plain
    # string comparison, NOT a real auth principal — the project has no
    # identity system. Wire real auth before relying on it for trust.
    allowed_resumer: str | None = None


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

    When ``config.enable_hitl`` is True, the graph uses the durable
    SqliteSaver checkpointer and pauses before ``maybe_interrupt``.  In that
    case the return value is a ``(result, thread_id)`` tuple so the caller can
    later resume the graph with :func:`resume_skill_harness`. The paused
    checkpoint survives a process restart because it is persisted to
    ``data/history.db`` (or ``config.checkpoint_path``).

    When HITL is disabled (default), returns a plain
    :class:`HarnessExecutionResult` as before.

    ``auto_run_condition`` is retained for call-site compatibility but is inert:
    AutoResearch has been decoupled from the harness execution trigger, so the
    field no longer drives any inline behavior. The harness always ends at END
    after ``maybe_interrupt``; AutoResearch runs only via its independent API
    (``/autoresearch/*``). See
    ``DOCS/design/2026-07-12-stage-harness-autoresearch-architecture.md``.
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
        # HCR-P1-02：透传 primary_skill/enabled_skills 给 tool_nodes 重建
        # per-tool HarnessRequest。来自 invoke_skill 的 HarnessRequest 字段。
        "primary_skill": str(context_payload.get("primary_skill", "")),
        "enabled_skills": list(context_payload.get("enabled_skills", [])),
        "allowed_tools": list(skill.allowed_tools),
        "enabled_tools": list(enabled_tools),
        "enabled_subagents": list(enabled_subagents or []),
        "permission_adapter": context_payload.get("permission_adapter"),
        "tool_adapter": context_payload.get("tool_adapter"),
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
        checkpointer = _saver_for(runtime_config)
        # The service owns thread identity.  A deterministic fallback is kept
        # for direct unit callers, but a Run-backed execution always passes
        # ``thread-{run_id}`` so the resume route addresses the same state.
        thread_id = context_payload.get("thread_id") or (
            f"thread-{context_payload['run_id']}" if context_payload.get("run_id") else f"thread-{uuid4().hex[:12]}"
        )
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
    # LangGraph's interrupt-before returns the state *before* the decision
    # node.  Preserve the legacy contract for direct harness callers by
    # exposing the decision that was already derivable from tool failures;
    # the Run service later replaces it with the Stage 1 governance decision
    # built from the fully persisted scenario summary.
    if runtime_config.enable_hitl and "decision" not in final_state:
        failures = list(final_state.get("tool_failures", []))
        final_state = {
            **final_state,
            "requires_human": bool(failures),
            "decision": {
                "should_continue": not failures,
                "requires_human": bool(failures),
                "summary": (
                    "Fallback decision: tool failures require review."
                    if failures else "Fallback decision: awaiting Stage 1 governance gate."
                ),
                "confidence": 0.3 if failures else 0.6,
                "notes": [],
                "source": "checkpoint_pre_decision",
                "3d_alignment": {},
            },
        }
    if runtime_config.enable_hitl:
        final_state = {
            **final_state,
            "checkpoint": {
                "thread_id": thread_id,
                "status": "paused",
                "provider": "langgraph-v1",
            },
        }
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
    checkpoint_path: str | None = None,
) -> HarnessExecutionResult:
    """Resume a previously interrupted graph execution.

    Call this after the human reviewer has provided their input.  The graph
    continues from the ``maybe_interrupt`` node with the human decision.

    ``checkpoint_path`` must match the path the run originally paused on so the
    same durable saver is probed (defaults to the shared ``data/history.db``).
    """
    client = llm_client or HarnessLLMClient()
    cp = checkpointer or _get_durable_saver(checkpoint_path)
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
    # The checkpoint was consumed by resume. Drop the resumable graph state so
    # a stale thread cannot be resumed twice; the audit trace in RunEvent /
    # StageResult is preserved independently.
    discard_hitl_checkpoint(thread_id, checkpoint_path=checkpoint_path)
    return _state_to_result(final_state)
