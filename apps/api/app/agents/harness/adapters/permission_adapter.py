"""Permission adapter for harness providers (HVS-P1-01).

第一版只做工具级 allowlist + 只读/写入分类，不做路径级检查。
Honeycomb runtime 在每次 ToolAdapter.invoke 之前调用 PermissionAdapter.check；
deny 时不执行工具，返回结构化 tool_failure（code="permission_denied"）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.apps.api.app.agents.harness.contracts import HarnessRequest, HarnessToolCall


PermissionCategory = Literal["read", "write"]


@dataclass
class PermissionDecision:
    """Permission check result.

    - allowed=False 时 reason 取 "tool_not_in_enabled_tools" 或 "tool_not_in_allowed_tools"
    - allowed=True 时 reason="ok"，category 标 read/write（无 write_tools 配置时统一为 read）
    """

    allowed: bool
    reason: str
    category: PermissionCategory | None


class PermissionAdapter:
    """Tool allowlist + 只读/写入分类适配器。

    第一版不做路径级检查；write_tools 缺省空集（所有工具归 read），
    分类能力由调用方注入 write_tools 集合显式启用。
    """

    def __init__(self, *, write_tools: set[str] | None = None) -> None:
        self._write_tools: set[str] = set(write_tools or [])

    def check(self, request: HarnessRequest, call: HarnessToolCall) -> PermissionDecision:
        if call.tool_name not in request.enabled_tools:
            return PermissionDecision(allowed=False, reason="tool_not_in_enabled_tools", category=None)
        if request.allowed_tools and call.tool_name not in request.allowed_tools:
            return PermissionDecision(allowed=False, reason="tool_not_in_allowed_tools", category=None)
        category: PermissionCategory = "write" if call.tool_name in self._write_tools else "read"
        return PermissionDecision(allowed=True, reason="ok", category=category)

    def build_denied_result(self, call: HarnessToolCall, decision: PermissionDecision) -> dict[str, Any]:
        """构造 permission deny 的 HarnessToolResult.failure dict（与 ToolAdapter failure 形状一致）。

        返回完整 failure dict，调用方包装成 HarnessToolResult。
        """
        return {
            "code": "permission_denied",
            "reason": decision.reason,
            "detail": f"Permission denied: {decision.reason}",
            "payload": dict(call.payload),
        }
