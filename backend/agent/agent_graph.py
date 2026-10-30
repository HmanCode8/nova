"""LangGraph 主图：手写 StateGraph + 原生 interrupt 人工确认。

图结构：
    START → load_context → agent ⇄ gate → tools → agent → END
                              └─ 额度耗尽 → finalize → END

- load_context：前置节点，组装 system prompt（记忆注入、项目进度、历史摘要）
- agent：调用绑定工具的 LLM
- gate：副作用工具在此 interrupt() 暂停，等待前端确认；无副作用工具直接放行
- tools：真正执行工具，只跑一次，避免 interrupt 恢复导致副作用重复执行
- finalize：工具调用额度耗尽的收尾节点，强制模型输出文字答复

说明：不用 langchain.agents.middleware，也不回退 create_react_agent 黑盒。
"""

from __future__ import annotations

from typing import Annotated, Any, Optional, Sequence, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from backend.agent.prompts import build_system_prompt
from backend.middleware import build_middleware
from backend.storage import memory_store, project_store


class AgentState(TypedDict, total=False):
    """图运行时 state（内存级，不直接持久化）。"""

    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    system_prompt: str
    history_summary: str
    rejected_call_ids: list[str]
    blocked_calls: dict[str, str]
    tool_counts: dict[str, int]  # 本轮「工具名+参数」签名 → 调用次数
    tool_total: int              # 本轮工具调用总次数


# 每轮工具调用会消耗 agent / gate / tools 三个节点步数，熔断额度已在下面单独控制，
# 这里放宽只是留足余量，真正的终止保证来自 MAX_TOOL_CALLS_PER_TURN + finalize 收尾
RECURSION_LIMIT = 100


async def _allowed_dirs() -> list[str]:
    """当前授权目录（写进 system prompt，避免模型猜路径导致写错目录）。"""
    try:
        from backend.tools.tool_hook import get_allowed_dirs

        return [str(path) for path in await get_allowed_dirs()]
    except Exception:  # 白名单读取失败不阻断对话
        return []


# 单轮工具调用总次数上限：24 轮 × 3 节点 + 收尾仍远低于 RECURSION_LIMIT
MAX_TOOL_CALLS_PER_TURN = 24

_LOOP_BLOCK_HINT = (
    "系统拦截：该工具用相同参数已重复调用 {limit} 次，判定为无效重试，已停止执行。\n"
    "不要再调用同一个工具，请直接基于已有结果回答用户；\n"
    "如果原因是「功能未启用 / 缺少配置」（例如文生图未开启），如实说明需要用户在设置面板开启即可，"
    "禁止改用截图、视觉理解或命令执行等工具去勉强替代。"
)


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
    """过滤历史中的 SystemMessage，system prompt 由前置节点统一注入。

    同时剔除「带 tool_calls 但没有对应 ToolMessage」的消息：这类未执行的调用留在上下文里，
    OpenAI 兼容接口会直接报错（例如本轮被上限/异常打断时）。
    """
    messages = [m for m in state.get("messages") or [] if not isinstance(m, SystemMessage)]
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    result: list[AnyMessage] = []
    for message in messages:
        calls = getattr(message, "tool_calls", None)
        if calls and any((call.get("id") or "") not in answered for call in calls):
            text = (getattr(message, "content", "") or "").strip()
            if text:  # 保留文字部分，去掉悬空的工具调用
                result.append(AIMessage(content=text))
            continue
        result.append(message)
    return result


def build_agent(
    model: BaseChatModel,
    tools: Optional[Sequence[Any]] = None,
    checkpointer: Optional[Any] = None,
    tool_map: Optional[dict[str, Any]] = None,
    task_id: str = "",
):
    """构建并编译 Agent 图。

    tool_list 只用于绑定给模型（对外暴露的能力集）；tool_map 可额外包含历史别名，
    这样旧会话里出现的旧工具名仍然能被执行。
    """
    tool_list = list(tools or [])
    if tool_map is None:
        # 默认执行表：规范名 + 旧名别名，保证历史会话里的旧工具名仍可执行
        from backend.tools.tool_hook import LEGACY_TOOL_NAMES

        execution_map: dict[str, Any] = {tool.name: tool for tool in tool_list}
        for old, new in LEGACY_TOOL_NAMES.items():
            if new in execution_map:
                execution_map.setdefault(old, execution_map[new])
    else:
        execution_map = dict(tool_map)
    for tool in tool_list:
        execution_map.setdefault(tool.name, tool)
    bound_model = model.bind_tools(tool_list) if tool_list else model

    def make_middleware(state: AgentState):
        return build_middleware(
            state.get("session_id") or "",
            execution_map,
            task_id=task_id,
            loop_hint=_LOOP_BLOCK_HINT,
        )

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
            allowed_dirs=await _allowed_dirs(),
        )
        return {"system_prompt": prompt, "tool_counts": {}, "tool_total": 0}

    async def agent_node(state: AgentState) -> dict[str, Any]:
        prompt = state.get("system_prompt") or build_system_prompt(tool_list)
        messages = [SystemMessage(content=prompt), *_conversation(state)]
        response = await bound_model.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        return {"messages": [response]}

    async def gate_node(state: AgentState) -> dict[str, Any]:
        """中间件前置：白名单/硬校验 + 删除确认 interrupt + Trace 开始埋点。"""
        return await make_middleware(state).prepare(state)

    async def tools_node(state: AgentState) -> dict[str, Any]:
        """中间件执行：真正调用工具并写 Trace 结束埋点。"""
        return await make_middleware(state).execute(state)

    async def finalize_node(state: AgentState) -> dict[str, Any]:
        """工具调用额度耗尽时的收尾：不再给工具，强制模型输出最终答复。"""
        prompt = state.get("system_prompt") or build_system_prompt(tool_list)
        messages = [
            SystemMessage(content=prompt),
            *_conversation(state),
            SystemMessage(
                content=(
                    "本轮工具调用次数已达上限，必须立即停止调用任何工具。"
                    "请基于已经获得的信息直接给出最终答复；未能完成的部分如实说明原因和下一步建议。"
                )
            ),
        ]
        response = await model.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        if getattr(response, "tool_calls", None):
            # 模型仍然想调工具时也不放行，保证一定有可见文字收尾
            text = (response.content or "").strip()
            response = AIMessage(
                content=text
                or "本轮工具调用次数已达上限，已停止继续尝试。请把需求拆小一点（例如先只做第一项）再让我继续。"
            )
        return {"messages": [response], "tool_counts": {}, "tool_total": 0}

    def route_after_agent(state: AgentState) -> str:
        last = (state.get("messages") or [None])[-1]
        return "gate" if getattr(last, "tool_calls", None) else END

    def route_after_gate(state: AgentState) -> str:
        """本轮工具调用已接近上限时走收尾节点，避免撞上递归上限报错。"""
        last = (state.get("messages") or [None])[-1]
        planned = len(getattr(last, "tool_calls", None) or [])
        if int(state.get("tool_total") or 0) + planned > MAX_TOOL_CALLS_PER_TURN:
            return "finalize"
        return "tools"

    graph = StateGraph(AgentState)
    graph.add_node("load_context", load_context)
    graph.add_node("agent", agent_node)
    graph.add_node("gate", gate_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"gate": "gate", END: END})
    graph.add_conditional_edges("gate", route_after_gate, {"tools": "tools", "finalize": "finalize"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())
