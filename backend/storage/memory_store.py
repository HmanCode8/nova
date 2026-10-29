"""记忆存储：会话记忆 + 全局偏好记忆（05-storage-spec.md）。

约束：
- 全部本地 sqlite，不上传云端
- 单条记忆限长、每个作用域限条数，避免 prompt 膨胀
- 自动记忆开关关闭时不再新增，但已有记忆仍会注入
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Optional

from backend.storage.db import db

# 当前请求上下文中的会话 id（由 WebSocket 网关设置，供记忆工具使用）
CURRENT_SESSION: ContextVar[str] = ContextVar("nova_current_session", default="")

MAX_ITEMS = 20
MAX_TEXT_CHARS = 300
INJECT_LIMIT_PER_SCOPE = 12

_SCOPES = {
    "session": ("session_memory", True),
    "global": ("global_memory", False),
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _table(scope: str) -> tuple[str, bool]:
    if scope not in _SCOPES:
        raise ValueError(f"未知的记忆作用域：{scope}")
    return _SCOPES[scope]


async def list_memories(scope: str, session_id: str = "") -> list[dict[str, Any]]:
    table, scoped = _table(scope)
    if scoped:
        rows = await db.fetch_all(
            f"SELECT id, memory_text, created_at, updated_at FROM {table} "
            "WHERE session_id = ? ORDER BY updated_at DESC",
            (session_id,),
        )
    else:
        rows = await db.fetch_all(
            f"SELECT id, memory_text, created_at, updated_at FROM {table} "
            "ORDER BY updated_at DESC"
        )
    return [dict(row) for row in rows]


async def add_memory(scope: str, text: str, session_id: str = "") -> Optional[dict[str, Any]]:
    """写入一条记忆；重复/空内容/超上限时返回 None。"""
    table, scoped = _table(scope)
    content = _normalize(text)[:MAX_TEXT_CHARS]
    if not content:
        return None
    if scoped and not session_id:
        return None

    existing = await list_memories(scope, session_id)
    if len(existing) >= MAX_ITEMS:
        return None
    known = {_normalize(item["memory_text"]).lower() for item in existing}
    if content.lower() in known:
        return None

    memory_id = uuid.uuid4().hex
    now = _now()
    if scoped:
        await db.execute(
            f"INSERT INTO {table} (id, session_id, memory_text, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (memory_id, session_id, content, now, now),
        )
    else:
        await db.execute(
            f"INSERT INTO {table} (id, memory_text, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (memory_id, content, now, now),
        )
    return {"id": memory_id, "memory_text": content, "created_at": now, "updated_at": now}


async def update_memory(scope: str, memory_id: str, text: str) -> bool:
    table, _ = _table(scope)
    content = _normalize(text)[:MAX_TEXT_CHARS]
    if not content:
        return False
    await db.execute(
        f"UPDATE {table} SET memory_text = ?, updated_at = ? WHERE id = ?",
        (content, _now(), memory_id),
    )
    row = await db.fetch_one(f"SELECT id FROM {table} WHERE id = ?", (memory_id,))
    return row is not None


async def delete_memory(scope: str, memory_id: str) -> bool:
    table, _ = _table(scope)
    row = await db.fetch_one(f"SELECT id FROM {table} WHERE id = ?", (memory_id,))
    if row is None:
        return False
    await db.execute(f"DELETE FROM {table} WHERE id = ?", (memory_id,))
    return True


async def delete_by_keyword(scope: str, keyword: str, session_id: str = "") -> int:
    table, scoped = _table(scope)
    word = _normalize(keyword)
    if not word:
        return 0
    items = await list_memories(scope, session_id)
    matched = [item["id"] for item in items if word.lower() in item["memory_text"].lower()]
    for memory_id in matched:
        await db.execute(f"DELETE FROM {table} WHERE id = ?", (memory_id,))
    return len(matched)


async def clear_memories(scope: str, session_id: str = "") -> int:
    table, scoped = _table(scope)
    items = await list_memories(scope, session_id)
    if scoped:
        await db.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
    else:
        await db.execute(f"DELETE FROM {table}")
    return len(items)


async def get_memory_context(session_id: str = "") -> str:
    """组装注入 system prompt 的记忆文本；无记忆时返回空字符串。"""
    blocks: list[str] = []

    global_items = (await list_memories("global"))[:INJECT_LIMIT_PER_SCOPE]
    if global_items:
        lines = "\n".join(f"- {item['memory_text']}" for item in global_items)
        blocks.append(f"【用户长期偏好】\n{lines}")

    if session_id:
        session_items = (await list_memories("session", session_id))[:INJECT_LIMIT_PER_SCOPE]
        if session_items:
            lines = "\n".join(f"- {item['memory_text']}" for item in session_items)
            blocks.append(f"【本会话约定】\n{lines}")

    return "\n\n".join(blocks)
