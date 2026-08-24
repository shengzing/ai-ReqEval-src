"""Serializable state contracts for the LangGraph skill harness."""

from __future__ import annotations

from typing import Any, TypedDict


NO_LLM_FALLBACK_MESSAGE = "LLM 未配置，已使用规则 fallback 执行；结果可用于本地测试，但不代表 LLM 推理输出。"
GRAPH_VERSION = "langgraph-harness-v1"


class HarnessState(TypedDict, total=False):
    graph_version: str
    project_id: str
    stage_id: str
    run_id: str
    goal: str
    stage_name: str
    config_version_id: str
    skill_name: str
    skill_version: str
    # HCR-P1-02 配置溯源：与 HarnessRequest 同名字段，tool_nodes.py 重建
    # per-tool HarnessRequest 时透传。仅审计用。
    primary_skill: str
    enabled_skills: list[str]
    allowed_tools: list[str]
    enabled_tools: list[str]
    enabled_subagents: list[str]
    # Request-scoped execution controls. These are process-local objects used
    # by the graph's tool node; they are not included in result contracts.
    permission_adapter: Any
    tool_adapter: Any
    evidence_items: list[dict[str, Any]]
    vision_results: list[dict[str, Any]]
    previous_stage_result: dict[str, Any] | None
    messages: list[dict[str, Any]]
    plan: dict[str, Any]
    tool_results: dict[str, dict[str, Any]]
    tool_result_items: list[dict[str, Any]]
    tool_failures: list[dict[str, Any]]
    tool_skips: list[dict[str, Any]]
    synthesized_payload: dict[str, Any]
    validation_issues: list[dict[str, Any]]
    quality_scores: dict[str, Any]
    decision: dict[str, Any]
    requires_human: bool
    llm_status: dict[str, Any]
    traces: list[dict[str, Any]]
    # HITL resume fields
    thread_id: str
    human_input: dict[str, Any]
    checkpoint: dict[str, Any]
    # Subagent results
    subagent_results: list[dict[str, Any]]
    subagent_audits: list[dict[str, Any]]
    # AutoResearch fields
    auto_run_condition: str
    autoresearch_record_ids: list[str]
    # Refinement loop fields (Phase 2)
    refinement_iteration: int
    max_refinement_iterations: int
    refinement_history: list[dict[str, Any]]
    # Candidate / rejected records (AutoResearch reproducibility)
    candidate_ids: list[str]
    rejected_candidate_ids: list[str]
    # L1-A: Prompt runtime fields — populated by runner from settings_snapshot,
    # read by graph.py plan_tools / synthesize_result instead of hardcoded strings.
    prompt_templates: dict[str, str]  # {prompt_id: body}  运行时已解析
    prompt_versions: dict[str, str]   # {prompt_id: "v1"/"v2"/...}  审计
    prompt_hashes: dict[str, str]     # {prompt_id: sha256_hex}
    # L3: RuleProposal ids emitted during refinement
    rule_proposal_ids: list[str]
