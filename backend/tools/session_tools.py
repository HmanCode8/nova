"""会话辅助工具：摘要压缩 / 新建会话。"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from backend.agent import context_compress
from backend.agent.llm_adapter import build_chat_model
from backend.storage import session_store
from backend.storage.memory_store import CURRENT_SESSION

KEEP_RECENT = 6


@tool
async def create_new_session(title: str = "新会话") -> str:
    """创建一个新的空白会话，返回新会话 id（前端会自动切换）。

    参数:
        title: 新会话标题，留空则为"新会话"
    """
    session = await session_store.create_session((title or "新会话").strip()[:40])
    return json.dumps(
        {"session_id": session["id"], "title": session["title"]}, ensure_ascii=False
    )


@tool
async def summarize_context() -> str:
    """把当前会话中较早的聊天压缩成摘要并返回摘要文本。

    当对话很长、需要回顾早期结论时使用；日常上下文超限由系统自动压缩。
    """
    session_id = CURRENT_SESSION.get()
    if not session_id:
        return "当前没有会话上下文，无法生成摘要。"
    rows = await session_store.get_llm_history(session_id)
    if len(rows) <= KEEP_RECENT + 2:
        return "当前会话内容较少，无需压缩。"
    try:
        model = await build_chat_model(streaming=False)
        summary = await context_compress.summarize_messages(
            model, context_compress.rows_to_messages(rows[:-KEEP_RECENT])
        )
    except Exception as exc:
        return f"生成摘要失败：{exc}"
    if not summary:
        return "未能生成有效摘要。"
    return f"【会话摘要】\n{summary}"
