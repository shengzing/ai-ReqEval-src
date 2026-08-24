"""Provider for Honeycomb v1 (P1 完整版)."""

from __future__ import annotations

from src.apps.api.app.agents.harness.adapters.hook_adapter import HookAdapter
from src.apps.api.app.agents.harness.adapters.llm_adapter import LLMAdapter
from src.apps.api.app.agents.harness.adapters.permission_adapter import PermissionAdapter
from src.apps.api.app.agents.harness.adapters.tool_adapter import ToolAdapter
from src.apps.api.app.agents.harness.contracts import HarnessRequest, HarnessResult
from src.apps.api.app.agents.harness.versions.honeycomb_v1.runtime import HoneycombV1Runtime


class HoneycombV1HarnessProvider:
    version = "honeycomb-v1"

    def __init__(
        self,
        *,
        tool_adapter: ToolAdapter | None = None,
        permission_adapter: PermissionAdapter | None = None,
        hook_adapter: HookAdapter | None = None,
        llm_adapter: LLMAdapter | None = None,
    ) -> None:
        self._tool_adapter = tool_adapter
        self._permission_adapter = permission_adapter
        self._hook_adapter = hook_adapter
        self._llm_adapter = llm_adapter

    def run(self, request: HarnessRequest) -> HarnessResult:
        # per-request adapter 解析；优先 request.options 注入，回退构造期注入，再回退默认
        permission_adapter = (
            request.options.get("permission_adapter")
            or self._permission_adapter
            or PermissionAdapter()
        )
        tool_adapter = (
            request.options.get("tool_adapter")
            or self._tool_adapter
            or ToolAdapter(tool_invoker=request.options.get("tool_invoker"))
        )
        hook_adapter = (
            request.options.get("hook_adapter") or self._hook_adapter or HookAdapter()
        )

        # llm_adapter 解析顺序：构造期注入 > request.options["llm_adapter"]
        # > request.options["llm_client"] 包成 LLMAdapter > runtime 内默认 LLMAdapter()
        llm_adapter = self._llm_adapter or request.options.get("llm_adapter")
        if llm_adapter is None and request.options.get("llm_client") is not None:
            llm_adapter = LLMAdapter(llm_client=request.options["llm_client"])

        runtime = HoneycombV1Runtime(
            tool_adapter=tool_adapter,
            permission_adapter=permission_adapter,
            hook_adapter=hook_adapter,
            llm_adapter=llm_adapter,
        )
        return runtime.run(request)
