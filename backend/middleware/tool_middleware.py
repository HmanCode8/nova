"""工具链路中间件（FINAL_DEVELOPMENT_DOC 第四章 Middleware 层）。

统一收口所有工具调用（内置工具 + 后续 MCP 工具）的横切逻辑，顺序固定：

    begin(Trace) → 硬校验（白名单/后缀/参数） → 删除拦截 interrupt()
      → 执行工具 → finish(Trace)

设计原则：
- 只做拦截、校验、埋点、异常捕获，不承载 Agent 决策
- 通过 interrupt() 实现的删除确认必须在本层完成，保证「任何工具都绕不过去」
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import AnyMessage, ToolMessage
from langgraph.types import interrupt

from backend.storage import trace_store
from backend.tools.tool_hook import (
    build_confirm_payload,
    hard_validate,
    needs_confirmation,
    summarize_tool_result,
)

# 循环熔断：同一工具 + 相同参数超过该次数即拦截，避免模型反复重试同一失败操作
MAX_SAME_CALL = 2


class ToolMiddleware:
    """一次对话轮次内的工具调用中间件状态容器。"""

    def __init__(
        self,
        session_id: str,
        tool_map: dict[str, Any],
        task_id: str = "",
        loop_hint: str = "",
    ) -> None:
        self.session_id = session_id
        self.task_id = task_id
        self.tool_map = tool_map
        self.loop_hint = loop_hint

    # -- 前置：确认 / 硬校验 / Trace 开始 ----------------------------------

    async def prepare(self, state: dict[str, Any]) -> dict[str, Any]:
        """gate 节点：先硬校验，再对需要确认的工具逐个 interrupt。"""
        last = (state.get("messages") or [None])[-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        rejected = list(state.get("rejected_call_ids") or [])
        blocked = dict(state.get("blocked_calls") or {})

        for call in calls:
            call_id = call.get("id") or ""
            name = call.get("name", "")
            args = dict(call.get("args") or {})
            if call_id in rejected:
                continue

            trace_id = await trace_store.begin(
                self.session_id, call_id, name, args, self.task_id
            )

            if not await needs_confirmation(name, args):
                continue

            error = await hard_validate(name, args)
            if error:
                # 硬校验失败：不弹确认，直接拒绝并留痕
                blocked[call_id] = error
                await trace_store.finish(trace_id, trace_store.STATUS_BLOCKED, error)
                continue

            await trace_store.mark(trace_id, trace_store.STATUS_WAITING)
            payload = build_confirm_payload(name, args)
            decision = interrupt(payload)
            accepted = (
                bool(decision.get("accepted")) if isinstance(decision, dict) else bool(decision)
            )
            if accepted:
                await trace_store.mark(trace_id, trace_store.STATUS_CONFIRMED)
            else:
                rejected.append(call_id)
                await trace_store.finish(trace_id, trace_store.STATUS_CANCELLED, "用户已取消本次操作。")

        return {"rejected_call_ids": rejected, "blocked_calls": blocked}

    # -- 执行：循环熔断 / 调用工具 / Trace 结束 ------------------------------

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """tools 节点：真正执行工具，只跑一次。"""
        last = (state.get("messages") or [None])[-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        rejected = set(state.get("rejected_call_ids") or [])
        blocked = dict(state.get("blocked_calls") or {})
        counts = dict(state.get("tool_counts") or {})
        total = int(state.get("tool_total") or 0)
        results: list[AnyMessage] = []

        for call in calls:
            call_id = call.get("id") or ""
            name = call.get("name") or ""
            args = dict(call.get("args") or {})
            trace_id = trace_store.trace_id_for(self.session_id, call_id)

            if call_id in rejected:
                results.append(
                    ToolMessage(content="用户已取消本次操作。", tool_call_id=call_id, name=name)
                )
                continue

            if call_id in blocked:
                results.append(
                    ToolMessage(
                        content=f"操作被拒绝：{blocked[call_id]}",
                        tool_call_id=call_id,
                        name=name,
                    )
                )
                continue

            signature = f"{name}|{_signature(args)}"
            counts[signature] = counts.get(signature, 0) + 1
            total += 1
            if counts[signature] > MAX_SAME_CALL:
                message = self.loop_hint.format(limit=MAX_SAME_CALL) if self.loop_hint else (
                    f"系统拦截：该工具用相同参数已重复调用 {MAX_SAME_CALL} 次，已停止执行。"
                    "请不要再调用同一个工具，直接基于已有结果回答用户。"
                )
                await trace_store.finish(trace_id, trace_store.STATUS_BLOCKED, message)
                results.append(ToolMessage(content=message, tool_call_id=call_id, name=name))
                continue

            tool = self.tool_map.get(name)
            if tool is None:
                message = f"工具不存在：{name}"
                await trace_store.finish(trace_id, trace_store.STATUS_FAILED, message)
                results.append(ToolMessage(content=message, tool_call_id=call_id, name=name))
                continue

            try:
                output = await tool.ainvoke(args)
                content = summarize_tool_result(output)
                await trace_store.finish(trace_id, trace_store.STATUS_SUCCESS, content)
            except Exception as exc:  # 工具异常不打断整轮对话
                content = f"工具执行失败：{exc}"
                await trace_store.finish(trace_id, trace_store.STATUS_FAILED, content)
            results.append(ToolMessage(content=content, tool_call_id=call_id, name=name))

        return {
            "messages": results,
            "rejected_call_ids": [],
            "blocked_calls": {},
            "tool_counts": counts,
            "tool_total": total,
        }


def _signature(args: dict[str, Any]) -> str:
    import json

    return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)


def build_middleware(
    session_id: str, tool_map: dict[str, Any], task_id: str = "", loop_hint: str = ""
) -> ToolMiddleware:
    return ToolMiddleware(session_id, tool_map, task_id=task_id, loop_hint=loop_hint)


def trace_of(state: dict[str, Any]) -> Optional[str]:
    """预留：任务级 trace 关联 id 的读取入口。"""
    return state.get("trace_id")
