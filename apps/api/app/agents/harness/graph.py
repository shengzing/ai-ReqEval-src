"""LangGraph implementation of the Skill + Tool harness."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.apps.api.app.agents.harness.llm import HarnessLLMClient
from src.apps.api.app.agents.harness.serializers import append_trace
from src.apps.api.app.agents.harness.state import GRAPH_VERSION, HarnessState, NO_LLM_FALLBACK_MESSAGE
from src.apps.api.app.agents.harness.tool_nodes import ToolInvoker, run_tool_node


# L1-A: hardcoded fallback prompts used only when state["prompt_templates"]
# does not contain the requested prompt_id. Keep these strings byte-identical
# with the previous behaviour so existing tests that mock the LLM client
# without supplying prompts continue to work.
DEFAULT_PLANNER_PROMPT = (
    "You are an internal requirement-evaluation harness planner. "
    "Return JSON with tool_names and reasoning. Only choose from enabled_tools."
)
DEFAULT_SYNTHESIZER_PROMPT = (
    "You synthesize Stage 1 scenario_summary JSON for a requirement evaluation platform. "
    "Return JSON only. Include risk_level, hitl_level, scenario_name, boundary, participants, "
    "process_nodes, risk_items, risk_matrix, hitl_rules, audit_requirements, prohibited_conditions, "
    "fatal_errors, evidence_refs, to_confirm, confidence, and review_status when evidence supports them. "
    "Include edges (list of {from, to, label?, variant}) and main_path (list of node ids) "
    "when evidence supports them. main_path must not regress: consecutive node ids must have "
    "a matching edge and move forward in process_nodes order; loops are edges with variant "
    "\"return\" outside main_path."
)


def _resolve_prompt(state: HarnessState, prompt_id: str, default: str) -> str:
    """Return the body of ``prompt_id`` from state.prompt_templates, falling
    back to ``default`` (the historical hardcoded string). L1-A makes
    PromptTemplate.body drive runtime LLM calls instead of dataclass dead
    code."""
    templates = state.get("prompt_templates") or {}
    return templates.get(prompt_id, default)


def _safe_enabled_tools(state: HarnessState) -> list[str]:
    allowed = set(state.get("allowed_tools", []))
    return [tool for tool in state.get("enabled_tools", []) if tool in allowed]


def _llm_status(llm_client: HarnessLLMClient, *, mode: str | None = None, message: str | None = None) -> dict[str, Any]:
    if hasattr(llm_client, "status"):
        return llm_client.status(mode=mode, message=message)
    configured = bool(llm_client.is_configured())
    return {
        "configured": configured,
        "mode": mode or ("llm" if configured else "fallback"),
        "message": message or ("" if configured else NO_LLM_FALLBACK_MESSAGE),
        "missing": [] if configured else ["AGENT_LLM_BASE_URL", "AGENT_LLM_API_KEY"],
    }


def build_skill_graph(
    *,
    llm_client: HarnessLLMClient,
    tool_invoker: ToolInvoker,
    fail_fast: bool = False,
    allow_llm_planning: bool = True,
    allow_llm_final_decision: bool = True,
    checkpointer: Any | None = None,
    interrupt_before: list[str] | None = None,
):
    """Build the LangGraph skill harness.

    Parameters
    ----------
    checkpointer : optional
        A LangGraph checkpointer (e.g. ``MemorySaver``).  When provided the
        graph can be interrupted and later resumed, enabling true HITL.
    interrupt_before : optional
        Node names before which the graph should pause.  Defaults to
        ``["maybe_interrupt"]`` when a *checkpointer* is provided, so that
        human review can happen after contract validation.
    """
    # LangGraph 1.x requires a declared state schema. ``dict`` no longer
    # discovers channels for arbitrary keys, so node updates would be dropped.
    graph = StateGraph(HarnessState)

    def load_context(state: HarnessState) -> HarnessState:
        initialized: HarnessState = {
            **state,
            "graph_version": GRAPH_VERSION,
            "tool_results": dict(state.get("tool_results", {})),
            "tool_result_items": list(state.get("tool_result_items", [])),
            "tool_failures": list(state.get("tool_failures", [])),
            "traces": list(state.get("traces", [])),
        }
        return append_trace(
            initialized,
            "context.loaded",
            {
                "skill_name": initialized.get("skill_name"),
                "config_version_id": initialized.get("config_version_id"),
                "skill_version": initialized.get("skill_version"),
            },
        )

    def plan_tools(state: HarnessState) -> HarnessState:
        safe_enabled = _safe_enabled_tools(state)
        llm_status = _llm_status(llm_client)
        if allow_llm_planning and llm_client.is_configured() and safe_enabled:
            try:
                payload = llm_client.complete_json(
                    system_prompt=_resolve_prompt(state, "prompt-planner", DEFAULT_PLANNER_PROMPT),
                    user_payload={
                        "skill": state.get("skill_name"),
                        "stage_name": state.get("stage_name"),
                        "goal": state.get("goal"),
                        "enabled_tools": safe_enabled,
                        "config_version_id": state.get("config_version_id"),
                    },
                )
                requested = payload.get("tool_names") if isinstance(payload, dict) else None
                planned = [tool for tool in requested if tool in safe_enabled] if isinstance(requested, list) else []
                if planned:
                    next_state = {
                        **state,
                        "llm_status": llm_status,
                        "plan": {
                            "tool_names": planned,
                            "reasoning": str(payload.get("reasoning", "LLM selected enabled tools.")),
                            "source": "llm",
                        },
                    }
                    return append_trace(next_state, "harness.planned", {"source": "llm", "tool_names": planned})
                llm_status = _llm_status(
                    llm_client,
                    mode="error_fallback",
                    message="LLM planner selected no enabled tools.",
                )
                state = append_trace(
                    state,
                    "llm.plan_invalid",
                    {
                        "reason": "no_enabled_tools_selected" if isinstance(requested, list) else "missing_or_invalid_tool_names",
                        "requested": requested,
                    },
                )
            except Exception as exc:
                llm_status = _llm_status(llm_client, mode="error_fallback", message=str(exc))
                state = append_trace(state, "llm.plan_failed", {"error": str(exc)})

        next_state = {
            **state,
            "llm_status": llm_status,
            "plan": {
                "tool_names": safe_enabled,
                "reasoning": "Fallback plan uses all enabled tools in registry order.",
                "source": "fallback",
            },
        }
        return append_trace(next_state, "harness.fallback", llm_status)

    def execute_tools(state: HarnessState) -> HarnessState:
        next_state = state
        for tool_name in state.get("plan", {}).get("tool_names", []):
            next_state = run_tool_node(
                next_state, tool_name,
                tool_invoker=tool_invoker, fail_fast=fail_fast,
                llm_client=llm_client,
            )
            if fail_fast and next_state.get("tool_failures"):
                break
        return next_state

    def run_subagents(state: HarnessState) -> HarnessState:
        """Execute enabled subagents with the current tool results."""
        from src.apps.api.app.agents.deepagent.subagents import invoke_subagent

        enabled = state.get("enabled_subagents", [])
        if not enabled:
            return append_trace(state, "subagents.skipped", {"reason": "no_subagents_enabled"})

        subagent_results: list[dict[str, Any]] = []
        for name in enabled:
            result = invoke_subagent(
                name,
                goal=state.get("goal", ""),
                stage_name=state.get("stage_name", ""),
                tool_results=state.get("tool_results", {}),
                previous_stage_result=state.get("previous_stage_result"),
                llm_client=llm_client,
            )
            # Convert dataclass to dict for serialization
            from dataclasses import asdict
            subagent_results.append(asdict(result))

        return append_trace(
            {**state, "subagent_results": subagent_results},
            "subagents.completed",
            {"count": len(subagent_results), "names": enabled},
        )

    def synthesize_result(state: HarnessState) -> HarnessState:
        synthesized_payload: dict[str, Any] = {"source": "tool_results", "tool_count": len(state.get("tool_results", {}))}
        if state.get("skill_name") == "scenario_risk_skill":
            try:
                from src.apps.api.app.services.skill_service import _build_stage_one_summary

                scenario_summary = _build_stage_one_summary(
                    goal=state.get("goal", ""),
                    stage_name=state.get("stage_name", ""),
                    tool_payload=state.get("tool_results", {}),
                    vision_results=state.get("vision_results", []),
                )
                synthesized_payload = {
                    **synthesized_payload,
                    "scenario_summary_candidate": scenario_summary,
                }
            except Exception as exc:
                synthesized_payload = {
                    **synthesized_payload,
                    "summary_build_error": str(exc),
                }
        if state.get("skill_name") == "value_modeling_skill":
            try:
                from src.apps.api.app.services.skill_service import _build_stage_two_summary

                stage2_summary = _build_stage_two_summary(
                    goal=state.get("goal", ""),
                    stage_name=state.get("stage_name", ""),
                    tool_payload=state.get("tool_results", {}),
                    previous_stage_result=state.get("previous_stage_result"),
                )
                synthesized_payload = {
                    **synthesized_payload,
                    "stage2_summary_candidate": stage2_summary,
                }
            except Exception as exc:
                synthesized_payload = {
                    **synthesized_payload,
                    "summary_build_error": str(exc),
                }
        if state.get("skill_name") == "probe_validation_skill":
            try:
                from src.apps.api.app.services.skill_service import _build_stage_three_summary

                stage3_summary = _build_stage_three_summary(
                    goal=state.get("goal", ""),
                    stage_name=state.get("stage_name", ""),
                    tool_payload=state.get("tool_results", {}),
                    previous_stage_result=state.get("previous_stage_result"),
                )
                synthesized_payload = {
                    **synthesized_payload,
                    "stage3_summary_candidate": stage3_summary,
                }
            except Exception as exc:
                synthesized_payload = {
                    **synthesized_payload,
                    "summary_build_error": str(exc),
                }
        if (
            state.get("skill_name") == "scenario_risk_skill"
            and allow_llm_final_decision
            and llm_client.is_configured()
        ):
            try:
                payload = llm_client.complete_json(
                    system_prompt=_resolve_prompt(state, "prompt-stage-1", DEFAULT_SYNTHESIZER_PROMPT),
                    user_payload={
                        "goal": state.get("goal"),
                        "stage_name": state.get("stage_name"),
                        "tool_results": state.get("tool_results", {}),
                    },
                )
                candidate = payload.get("scenario_summary", payload) if isinstance(payload, dict) else None
                if isinstance(candidate, dict) and candidate:
                    synthesized_payload = {
                        **synthesized_payload,
                        "source": "llm",
                        "scenario_summary_candidate": candidate,
                    }
                    return append_trace(
                        {**state, "synthesized_payload": synthesized_payload},
                        "result.synthesized",
                        {"source": "llm", "candidate_fields": sorted(candidate.keys())},
                    )
                state = append_trace(
                    state,
                    "llm.synthesis_invalid",
                    {"reason": "empty_or_non_object_candidate"},
                )
            except Exception as exc:
                state = append_trace(state, "llm.synthesis_failed", {"error": str(exc)})
                synthesized_payload = {**synthesized_payload, "source": "fallback", "error": str(exc)}
        return append_trace(
            {**state, "synthesized_payload": synthesized_payload},
            "result.synthesized",
            {"source": synthesized_payload.get("source", "tool_results")},
        )

    def validate_contract(state: HarnessState) -> HarnessState:
        failures = list(state.get("tool_failures", []))
        requires_human = bool(failures)
        issues: list[dict[str, Any]] = [
            {"code": "tool_failed", "detail": item.get("detail", "")} for item in failures
        ]
        # Validate the current run's synthesized summary, not an input from a
        # prior stage. This makes the graph decision reflect what it produced.
        # scenario_summary contract. This populates validation_issues with
        # structured stage1 issues that have suggested_patches — which the
        # refine_stage1 node uses to drive iterative improvement.
        if state.get("skill_name") == "scenario_risk_skill":
            synthesized = state.get("synthesized_payload") or {}
            scenario_summary = synthesized.get("scenario_summary_candidate", {}) if isinstance(synthesized, dict) else {}
            if scenario_summary:
                try:
                    from src.apps.api.app.services.stage1_contract import (
                        compute_stage1_quality,
                        validate_stage1_summary,
                    )
                    stage1_issues = validate_stage1_summary(scenario_summary)
                    quality = compute_stage1_quality(scenario_summary)
                    # Enrich issues with suggested_patch via the autoresearch
                    # patch builder so refine_stage1 has actionable patches.
                    try:
                        from src.apps.api.app.services.autoresearch_service import (
                            _build_suggested_patch,
                        )
                        for issue in stage1_issues:
                            patch = _build_suggested_patch(
                                issue, scenario_summary, llm_client=llm_client
                            )
                            if patch is not None:
                                issue["suggested_patch"] = patch
                    except Exception:
                        pass
                    issues.extend(stage1_issues)
                    return append_trace(
                        {
                            **state,
                            "validation_issues": issues,
                            "quality_scores": quality,
                            "requires_human": requires_human,
                        },
                        "contract.validated",
                        {
                            "requires_human": requires_human,
                            "issue_count": len(issues),
                            "stage1_issue_count": len(stage1_issues),
                        },
                    )
                except Exception as exc:
                    # Don't fail the run if stage1 validation has issues
                    state = append_trace(
                        state, "contract.stage1_validation_failed", {"error": str(exc)}
                    )
        return append_trace(
            {
                **state,
                "validation_issues": issues,
                "requires_human": requires_human,
            },
            "contract.validated",
            {"requires_human": requires_human, "issue_count": len(issues)},
        )

    def maybe_interrupt(state: HarnessState) -> HarnessState:
        failures = list(state.get("tool_failures", []))
        # ── 3D alignment check — if a binding decision exists and is
        # defer/reject, escalate to human review (overrides the default
        # tool-failure-only check). ──
        from src.apps.api.app.services.alignment_service import (
            compute_3d_alignment,
            should_interrupt_for_human,
        )
        alignment_requires_human = False
        alignment_summary = ""
        confidence = 0.6 if not failures else 0.3
        prev = state.get("previous_stage_result") or {}
        synth = state.get("synthesized_payload", {}) or {}
        previous_scenario = prev.get("scenario_summary", {}) if isinstance(prev, dict) else {}
        s1_payload = synth.get("scenario_summary_candidate", {}) if isinstance(synth, dict) else {}
        s2_payload = synth.get("stage2_summary_candidate", {}) if isinstance(synth, dict) else {}
        s3_payload = synth.get("stage3_summary_candidate", {}) if isinstance(synth, dict) else {}
        previous_stage2 = prev.get("stage2_summary", {}) if isinstance(prev, dict) else {}
        previous_stage3 = prev.get("stage3_summary", {}) if isinstance(prev, dict) else {}
        scenario_summary = s1_payload or previous_scenario
        current_stage2 = s2_payload or previous_stage2
        current_stage3 = s3_payload or previous_stage3
        risk_level = (
            current_stage3.get("risk_level") if isinstance(current_stage3, dict) else None
        ) or (
            current_stage2.get("risk_level") if isinstance(current_stage2, dict) else None
        ) or (scenario_summary.get("risk_level") if isinstance(scenario_summary, dict) else None)
        target_sla = current_stage3.get("target_sla") if isinstance(current_stage3, dict) else None
        if target_sla is None and isinstance(current_stage2, dict):
            target_sla = current_stage2.get("target_sla")
        actual_sla = current_stage3.get("actual_sla") if isinstance(current_stage3, dict) else None
        gap_pct = current_stage3.get("gap_to_target_pct") if isinstance(current_stage3, dict) else None
        alignment = compute_3d_alignment(
            risk_level=risk_level,
            target_sla=target_sla,
            actual_sla=actual_sla,
            gap_to_target_pct=gap_pct,
        )
        if alignment.get("decision") and alignment["decision"] != "insufficient":
            alignment_requires_human = should_interrupt_for_human(alignment)
            alignment_summary = alignment.get("rationale", "")
            if alignment["decision"] == "approve" and not failures:
                confidence = 0.85
            elif alignment["decision"] == "reject":
                confidence = 0.2
            elif alignment["decision"] == "defer":
                confidence = 0.4
        requires_human = bool(state.get("requires_human", False)) or alignment_requires_human
        human_input = state.get("human_input") or {}
        human_approved = human_input.get("approved") if isinstance(human_input, dict) else None
        should_continue = not failures and alignment.get("decision") != "reject"
        notes = [f"{len(failures)} tool failure(s)."] if failures else []
        if alignment_summary and alignment.get("decision") != "insufficient":
            notes.append("3D对齐: {0}".format(alignment_summary))
        if human_approved is not None:
            requires_human = False
            should_continue = bool(human_approved) and not failures and alignment.get("decision") != "reject"
            notes.append("Human review: {0}.".format("approved" if human_approved else "rejected"))
        decision = {
            "should_continue": should_continue,
            "requires_human": requires_human,
            "summary": alignment_summary or ("Fallback decision: completed enabled tools." if not failures else "Fallback decision: tool failures require review."),
            "confidence": confidence,
            "notes": notes,
            "source": "human" if human_approved is not None else ("validator" if state.get("requires_human") else state.get("plan", {}).get("source", "fallback")),
            "3d_alignment": alignment,
        }
        next_state = {**state, "decision": decision, "requires_human": requires_human}
        if human_approved is not None:
            next_state = append_trace(next_state, "harness.human_reviewed", {"approved": bool(human_approved)})
        return append_trace(next_state, "harness.decision", decision)

    def _should_refine(state: HarnessState) -> str:
        """Conditional edge: decide whether to refine the Stage 1 result or proceed to autoresearch.

        Returns "refine_stage1" if the scenario_summary can be automatically improved
        within the configured iteration budget and the case is not blocked by HITL gates.
        Returns "autoresearch" otherwise.
        """
        iteration = int(state.get("refinement_iteration", 0) or 0)
        max_iter = int(state.get("max_refinement_iterations", 2) or 2)
        if iteration >= max_iter:
            return "autoresearch"

        # Check scenario_summary from synthesized_payload (or previous_stage_result fallback)
        prev = state.get("previous_stage_result") or {}
        scenario_summary = prev.get("scenario_summary", {}) if isinstance(prev, dict) else {}
        synth = state.get("synthesized_payload", {}) or {}
        if not scenario_summary and isinstance(synth, dict):
            scenario_summary = synth.get("scenario_summary_candidate", {}) or {}

        # HITL gate: L3 risk, boundary_flag, or L3-confidence >= 0.5 require human review
        risk_level = scenario_summary.get("risk_level", "") if isinstance(scenario_summary, dict) else ""
        boundary_flag = scenario_summary.get("boundary_flag", False) if isinstance(scenario_summary, dict) else False
        risk_confidence = (
            scenario_summary.get("risk_confidence", {}) if isinstance(scenario_summary, dict) else {}
        )
        if risk_level == "L3":
            return "autoresearch"
        if boundary_flag:
            return "autoresearch"
        if (
            risk_level != "L3"
            and isinstance(risk_confidence, dict)
            and float(risk_confidence.get("L3", 0.0) or 0.0) >= 0.5
        ):
            return "autoresearch"

        # Only refine if there are still high-severity issues with suggested patches
        issues = state.get("validation_issues", []) or []
        patchable_high = [
            i for i in issues
            if i.get("severity") == "high" and i.get("suggested_patch")
        ]
        if not patchable_high:
            return "autoresearch"

        return "refine_stage1"

    def refine_stage1(state: HarnessState) -> HarnessState:
        """Apply suggested patches to scenario_summary and re-validate.

        Iterates one round of refinement:
        1. Apply suggested patches from validation_issues
        2. Re-run validate_stage1_summary
        3. Re-run compute_stage1_quality
        4. Record the iteration in refinement_history
        5. Increment refinement_iteration
        6. Create AutoResearchCandidate/RejectedCandidate records for
           reproducibility and auditability
        """
        # Lazy imports — keep them inside the node to avoid circular imports
        from src.apps.api.app.services.autoresearch_service import (
            _WHITELISTED_PATCH_FIELDS,
            _build_suggested_patch,
        )
        from src.apps.api.app.services.stage1_contract import (
            compute_stage1_quality,
            validate_stage1_summary,
        )

        prev = state.get("previous_stage_result") or {}
        scenario_summary = dict(prev.get("scenario_summary", {}) if isinstance(prev, dict) else {})
        if not scenario_summary:
            synth = state.get("synthesized_payload", {}) or {}
            scenario_summary = dict(synth.get("scenario_summary_candidate", {}) or {})

        # Capture before-metrics for candidate records
        metrics_before = dict(state.get("quality_scores", {})) if state.get("quality_scores") else {}
        iteration = int(state.get("refinement_iteration", 0) or 0)

        # Read previously-rejected insights so we don't repeat patches that
        # earlier runs already learned to skip.  This closes the continuous
        # optimisation loop: each new run consumes the rejected candidate
        # buffer left by previous runs.
        from src.apps.api.app.services.autoresearch_service import (
            read_rejected_insights,
        )
        rejected_insights = read_rejected_insights(str(state.get("stage_id", "")))
        previously_rejected_fields: set[str] = set()
        for ri in rejected_insights:
            if (
                ri["rejection_reason"] == "not_whitelisted"
                and "Field '" in ri["insight_text"]
            ):
                # Extract field name from insight text, e.g.
                # "Field 'scenario_name' is not in whitelisted patch fields".
                parts = ri["insight_text"].split("'")
                if len(parts) >= 2 and parts[1]:
                    previously_rejected_fields.add(parts[1])

        # issue_type → change_type mapping
        _CHANGE_TYPE_MAP = {
            "invalid_enum": "enum_normalization",
            "hitl_mismatch": "hitl_alignment",
            "missing_field": "missing_field_add",
            "quality_threshold": "quality_patch",
            "confidence_mismatch": "confidence_realignment",
            "placeholder_content": "content_replacement",
            "weak_evidence": "evidence_binding",
        }

        issues = state.get("validation_issues", []) or []
        applied: list[dict] = []
        rejected: list[dict] = []
        candidate_ids: list[str] = list(state.get("candidate_ids", []) or [])
        rejected_candidate_ids: list[str] = list(state.get("rejected_candidate_ids", []) or [])

        for issue in issues:
            patch = issue.get("suggested_patch")
            if not patch or not isinstance(patch, dict):
                continue
            # Multi-patch or single-patch
            patches_to_apply = []
            op = patch.get("op", "replace")
            if op == "multi":
                patches_to_apply = patch.get("patches", []) or []
            else:
                patches_to_apply = [patch]

            # Determine change_type from issue
            issue_type = issue.get("issue_type", "")
            change_type = _CHANGE_TYPE_MAP.get(issue_type, "quality_patch")
            changed_fields = [p.get("field", "") for p in patches_to_apply]

            # Create candidate record for this issue
            from uuid import uuid4
            from src.apps.api.app.domain.models import AutoResearchCandidate, RejectedCandidate
            from src.apps.api.app.repositories.store import save_autoresearch_candidate, save_rejected_candidate

            candidate = AutoResearchCandidate(
                id=f"cand-{uuid4().hex[:8]}",
                project_id=str(state.get("project_id", "")),
                stage_id=str(state.get("stage_id", "")),
                run_id=str(state.get("run_id", "")),
                change_type=change_type,
                target_stage="stage-1",
                hypothesis=issue.get("message", ""),
                changed_refs=changed_fields,
                expected_effect=issue.get("expected_effect", ""),
                must_not_change=["evidence_refs"],
                status="proposed",
                iteration=iteration,
                metrics_before=metrics_before,
                metrics_after={},
                gate_result="",
                gate_reason="",
                human_review_status="not_required",
            )
            save_autoresearch_candidate(candidate)
            candidate_ids.append(candidate.id)

            all_patches_rejected = True
            for p in patches_to_apply:
                field = p.get("field", "")
                value = p.get("value")
                # Continuous optimisation: skip patches for fields that
                # prior runs already rejected (rejected candidate buffer).
                if field in previously_rejected_fields:
                    rejected.append({
                        "field": field,
                        "reason": "previously_rejected",
                    })
                    # Don't create another RejectedCandidate — the
                    # original rejection record already exists for this
                    # field.  We just skip silently and append to the
                    # local rejected list so the candidate stays marked
                    # all-rejected.
                    continue
                if field not in _WHITELISTED_PATCH_FIELDS:
                    rejected.append({"field": field, "reason": "not_whitelisted"})
                    # Create RejectedCandidate
                    rc = RejectedCandidate(
                        id=f"rc-{uuid4().hex[:8]}",
                        project_id=str(state.get("project_id", "")),
                        stage_id=str(state.get("stage_id", "")),
                        candidate_id=candidate.id,
                        rejection_reason="not_whitelisted",
                        failed_metrics={},
                        hard_constraint_triggered="",
                        reusable_insights=[f"Field '{field}' is not in whitelisted patch fields"],
                        retry_allowed=True,
                    )
                    save_rejected_candidate(rc)
                    rejected_candidate_ids.append(rc.id)
                    continue
                scenario_summary[field] = value
                applied.append({"field": field, "value": value})
                all_patches_rejected = False

            # Update candidate status based on patch outcome
            if all_patches_rejected and patches_to_apply:
                candidate.status = "rejected"
                candidate.gate_result = "fail"
                candidate.gate_reason = "not_whitelisted"
            elif not patches_to_apply:
                # No actual patches — issue had suggested_patch metadata but empty patches
                candidate.status = "rejected"
                candidate.gate_result = "fail"
                candidate.gate_reason = "empty_patch"
            save_autoresearch_candidate(candidate)

        # ── L2: emit RuleProposals for unpatchable issues ─────────────
        # After the patch loop, walk all issues one more time. Issues
        # that had ``suggested_patch = None`` (or whose patch did not
        # apply because it was unpatchable at the data layer) trigger a
        # RuleProposal. These proposals go through human review — they
        # never modify the frozen contract directly.
        from uuid import uuid4 as _uuid4
        from src.apps.api.app.domain.models import RuleProposal
        from src.apps.api.app.services.autoresearch_service import _build_rule_proposal
        from src.apps.api.app.repositories.store import save_rule_proposal

        rule_proposal_ids: list[str] = list(state.get("rule_proposal_ids", []) or [])
        for issue in issues:
            # Only unpatchable quality_threshold issues generate proposals.
            if issue.get("suggested_patch"):
                # This issue had a patchable fix — already handled above.
                continue
            supporting = {
                "observed_value": metrics_before.get(issue.get("field", ""), 0.0),
                "issue_severity": issue.get("severity", "medium"),
                "issue_message": issue.get("message", ""),
            }
            proposal = _build_rule_proposal(
                project_id=str(state.get("project_id", "")),
                stage_id=str(state.get("stage_id", "")),
                run_id=str(state.get("run_id", "")),
                issue=issue,
                supporting_metrics=supporting,
                rationale=(
                    f"Issue {issue.get('field', '')}={issue.get('message', '')} "
                    f"could not be patched at the data layer. Suggest tightening "
                    f"the underlying frozen rule."
                ),
            )
            if proposal is not None:
                save_rule_proposal(proposal)
                rule_proposal_ids.append(proposal.id)

        # Re-validate
        new_issues = validate_stage1_summary(scenario_summary)
        new_quality = compute_stage1_quality(scenario_summary)

        # Post-patch gate check: any high-severity issues introduced?
        high_post = [i for i in new_issues if i.get("severity") == "high"]
        post_patch_failed = len(high_post) > 0 and len(applied) > 0

        # Update candidates with after-metrics and gate results
        if candidate_ids:
            from src.apps.api.app.repositories.store import get_autoresearch_candidate
            for cid in candidate_ids:
                cand = get_autoresearch_candidate(cid)
                if cand and cand.status == "proposed":
                    cand.metrics_after = dict(new_quality)
                    if post_patch_failed:
                        cand.status = "reverted"
                        cand.gate_result = "fail"
                        cand.gate_reason = "post_patch_validation_failed"
                    else:
                        cand.status = "applied"
                        cand.gate_result = "pass"
                    save_autoresearch_candidate(cand)

            # Create RejectedCandidate for post-patch failures
            if post_patch_failed:
                from uuid import uuid4
                from src.apps.api.app.domain.models import RejectedCandidate
                from src.apps.api.app.repositories.store import save_rejected_candidate
                for cid in candidate_ids:
                    cand = get_autoresearch_candidate(cid)
                    if cand and cand.status == "reverted":
                        rc = RejectedCandidate(
                            id=f"rc-{uuid4().hex[:8]}",
                            project_id=str(state.get("project_id", "")),
                            stage_id=str(state.get("stage_id", "")),
                            candidate_id=cand.id,
                            rejection_reason="post_patch_validation_failed",
                            failed_metrics=dict(new_quality),
                            hard_constraint_triggered="",
                            reusable_insights=[
                                f"Post-patch validation introduced {len(high_post)} high-severity issues"
                            ],
                            retry_allowed=True,
                        )
                        save_rejected_candidate(rc)
                        rejected_candidate_ids.append(rc.id)

        # Update previous_stage_result.scenario_summary so downstream sees the refined value
        new_prev: dict[str, Any] = dict(prev) if isinstance(prev, dict) else {}
        new_prev["scenario_summary"] = scenario_summary

        # Append history snapshot
        history = list(state.get("refinement_history", []) or [])
        history.append({
            "iteration": iteration,
            "applied_patches": applied,
            "rejected_patches": rejected,
            "issues_before": len(issues),
            "issues_after": len(new_issues),
            "high_after": sum(1 for i in new_issues if i.get("severity") == "high"),
            "quality": new_quality,
            "candidate_ids": candidate_ids,
            "rejected_candidate_ids": rejected_candidate_ids,
        })

        next_state: HarnessState = {
            **state,
            "previous_stage_result": new_prev,
            "validation_issues": new_issues,
            "quality_scores": new_quality,
            "refinement_iteration": iteration + 1,
            "refinement_history": history,
            "candidate_ids": candidate_ids,
            "rejected_candidate_ids": rejected_candidate_ids,
            "rule_proposal_ids": rule_proposal_ids,
        }
        return append_trace(
            next_state,
            "refinement.iterated",
            {
                "iteration": next_state["refinement_iteration"],
                "applied": len(applied),
                "rejected": len(rejected),
                "high_after": history[-1]["high_after"],
                "candidate_count": len(candidate_ids),
                "rejected_count": len(rejected_candidate_ids),
            },
        )

    graph.add_node("load_context", load_context)
    graph.add_node("plan_tools", plan_tools)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("run_subagents", run_subagents)
    graph.add_node("synthesize_result", synthesize_result)
    graph.add_node("validate_contract", validate_contract)
    graph.add_node("maybe_interrupt", maybe_interrupt)
    graph.add_node("refine_stage1", refine_stage1)
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "plan_tools")
    graph.add_edge("plan_tools", "execute_tools")
    graph.add_edge("execute_tools", "run_subagents")
    graph.add_edge("run_subagents", "synthesize_result")
    graph.add_edge("synthesize_result", "validate_contract")
    graph.add_edge("validate_contract", "maybe_interrupt")

    # --- AutoResearch node ---------------------------------------------------
    def autoresearch(state: HarnessState) -> HarnessState:
        """Generate an AutoResearch record if auto_run_condition permits."""
        condition = state.get("auto_run_condition", "manual")
        if condition == "manual":
            return append_trace(state, "autoresearch.skipped", {"reason": "manual_mode"})

        # Only proceed if there are evidence items (for on_inputs_ready)
        if condition == "on_inputs_ready" and not state.get("evidence_items"):
            return append_trace(state, "autoresearch.skipped", {"reason": "no_inputs_ready"})

        # Extract risk context from previous_stage_result for trace logging
        prev = state.get("previous_stage_result") or {}
        scenario_summary = prev.get("scenario_summary", {}) if isinstance(prev, dict) else {}
        risk_level_trace = scenario_summary.get("risk_level", "")
        boundary_flag_trace = scenario_summary.get("boundary_flag", False)

        record_ids: list[str] = list(state.get("autoresearch_record_ids", []))
        try:
            from src.apps.api.app.services.autoresearch_service import create_autoresearch_record

            stage_id = str(state.get("stage_id", ""))
            run_id = str(state.get("run_id", ""))
            if stage_id and run_id:
                record = create_autoresearch_record(stage_id=stage_id, run_id=run_id, auto_run_condition=condition)
                record_ids.append(record.id)
                gate_blocked = record.context.get("autoresearch_gate_blocked", False)
                gate_reason = record.context.get("autoresearch_gate_reason", "")
                trace_data: dict[str, Any] = {
                    "record_id": record.id,
                    "condition": condition,
                    "risk_level": risk_level_trace,
                    "boundary_flag": boundary_flag_trace,
                }
                if gate_blocked:
                    trace_data["gate_blocked"] = True
                    trace_data["gate_reason"] = gate_reason
                return append_trace(
                    {**state, "autoresearch_record_ids": record_ids},
                    "autoresearch.generated",
                    trace_data,
                )
        except Exception as exc:
            # Don't fail the run if autoresearch has an issue
            return append_trace(state, "autoresearch.failed", {"error": str(exc)})

        return state

    # Rewire: maybe_interrupt -> _should_refine (conditional) -> refine_stage1 | autoresearch
    # If refine_stage1 runs, it loops back to validate_contract → maybe_interrupt.
    # Otherwise it proceeds to autoresearch → END.
    graph.add_node("autoresearch", autoresearch)
    graph.add_conditional_edges(
        "maybe_interrupt",
        _should_refine,
        {
            "refine_stage1": "refine_stage1",
            "autoresearch": "autoresearch",
        },
    )
    graph.add_edge("refine_stage1", "validate_contract")
    graph.add_edge("autoresearch", END)

    # Determine effective interrupt_before
    effective_interrupt = interrupt_before
    if effective_interrupt is None and checkpointer is not None:
        effective_interrupt = ["maybe_interrupt"]

    compile_kwargs: dict[str, Any] = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    if effective_interrupt:
        compile_kwargs["interrupt_before"] = effective_interrupt

    return graph.compile(**compile_kwargs)
