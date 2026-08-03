"""OpenHarness conversation adapter skeleton.

LLM path is shared with simple_v1 via :func:`run_with_llm_fallback`; the
adapter overlay records ``openharness_adapter`` traces with the read-only
tool allowlist and denied tool classes.
"""

from __future__ import annotations

from typing import Any

from src.apps.api.app.agents.conversation_harness.contracts import (
    ConversationHarnessRequest,
    ConversationHarnessResult,
)
from src.apps.api.app.agents.conversation_harness.versions.simple_v1.runtime import (
    run_with_llm_fallback,
)


RUNTIME_VERSION = "conversation-openharness-adapter-v1"
READ_ONLY_TOOL_ALLOWLIST = [
    "list_available_skills",
    "list_evidence_summaries",
    "list_recent_run_events",
    "read_latest_stage_result",
    "read_project_context",
    "read_stage_context",
]
DENIED_TOOL_CLASSES = ["bash", "file_write", "web", "mcp", "unscoped_database_write"]


class ConversationOpenHarnessV1Provider:
    version = "conversation-openharness-v1"

    def run(self, request: ConversationHarnessRequest) -> ConversationHarnessResult:
        adapter_traces = [
            {
                "step": "openharness_adapter",
                "mode": "fallback",
                "permission_profile": {
                    "read_only_tool_allowlist": list(READ_ONLY_TOOL_ALLOWLIST),
                    "denied_tool_classes": list(DENIED_TOOL_CLASSES),
                },
                "hook_mapping": {
                    "before_tool": "validate allowlist and request scope",
                    "after_tool": "record tool result in ConversationHarnessResult.tool_calls",
                    "before_effect": "convert writes into action_proposals",
                },
            }
        ]
        # adapter 警告("正在使用规则 fallback")只在走规则回退分支时才成立,
        # 放 fallback_warnings 避免在 LLM 成功路径误报。
        fallback_warnings = [
            {
                "code": "openharness_runtime_not_configured",
                "message": "Using rule-based fallback under the OpenHarness adapter contract.",
            }
        ]

        answer, traces, warnings, tool_calls, raw = run_with_llm_fallback(
            request,
            extra_traces=adapter_traces,
            fallback_warnings=fallback_warnings,
        )

        result = ConversationHarnessResult(
            conversation_harness_version=self.version,
            runtime_version=RUNTIME_VERSION,
            assistant_message=answer["assistant_message"],
            intent=answer.get("intent", {"type": "llm"} if raw.get("llm_used") else {"type": "unknown"}),
            citations=list(answer.get("citations", [])),
            tool_calls=tool_calls,
            action_proposals=list(answer.get("action_proposals", [])),
            effects=[],
            traces=traces,
            warnings=warnings,
            raw={"adapter": "openharness", "llm_used": raw.get("llm_used", False)},
        )
        result.to_dict()
        return result
