"""会话与消息持久化适配层。

职责（09-runtime-middleware-spec.md）：
- sessions / messages 表的 CRUD
- Runtime State 消息 → SQLite 精简消息 的转换（长内容截断、base64 丢弃）
- 为 Agent 提供精简历史（只回放 user/assistant，不回放 ToolMessage，避免 tool_call_id 不匹配）
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from backend.storage.db import db

MAX_CONTENT_CHARS = 8000
MAX_TOOL_RESULT_CHARS = 2000
HISTORY_LIMIT = 40

# 兜底清洗：任何 base64 图片数据都不允许进入 sqlite
_BASE64_RE = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=\s]+")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _slim(text: Optional[str], limit: int) -> str:
    cleaned = _BASE64_RE.sub("[图片数据已省略]", text or "")
    if len(cleaned) > limit:
        return cleaned[:limit] + f"\n...[已截断，原长 {len(cleaned)} 字符]"
    return cleaned


async def create_session(title: str = "新会话") -> dict[str, Any]:
    session_id = uuid.uuid4().hex
    now = _now()
    await db.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, title, now, now),
    )
    return {"id": session_id, "title": title, "created_at": now, "updated_at": now}


async def list_sessions() -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
    )
    return [dict(row) for row in rows]


async def get_session(session_id: str) -> Optional[dict[str, Any]]:
    row = await db.fetch_one(
        "SELECT id, title, created_at, updated_at FROM sessions WHERE id = ?", (session_id,)
    )
    return dict(row) if row else None


async def update_session_title(session_id: str, title: str) -> bool:
    if await get_session(session_id) is None:
        return False
    await db.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title.strip()[:60] or "新会话", _now(), session_id),
    )
    return True


async def maybe_auto_title(session_id: str, first_message: str) -> None:
    """会话标题仍是默认值时，用首条用户消息生成简短标题。"""
    session = await get_session(session_id)
    if session is None or session["title"] not in ("", "新会话"):
        return
    title = " ".join(first_message.strip().split())[:24] or "新会话"
    await db.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?", (title, _now(), session_id)
    )


async def touch_session(session_id: str) -> None:
    await db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))


async def delete_session(session_id: str) -> bool:
    if await get_session(session_id) is None:
        return False
    await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    await db.execute("DELETE FROM session_memory WHERE session_id = ?", (session_id,))
    await db.execute("DELETE FROM uploaded_file_meta WHERE session_id = ?", (session_id,))
    await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return True


async def add_message(
    session_id: str,
    role: str,
    content: str = "",
    tool_name: Optional[str] = None,
    tool_result: Optional[str] = None,
    file_id: Optional[str] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> str:
    message_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO messages
            (id, session_id, role, content, tool_name, tool_result, file_id, attachments_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id,
            session_id,
            role,
            _slim(content, MAX_CONTENT_CHARS),
            tool_name,
            _slim(tool_result, MAX_TOOL_RESULT_CHARS) if tool_result is not None else None,
            file_id,
            json.dumps(attachments, ensure_ascii=False) if attachments else None,
            _now(),
        ),
    )
    return message_id


async def list_messages(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        """
        SELECT id, role, content, tool_name, tool_result, file_id, attachments_json, created_at
        FROM messages WHERE session_id = ?
        ORDER BY created_at ASC, rowid ASC LIMIT ?
        """,
        (session_id, limit),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw = item.pop("attachments_json", None)
        try:
            item["attachments"] = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            item["attachments"] = []
        items.append(item)
    return items


async def get_llm_history(session_id: str, limit: int = HISTORY_LIMIT) -> list[dict[str, Any]]:
    """取最近 N 条 user/assistant 消息（含 id），按时间正序返回，用于每轮重建 state。"""
    rows = await db.fetch_all(
        """
        SELECT id, role, content FROM (
            SELECT id, role, content, created_at, rowid AS rid FROM messages
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY created_at DESC, rid DESC LIMIT ?
        ) ORDER BY created_at ASC, rid ASC
        """,
        (session_id, limit),
    )
    return [dict(row) for row in rows]


async def get_last_user_message(session_id: str) -> str:
    row = await db.fetch_one(
        """
        SELECT content FROM messages
        WHERE session_id = ? AND role = 'user'
        ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (session_id,),
    )
    return str(row["content"]) if row else ""
