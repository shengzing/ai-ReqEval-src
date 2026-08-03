"""Runtime for stage conversation harness.

Primary path: LLM-driven multi-turn replies via :func:`answer_with_llm`.
Fallback path: rule-based :func:`classify_intent` + branch answers, used when
LLM is not configured or fails.
"""

from __future__ import annotations

import logging
from typing import Any

from src.apps.api.app.agents.conversation_harness.adapters.context_tool_adapter import (
    ConversationContextToolAdapter,
)
from src.apps.api.app.agents.conversation_harness.contracts import (
    ConversationActionProposal,
    ConversationHarnessRequest,
)
from src.apps.api.app.agents.harness.llm import HarnessLLMClient
from src.apps.api.app.agents.harness.state import NO_LLM_FALLBACK_MESSAGE


logger = logging.getLogger(__name__)

RUNTIME_VERSION = "conversation-simple-runtime-v1"

DEFAULT_CONVERSATION_PROMPT = (
    "你是 AI ReqEval 的阶段对话助手。请基于所提供的项目上下文、阶段上下文、"
    "最新阶段结果、证据摘要、历史消息等上下文，用中文回答用户当前的问题。\n\n"
    "必须返回如下 JSON 结构：\n"
    '{"reply": "给用户的中文回复", "action_proposals": []}\n\n'
    "回复要求：始终用中文；引用上下文中的具体信息，不要编造上下文中没有的内容；"
    "不确定时在 reply 中标注“待确认”；回复聚焦用户问题，简洁清晰。\n\n"
    "受控动作要求：仅当用户明确要求重新分析 / 重跑 / 再跑一次时，才在 "
    "action_proposals 放入一个对象："
    '{"action_type": "propose_create_run", "title": "创建阶段分析任务", '
    '"payload": {"goal": "用户原话"}, "requires_confirmation": true}；'
    "其他情况 action_proposals 必须为空数组。"
)


def classify_intent(user_message: str) -> dict[str, Any]:
    if not user_message:
        return {"type": "unknown", "confidence": 0.0}
    # Chinese characters are case-insensitive under .lower(); English
    # keywords are matched against the lowercased text so "Stage" and "stage"
    # hit alike.
    text = user_message.lower()
    # explain_result is checked before request_run so that phrases like
    # "请解释执行结果的风险等级" match explain_result instead of being pulled
    # into request_run by the broad "执行" keyword.
    if any(keyword in text for keyword in ["为什么", "风险等级", "判成", "结果", "结论", "l1", "l2", "l3"]):
        return {"type": "explain_result", "confidence": 0.82}
    if any(keyword in text for keyword in ["重新分析", "重新执行", "重跑", "再跑一次", "重新跑"]):
        return {"type": "request_run", "confidence": 0.9}
    if any(keyword in text for keyword in ["当前阶段", "阶段", "项目", "目标", "证据", "skill", "技能"]) or any(
        keyword in text for keyword in ["stage", "project", "skill", "context"]
    ):
        return {"type": "ask_context", "confidence": 0.78}
    return {"type": "unknown", "confidence": 0.45}


def answer_with_llm(
    request: ConversationHarnessRequest,
    tools: ConversationContextToolAdapter,
) -> dict[str, Any] | None:
    """LLM 驱动的多轮对话回复。

    返回 None 表示 LLM 未配置或调用失败/返回空，调用方应回退到规则分支。
    返回 dict 时含 ``llm_used: True`` 标记，供 provider 写 traces。

    LLM 客户端优先从项目 settings(后端已配的语言模型/多模态模型/裁判模型)
    实例化,不再依赖全局 ``AGENT_LLM_*`` env。回退顺序:
    1. ``request.options["settings_snapshot"]["openai_compatible_models_with_secrets"]["general"]``
    2. ``HarnessLLMClient()`` 读 env(向后兼容)
    """
    llm = _build_llm_client(request)
    if not llm or not llm.is_configured():
        logger.warning(
            "[conversation_harness] answer_with_llm: LLM not configured, will fallback. "
            "project_id=%s stage_id=%s conversation_id=%s",
            request.project_id, request.stage_id, request.conversation_id,
        )
        return None

    system_prompt = request.prompt_templates.get(
        "prompt-conversation-reply", DEFAULT_CONVERSATION_PROMPT
    )

    user_payload = {
        "project_context": request.project_context,
        "stage_context": request.stage_context,
        "latest_stage_result": request.latest_stage_result,
        "evidence_summaries": request.evidence_summaries,
        "recent_run_events": request.recent_run_events,
        "available_skills": request.available_skills,
        "message_history": request.message_history,
        "user_message": request.user_message,
    }

    logger.info(
        "[conversation_harness] answer_with_llm: calling LLM model=%s base_url=%s "
        "project_id=%s stage_id=%s conversation_id=%s user_message_preview=%r",
        llm.model, llm.base_url, request.project_id, request.stage_id,
        request.conversation_id, request.user_message[:80],
    )

    try:
        data = llm.complete_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            temperature=0.4,
        )
    except Exception as exc:
        logger.warning(
            "[conversation_harness] answer_with_llm: LLM call FAILED model=%s "
            "error=%s: %s. Will fallback.",
            llm.model, type(exc).__name__, exc,
            exc_info=True,
        )
        return None

    if not data:
        logger.warning(
            "[conversation_harness] answer_with_llm: LLM returned empty data. Will fallback."
        )
        return None
    if not data.get("reply"):
        logger.warning(
            "[conversation_harness] answer_with_llm: LLM returned no 'reply' field. data_keys=%s. Will fallback.",
            list(data.keys()),
        )
        return None

    logger.info(
        "[conversation_harness] answer_with_llm: LLM success. reply_preview=%r action_proposals=%d",
        str(data["reply"])[:80], len(data.get("action_proposals") or []),
    )

    # 过滤掉非法 action_proposals:下游 save_action_proposals 用 proposal["action_type"]
    # 直接下标访问,缺少 action_type 会抛 KeyError 触发 500。这里只保留含非空
    # action_type 的 dict,丢弃 LLM 偶发的畸形 proposal,保证 reply 仍能返回。
    raw_proposals = data.get("action_proposals") or []
    cleaned_proposals: list[dict[str, Any]] = []
    for proposal in raw_proposals:
        if not isinstance(proposal, dict):
            continue
        action_type = proposal.get("action_type")
        if not action_type:
            continue
        cleaned_proposals.append(proposal)

    return {
        "assistant_message": str(data["reply"]),
        "citations": [],
        "warnings": [],
        "action_proposals": cleaned_proposals,
        "llm_used": True,
    }


def rule_based_fallback(
    request: ConversationHarnessRequest,
    tools: ConversationContextToolAdapter,
) -> dict[str, Any]:
    """规则 fallback：classify_intent 分流到现有模板分支，LLM 不可用时使用。"""
    intent = classify_intent(request.user_message)
    if intent["type"] == "ask_context":
        answer = answer_context(request, tools)
    elif intent["type"] == "explain_result":
        answer = explain_result(request, tools)
    elif intent["type"] == "request_run":
        answer = propose_run(request)
    else:
        answer = fallback_answer(request)
    answer["intent"] = intent
    return answer


def answer_context(request: ConversationHarnessRequest, tools: ConversationContextToolAdapter) -> dict[str, Any]:
    stage = tools.call("read_stage_context", reason="answer current stage question")
    project = tools.call("read_project_context", reason="answer project context question")
    evidence = tools.call("list_evidence_summaries", reason="summarize available evidence")
    skills = tools.call("list_available_skills", reason="summarize available skills")

    stage_context = stage.output
    project_context = project.output
    evidence_count = len(evidence.output.get("items", []))
    skill_names = [item.get("name") for item in skills.output.get("items", []) if item.get("name")]
    message = (
        f"当前处于 {stage_context.get('name', request.stage_id)}，"
        f"阶段目标是：{stage_context.get('objective') or '未配置'}。"
        f"项目是 {project_context.get('name', request.project_id)}，"
        f"项目目标是：{project_context.get('goal') or '未配置'}。"
        f"当前可参考 {evidence_count} 条证据摘要。"
    )
    if skill_names:
        message += f"可用 Skill：{', '.join(skill_names)}。"
    return {
        "assistant_message": message,
        "citations": [
            {"source": "stage_context", "id": stage_context.get("id"), "field": "objective"},
            {"source": "project_context", "id": project_context.get("id"), "field": "goal"},
        ],
    }


def explain_result(request: ConversationHarnessRequest, tools: ConversationContextToolAdapter) -> dict[str, Any]:
    result = tools.call("read_latest_stage_result", reason="explain latest stage result")
    latest = result.output
    if not latest:
        return {
            "assistant_message": "当前阶段还没有阶段结果，因此无法解释风险等级或结论。可以先创建阶段分析任务。",
            "citations": [],
            "warnings": [{"code": "missing_stage_result", "message": "No latest stage result."}],
        }

    payload = latest.get("result_payload", {}) or {}
    scenario = payload.get("scenario_summary", {}) or {}
    risk_level = scenario.get("risk_level")
    hitl_level = scenario.get("hitl_level")
    rationale = scenario.get("risk_rationale")
    rationale_field = "result_payload.scenario_summary.risk_rationale"
    if not rationale:
        rationale = scenario.get("rationale")
        rationale_field = "result_payload.scenario_summary.rationale"
    if not rationale:
        rationale = latest.get("summary")
        rationale_field = "summary"
    if not rationale:
        rationale = "阶段结果中未给出明确理由。"
        rationale_field = None
    parts = []
    if risk_level:
        parts.append(f"当前风险等级是 {risk_level}")
    if hitl_level:
        parts.append(f"HITL 要求是 {hitl_level}")
    parts.append(f"主要依据：{rationale}")
    citations = [
        {"source": "latest_stage_result", "id": latest.get("id"), "field": "result_payload.scenario_summary.risk_level"}
    ]
    if rationale_field:
        citations.append(
            {"source": "latest_stage_result", "id": latest.get("id"), "field": rationale_field}
        )
    return {
        "assistant_message": "；".join(parts) + "。",
        "citations": citations,
        "warnings": [],
    }


def propose_run(request: ConversationHarnessRequest) -> dict[str, Any]:
    proposal = ConversationActionProposal(
        action_type="propose_create_run",
        title="创建阶段分析任务",
        payload={
            "project_id": request.project_id,
            "stage_id": request.stage_id,
            "conversation_id": request.conversation_id,
            "goal": request.user_message,
            "config_version_id": request.config_version_id,
        },
        requires_confirmation=True,
    )
    return {
        "assistant_message": "我可以为当前阶段创建一次新的阶段分析任务。该操作需要确认后再执行，不会由对话 Harness 直接写入阶段结果。",
        "action_proposals": [proposal.to_dict()],
    }


def fallback_answer(request: ConversationHarnessRequest) -> dict[str, Any]:
    stage_name = request.stage_context.get("name") or request.stage_id
    return {
        "assistant_message": (
            f"我可以基于当前项目和 {stage_name} 的上下文回答问题，"
            "也可以解释最新阶段结果；如果需要重新分析，我会先给出待确认的任务建议。"
        )
    }


def run_with_llm_fallback(
    request: ConversationHarnessRequest,
    *,
    extra_traces: list[dict[str, Any]] | None = None,
    extra_warnings: list[dict[str, Any]] | None = None,
    fallback_warnings: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """统一调度：LLM 优先，未配置/失败回退规则分支。

    返回 ``(answer, traces, warnings, tool_calls, raw)``，供 provider 组装
    :class:`ConversationHarnessResult`。

    - ``answer``: 含 ``assistant_message``/``citations``/``warnings``/``action_proposals``，
      LLM 路径额外带 ``llm_used: True``，规则路径带 ``intent``。
    - ``traces``: 含 ``llm_reply`` 步骤（记录 configured/success）。``extra_traces``
      无条件前置，适合记录 adapter 标识等恒定信息。
    - ``warnings``: LLM 未配置记 ``llm_not_configured``，失败记 ``llm_call_failed``。
      ``extra_warnings`` 无条件前置；``fallback_warnings`` 仅在走规则回退时追加，
      用于"当前是规则 fallback"这类仅在非 LLM 路径才成立的声明,避免 LLM 成功时
      仍误报"正在使用规则 fallback"。
    - ``raw``: ``{"llm_used": bool, "tool_names": list[str]}``，供审计与 adapter 补
      ``allowed_tools`` 字段。

    版本兼容: ``fallback_warnings`` / ``raw.tool_names`` 为本次新增,旧调用方不传
    ``fallback_warnings`` 时按原行为(仅在回退分支加 llm_not_configured/llm_call_failed)。
    """
    tools = ConversationContextToolAdapter(request)
    tool_names = sorted(tools._tools.keys())
    traces: list[dict[str, Any]] = list(extra_traces or [])
    warnings: list[dict[str, Any]] = list(extra_warnings or [])

    llm_answer = answer_with_llm(request, tools)
    if llm_answer is not None:
        answer = llm_answer
        traces.append({"step": "llm_reply", "configured": True, "success": True})
        raw = {"llm_used": True, "tool_names": tool_names}
    else:
        configured = _is_llm_configured(request)
        if not configured:
            warnings.append({"code": "llm_not_configured", "message": NO_LLM_FALLBACK_MESSAGE})
        else:
            warnings.append({"code": "llm_call_failed", "message": "LLM 调用失败或返回空，已回退规则分支。"})
        # fallback_warnings 只在回退分支追加:此处的 adapter 警告(如
        # "Using rule-based fallback")只在真正走规则分支时才成立。
        warnings.extend(fallback_warnings or [])
        traces.append({"step": "llm_reply", "configured": configured, "success": False})
        answer = rule_based_fallback(request, tools)
        raw = {"llm_used": False, "tool_names": tool_names}

    warnings.extend(answer.get("warnings", []))
    return answer, traces, warnings, list(tools.tool_calls), raw


def _build_llm_client(request: ConversationHarnessRequest) -> HarnessLLMClient | None:
    """从项目 settings 里的语言模型(general role)构造 LLM 客户端。

    回退到 ``HarnessLLMClient()`` 读 env(向后兼容)。返回 None 仅当无任何可用配置。
    """
    snapshot = (request.options or {}).get("settings_snapshot") or {}
    ocm = snapshot.get("openai_compatible_models_with_secrets") or {}
    general = ocm.get("general") or {}
    base_url = general.get("base_url") or None
    api_key = general.get("api_key") or None
    model = general.get("model_name") or None
    # reasoning_mode 缺省 True 兼容旧 settings(未持久化该字段)。
    # False 时 HarnessLLMClient.complete_json 会附 extra_body + system 指令
    # 关掉推理链,直接返回干净 JSON。
    reasoning_mode = bool(general.get("reasoning_mode", True))
    logger.info(
        "[conversation_harness] _build_llm_client: project settings general model_name=%s base_url=%s "
        "api_key_set=%s reasoning_mode=%s",
        model, base_url, bool(api_key), reasoning_mode,
    )
    # A default model name without endpoint credentials is a placeholder from
    # project settings, not a usable project-level override. In that case use
    # the complete AGENT_LLM_* configuration instead of mixing providers.
    if base_url and api_key:
        return HarnessLLMClient(
            base_url=base_url, api_key=api_key, model=model, reasoning_mode=reasoning_mode,
        )
    # 项目 settings 没配 general 模型 → 回退读 env(AGENT_LLM_* / OPENAI_*)
    logger.info("[conversation_harness] _build_llm_client: no project general model, falling back to env")
    return HarnessLLMClient(reasoning_mode=reasoning_mode)


def _is_llm_configured(request: ConversationHarnessRequest) -> bool:
    """判断当前请求是否有可用的 LLM 配置(项目 settings 或 env 任一即可)。"""
    client = _build_llm_client(request)
    return bool(client and client.is_configured())
