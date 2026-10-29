"""M1 自测脚本：验证手写 StateGraph 的工具调用与 interrupt 人工确认流程（不依赖真实 LLM）。

运行：
    cd e:\nova-secretary
    $env:PYTHONPATH = "e:\nova-secretary"
    uv run --project backend python -m backend.agent.selftest_agent_graph

覆盖场景：
1. 普通对话（无工具调用）正常结束
2. 副作用工具调用 → interrupt 暂停 → 确认 → 执行 → 回到 agent 收尾
3. 副作用工具调用 → interrupt 暂停 → 取消 → 不执行，Agent 继续对话
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.types import Command
from pydantic import Field, PrivateAttr

from backend.agent.agent_graph import build_agent, extract_interrupt, thread_config
from backend.storage.config_store import get_config, save_config
from backend.storage.db import db


class ScriptedChatModel(BaseChatModel):
    """按预设脚本逐次返回 AIMessage，用于离线验证图逻辑。"""

    script: list[AIMessage] = Field(default_factory=list)
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-test-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(
        self,
        messages: Any,
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self._cursor >= len(self.script):
            raise RuntimeError("脚本已耗尽：模型被多调用了一次")
        message = self.script[self._cursor]
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


@tool
def write_file(file_path: str, content: str) -> str:
    """测试用写文件工具（仅 M1 验证确认链路，M2 替换为正式实现）。"""
    Path(file_path).write_text(content, encoding="utf-8")
    return f"已写入 {file_path}"


def _tool_call_message(path: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "write_file",
                "args": {"file_path": path, "content": "hello"},
                "id": "call_write_1",
            }
        ],
    )


async def case_plain_reply() -> None:
    graph = build_agent(ScriptedChatModel(script=[AIMessage(content="你好，我是 NovaSecretary。")]))
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="你好")], "session_id": "case-plain"},
        config=thread_config("case-plain"),
    )
    assert extract_interrupt(result) is None, "普通对话不应触发中断"
    assert result["messages"][-1].content == "你好，我是 NovaSecretary。"
    print("[PASS] 1. 普通对话正常结束")


async def case_confirm_accept(workdir: Path) -> None:
    target = workdir / "accepted.txt"
    model = ScriptedChatModel(
        script=[_tool_call_message(str(target)), AIMessage(content="已写入文件。")]
    )
    graph = build_agent(model, tools=[write_file])

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="帮我写个文件")], "session_id": "case-accept"},
        config=thread_config("case-accept"),
    )
    payload = extract_interrupt(result)
    assert payload is not None, "副作用工具必须触发 interrupt"
    assert payload["action"] == "write_file"
    assert payload["confirm_id"], "确认事件必须带 confirm_id"
    assert "即将写入文件" in payload["preview_text"]
    assert not target.exists(), "确认前禁止执行写文件"
    print(f"[PASS] 2a. interrupt 载荷正确：{payload['preview_text']}")

    result = await graph.ainvoke(
        Command(resume={"accepted": True}), config=thread_config("case-accept")
    )
    assert target.exists(), "确认后应真正写入文件"
    assert result["messages"][-1].content == "已写入文件。"
    print("[PASS] 2b. 确认后执行工具并回到 Agent 收尾")


async def case_confirm_reject(workdir: Path) -> None:
    target = workdir / "rejected.txt"
    model = ScriptedChatModel(
        script=[_tool_call_message(str(target)), AIMessage(content="好的，已取消。")]
    )
    graph = build_agent(model, tools=[write_file])

    await graph.ainvoke(
        {"messages": [HumanMessage(content="帮我写个文件")], "session_id": "case-reject"},
        config=thread_config("case-reject"),
    )
    result = await graph.ainvoke(
        Command(resume={"accepted": False}), config=thread_config("case-reject")
    )
    assert not target.exists(), "取消后禁止执行写文件"
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages and "用户已取消" in tool_messages[-1].content
    assert result["messages"][-1].content == "好的，已取消。"
    print("[PASS] 3. 取消后不执行副作用并继续对话")


async def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="ns_m1_"))
    # M2 起 gate 会在弹确认前做目录白名单硬校验，测试目录需要临时加入白名单
    original = await get_config()
    await save_config({"allowed_dirs": [str(workdir)]})
    try:
        await case_plain_reply()
        await case_confirm_accept(workdir)
        await case_confirm_reject(workdir)
    finally:
        await save_config({"allowed_dirs": list(original.get("allowed_dirs") or [])})
        await db.close()
    print("\nM1 全部自测通过")


if __name__ == "__main__":
    asyncio.run(main())
