"""LangGraph 主图：手写 StateGraph + 原生 interrupt 人工确认。

图结构：
    START → load_context → agent ⇄ gate → tools → agent → END

- load_context：前置节点，组装 system prompt（M7 注入记忆、M8 加 token 检查）
- agent：调用绑定工具的 LLM
- gate：副作用工具在此 interrupt() 暂停，等待前端确认；无副作用工具直接放行
- tools：真正执行工具，只跑一次，避免 interrupt 恢复导致副作用重复执行

说明：不用 langchain.agents.middleware，也不回退 create_react_agent 黑盒。
"""

from __future__ import annotations

from typing import Annotated, Any, Optional, Sequence, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from backend.agent.prompts import build_system_prompt
from backend.storage import memory_store, project_store
from backend.tools.tool_hook import (
    build_confirm_payload,
    hard_validate,
    needs_confirmation,
    summarize_tool_result,
)


class AgentState(TypedDict, total=False):
    """图运行时 state（内存级，不直接持久化）。"""

    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    system_prompt: str
    history_summary: str
    rejected_call_ids: list[str]
    blocked_calls: dict[str, str]


# 项目模式需要多步工具循环（计划 → 批量写文件 → 更新进度），默认 25 步不够用
RECURSION_LIMIT = 60


def thread_config(session_id: str) -> dict[str, Any]:
    """checkpointer 线程配置：一个会话一个 thread_id。"""
    return {"configurable": {"thread_id": session_id}, "recursion_limit": RECURSION_LIMIT}


def extract_interrupt(result: Any) -> Optional[dict[str, Any]]:
    """从 ainvoke 结果里取出 interrupt 载荷（有中断时返回 dict）。"""
    if not isinstance(result, dict):
        return None
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}


def _conversation(state: AgentState) -> list[AnyMessage]:
    """过滤历史中的 SystemMessage，system prompt 由前置节点统一注入。"""
    return [m for m in state.get("messages") or [] if not isinstance(m, SystemMessage)]


def build_agent(
    model: BaseChatModel,
    tools: Optional[Sequence[Any]] = None,
    checkpointer: Optional[Any] = None,
):
    """构建并编译 Agent 图。checkpointer 默认使用进程内 InMemorySaver。"""
    tool_list = list(tools or [])
    tool_map = {tool.name: tool for tool in tool_list}
    bound_model = model.bind_tools(tool_list) if tool_list else model

    async def load_context(state: AgentState) -> dict[str, Any]:
        """前置节点：注入记忆 + 历史摘要 + 组装 system prompt。"""
        session_id = state.get("session_id") or ""
        extra_context = ""
        project_context = ""
        if session_id:
            try:
                extra_context = await memory_store.get_memory_context(session_id)
            except Exception:  # 记忆读取失败不阻断对话
                extra_context = ""
            try:
                plan = await project_store.get_latest_plan(session_id)
                if plan and plan.get("status") == "active":
                    project_context = project_store.summary_text(plan)
            except Exception:  # 项目读取失败不阻断对话
                project_context = ""
        prompt = build_system_prompt(
            tool_list,
            extra_context=extra_context or None,
            history_summary=state.get("history_summary") or None,
            project_context=project_context or None,
        )
        return {"system_prompt": prompt}

    async def agent_node(state: AgentState) -> dict[str, Any]:
        prompt = state.get("system_prompt") or build_system_prompt(tool_list)
        messages = [SystemMessage(content=prompt), *_conversation(state)]
        response = await bound_model.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        return {"messages": [response]}

    async def gate_node(state: AgentState) -> dict[str, Any]:
        """先硬校验，再对副作用工具逐个 interrupt 确认；恢复后从上次位置继续。"""
        last = (state.get("messages") or [None])[-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        rejected = list(state.get("rejected_call_ids") or [])
        blocked = dict(state.get("blocked_calls") or {})
        for call in calls:
            call_id = call.get("id") or ""
            name = call.get("name", "")
            args = dict(call.get("args") or {})
            if call_id in rejected or not await needs_confirmation(name):
                continue
            error = await hard_validate(name, args)
            if error:
                blocked[call_id] = error  # 硬校验失败：不弹确认，直接拒绝
                continue
            payload = build_confirm_payload(name, args)
            decision = interrupt(payload)
            accepted = bool(decision.get("accepted")) if isinstance(decision, dict) else bool(decision)
            if not accepted:
                rejected.append(call_id)
        return {"rejected_call_ids": rejected, "blocked_calls": blocked}

    async def tools_node(state: AgentState) -> dict[str, Any]:
        last = (state.get("messages") or [None])[-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        rejected = set(state.get("rejected_call_ids") or [])
        blocked = dict(state.get("blocked_calls") or {})
        results: list[AnyMessage] = []

        for call in calls:
            call_id = call.get("id") or ""
            name = call.get("name") or ""
            args = dict(call.get("args") or {})

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

            tool = tool_map.get(name)
            if tool is None:
                results.append(
                    ToolMessage(content=f"工具不存在：{name}", tool_call_id=call_id, name=name)
                )
                continue

            try:
                output = await tool.ainvoke(args)
                content = summarize_tool_result(output)
            except Exception as exc:  # 工具异常不打断整轮对话
                content = f"工具执行失败：{exc}"
            results.append(ToolMessage(content=content, tool_call_id=call_id, name=name))

        # 一次性标记，执行完立即清空
        return {"messages": results, "rejected_call_ids": [], "blocked_calls": {}}

    def route_after_agent(state: AgentState) -> str:
        last = (state.get("messages") or [None])[-1]
        return "gate" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(AgentState)
    graph.add_node("load_context", load_context)
    graph.add_node("agent", agent_node)
    graph.add_node("gate", gate_node)
    graph.add_node("tools", tools_node)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"gate": "gate", END: END})
    graph.add_edge("gate", "tools")
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer or InMemorySaver())
