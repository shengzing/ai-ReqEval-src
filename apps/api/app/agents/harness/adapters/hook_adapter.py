"""Hook adapter for harness providers (HVS-P1-02).

4 事件：before_harness / before_tool / after_tool / after_harness。
回调返回 dict → 追加 hook.<event> trace；返回 None → 不追加；抛异常 → 追加 hook.warning trace。
HookAdapter.trigger 永不 re-raise（spec："hook 异常不导致 Harness 崩溃"）。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


HookEvent = Literal["before_harness", "before_tool", "after_tool", "after_harness"]
HookCallback = Callable[[HookEvent, dict[str, Any]], "dict[str, Any] | None"]


@dataclass
class HookTrace:
    """Hook 回调产生的 trace 条目（event=payload 形式）。"""

    event: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"event": self.event, "payload": dict(self.payload)}


class HookAdapter:
    """4 事件 hook 适配器；无回调时 trigger 返回空列表（行为等同未接 hook）。"""

    def __init__(
        self,
        *,
        callbacks: dict[str, list[HookCallback]] | None = None,
    ) -> None:
        self._callbacks: dict[str, list[HookCallback]] = defaultdict(list)
        if callbacks:
            for event, cbs in callbacks.items():
                self._callbacks[event].extend(cbs)

    def register(self, event: HookEvent, callback: HookCallback) -> None:
        self._callbacks[event].append(callback)

    def trigger(self, event: HookEvent, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """触发 event 的所有回调；返回 trace dict 列表（不修改入参 payload）。

        - 回调返回 dict → 追加 {"event": f"hook.{event}", "payload": returned_dict}
        - 回调返回 None → 不追加
        - 回调抛异常 → 追加 {"event": "hook.warning", "payload": {"hook_event", "error", "callback_index"}}
        - 永不 re-raise
        """
        traces: list[dict[str, Any]] = []
        for index, callback in enumerate(self._callbacks.get(event, [])):
            try:
                returned = callback(event, dict(payload))
            except Exception as exc:  # noqa: BLE001 — hook 异常必须降级为 warning trace
                traces.append(
                    {
                        "event": "hook.warning",
                        "payload": {
                            "hook_event": event,
                            "error": str(exc),
                            "callback_index": index,
                        },
                    }
                )
                continue
            if isinstance(returned, dict):
                traces.append({"event": f"hook.{event}", "payload": dict(returned)})
        return traces
