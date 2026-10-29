"""Agent 记忆工具：会话记忆 / 全局记忆的新增与删除。

会话 id 由 WebSocket 网关写入 ContextVar，工具无需 LLM 传参。
"""

from __future__ import annotations

from langchain_core.tools import tool

from backend.storage.memory_store import (
    CURRENT_SESSION,
    add_memory,
    delete_by_keyword,
)


def _session_id() -> str:
    return CURRENT_SESSION.get() or ""


@tool
async def add_session_memory(memory_text: str) -> str:
    """记住仅在本会话生效的约定或偏好（例如"这个项目的接口都用 snake_case"）。

    参数:
        memory_text: 要记住的内容，一句话即可
    """
    session_id = _session_id()
    if not session_id:
        return "写入会话记忆失败：当前没有会话上下文。"
    record = await add_memory("session", memory_text, session_id)
    if record is None:
        return "未写入会话记忆（内容为空、重复，或已达条数上限）。"
    return f"已记住（本会话）：{record['memory_text']}"


@tool
async def delete_session_memory(keyword: str) -> str:
    """删除本会话中包含指定关键词的记忆。

    参数:
        keyword: 要匹配的关键词
    """
    session_id = _session_id()
    if not session_id:
        return "删除会话记忆失败：当前没有会话上下文。"
    count = await delete_by_keyword("session", keyword, session_id)
    return f"已删除 {count} 条匹配的会话记忆。" if count else "没有找到匹配的会话记忆。"


@tool
async def add_global_memory(memory_text: str) -> str:
    """记住跨会话生效的长期偏好（例如"回答尽量简洁"、"我主要使用 Python"）。

    参数:
        memory_text: 要长期记住的内容，一句话即可
    """
    record = await add_memory("global", memory_text)
    if record is None:
        return "未写入全局记忆（内容为空、重复，或已达条数上限）。"
    return f"已记住（全局）：{record['memory_text']}"


@tool
async def delete_global_memory(keyword: str) -> str:
    """删除全局记忆中包含指定关键词的条目。

    参数:
        keyword: 要匹配的关键词
    """
    count = await delete_by_keyword("global", keyword)
    return f"已删除 {count} 条匹配的全局记忆。" if count else "没有找到匹配的全局记忆。"
