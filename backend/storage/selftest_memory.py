"""M7 自测：记忆存储 / 记忆工具 / 自动抽取解析。

必须先设置隔离数据库后运行：
    $env:NOVA_DB_PATH = "$env:TEMP\\ns_m7\\nova.db"
    $env:PYTHONPATH = "e:\\nova-secretary"
    uv run --project backend python -m backend.storage.selftest_memory
"""

from __future__ import annotations

import asyncio
import os
import sys

from langchain_core.messages import AIMessage

from backend.agent.memory_extractor import extract_and_store, parse_extraction
from backend.agent.selftest_agent_graph import ScriptedChatModel
from backend.storage import memory_store, session_store
from backend.storage.db import db
from backend.tools.memory_tools import (
    add_global_memory,
    add_session_memory,
    delete_global_memory,
    delete_session_memory,
)


async def case_store(session_id: str) -> None:
    global_item = await memory_store.add_memory("global", "我喜欢简洁的回答")
    assert global_item, "全局记忆写入失败"
    assert await memory_store.add_memory("global", "  我喜欢简洁的回答  ") is None, "重复记忆应被忽略"
    assert await memory_store.add_memory("session", "本项目接口使用 snake_case", session_id)

    for index in range(25):
        await memory_store.add_memory("global", f"批量偏好 {index}")
    assert len(await memory_store.list_memories("global")) == memory_store.MAX_ITEMS
    print("[PASS] 1. 记忆写入 / 去重 / 条数上限")

    await memory_store.clear_memories("global")
    await memory_store.add_memory("global", "回答尽量简洁")
    context = await memory_store.get_memory_context(session_id)
    assert "回答尽量简洁" in context and "snake_case" in context, context
    print("[PASS] 2. 记忆注入文本组装正确")

    item = (await memory_store.list_memories("global"))[0]
    assert await memory_store.update_memory("global", item["id"], "回答要更简洁")
    assert await memory_store.delete_memory("global", item["id"])
    print("[PASS] 3. 记忆编辑 / 单条删除")


async def case_tools(session_id: str) -> None:
    token = memory_store.CURRENT_SESSION.set(session_id)
    try:
        result = await add_session_memory.ainvoke({"memory_text": "接口统一返回 JSON"})
        assert "已记住" in result, result
        result = await add_global_memory.ainvoke({"memory_text": "我主要使用 Python"})
        assert "已记住" in result, result
        result = await delete_session_memory.ainvoke({"keyword": "JSON"})
        assert "已删除 1" in result, result
        result = await delete_global_memory.ainvoke({"keyword": "Python"})
        assert "已删除 1" in result, result
    finally:
        memory_store.CURRENT_SESSION.reset(token)
    print("[PASS] 4. Agent 记忆工具（新增/按关键词删除）")


async def case_extractor(session_id: str) -> None:
    parsed = parse_extraction('```json\n{"session": ["偏好A"], "global": ["偏好B"]}\n```')
    assert parsed == {"session": ["偏好A"], "global": ["偏好B"]}, parsed
    assert parse_extraction("没有 JSON") == {}
    print("[PASS] 5. 抽取结果解析（兼容代码块/异常输出）")

    await session_store.add_message(session_id, "user", "请记住我更喜欢用 uv 而不是 pip 管理依赖")
    await session_store.add_message(session_id, "assistant", "好的，已记录。")
    model = ScriptedChatModel(
        script=[AIMessage(content='{"session": ["使用 uv 管理依赖"], "global": []}')]
    )
    added = await extract_and_store(session_id, "好的，已记录。", model)
    assert added["session"] == 1, added
    memories = await memory_store.list_memories("session", session_id)
    assert any("uv" in item["memory_text"] for item in memories), memories
    print("[PASS] 6. 自动抽取写入会话记忆")


async def main() -> None:
    if not os.environ.get("NOVA_DB_PATH"):
        print("拒绝执行：请先设置 NOVA_DB_PATH 指向隔离数据库，避免污染真实记忆。")
        sys.exit(2)

    await db.init_db()
    session = await session_store.create_session("记忆自测")
    session_id = session["id"]
    try:
        await memory_store.clear_memories("global")
        await memory_store.clear_memories("session", session_id)
        await case_store(session_id)
        await case_tools(session_id)
        await case_extractor(session_id)
    finally:
        await memory_store.clear_memories("global")
        await session_store.delete_session(session_id)
        await db.close()

    print("\nM7 全部自测通过")


if __name__ == "__main__":
    asyncio.run(main())
