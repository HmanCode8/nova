"""工具调用轨迹（trace_log 表）读写。

对应 FINAL_DEVELOPMENT_DOC 第三章「轨迹 Trace 面板」与第十章 trace_log 表：
- 每次工具调用写一行：工具名、参数、返回值、耗时、状态
- 删除确认会经历 waiting_confirm → confirmed / cancelled 三次状态变更
- 轨迹只用于展示与回放，不参与模型上下文
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Optional

MAX_PARAMS_CHARS = 4000
MAX_RESULT_CHARS = 8000

# 允许的状态机取值
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_WAITING = "waiting_confirm"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"
STATUS_BLOCKED = "blocked"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clip(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            value = str(value)
    if len(value) > limit:
        return value[:limit] + f"\n...[已截断，原长 {len(value)} 字符]"
    return value


def trace_id_for(session_id: str, call_id: str) -> str:
    """确定性主键：同一次工具调用在 gate 重放时不会产生重复行。"""
    return f"{session_id or '-'}:{call_id or '-'}"


async def begin(
    session_id: str,
    call_id: str,
    tool_name: str,
    params: dict[str, Any] | None = None,
    task_id: str = "",
) -> str:
    """记录一次工具调用开始（幂等）。返回 trace_id。"""
    from backend.storage.db import db

    trace_id = trace_id_for(session_id, call_id)
    await db.execute(
        """
        INSERT OR IGNORE INTO trace_log
            (id, task_id, session_id, tool_name, params, result, status, duration_ms, started_at, created_at)
        VALUES (?, ?, ?, ?, ?, '', ?, 0, ?, ?)
        """,
        (
            trace_id,
            task_id or None,
            session_id or None,
            tool_name,
            _clip(params or {}, MAX_PARAMS_CHARS),
            STATUS_RUNNING,
            time.time(),
            _now(),
        ),
    )
    return trace_id


async def mark(trace_id: str, status: str) -> None:
    """更新状态；confirmed 会额外打上「已人工确认」标记。"""
    from backend.storage.db import db

    if status == STATUS_CONFIRMED:
        await db.execute(
            "UPDATE trace_log SET status = ?, confirmed = 1 WHERE id = ?", (status, trace_id)
        )
        return
    await db.execute("UPDATE trace_log SET status = ? WHERE id = ?", (status, trace_id))


async def finish(trace_id: str, status: str, result: Any = None) -> None:
    """记录工具调用结束：状态 + 返回值 + 耗时。"""
    from backend.storage.db import db

    row = await db.fetch_one("SELECT started_at FROM trace_log WHERE id = ?", (trace_id,))
    duration = 0
    if row is not None:
        try:
            duration = max(0, int((time.time() - float(row["started_at"] or 0)) * 1000))
        except (TypeError, ValueError):
            duration = 0
    await db.execute(
        "UPDATE trace_log SET status = ?, result = ?, duration_ms = ? WHERE id = ?",
        (status, _clip(result, MAX_RESULT_CHARS), duration, trace_id),
    )


async def record(
    session_id: str,
    call_id: str,
    tool_name: str,
    params: dict[str, Any] | None,
    status: str,
    result: Any = None,
    task_id: str = "",
) -> str:
    """一步写入开始与结束状态（工具未真正执行、被拦截时用）。"""
    trace_id = await begin(session_id, call_id, tool_name, params, task_id)
    await finish(trace_id, status, result)
    return trace_id


def _row_to_item(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["duration_ms"] = int(item.get("duration_ms") or 0)
    item["confirmed"] = bool(item.get("confirmed"))
    item.pop("started_at", None)
    return item


async def query(
    session_id: str = "",
    search: str = "",
    limit: int = 200,
    task_id: str = "",
) -> list[dict[str, Any]]:
    """轨迹列表（新→旧），支持按会话、任务、关键词过滤。"""
    from backend.storage.db import db

    sql = (
        "SELECT id, task_id, session_id, tool_name, params, result, status, duration_ms, "
        "confirmed, created_at FROM trace_log WHERE 1 = 1"
    )
    params: list[Any] = []
    if session_id:
        sql += " AND session_id = ?"
        params.append(session_id)
    if task_id:
        sql += " AND task_id = ?"
        params.append(task_id)
    if search:
        sql += " AND (tool_name LIKE ? OR params LIKE ? OR result LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(int(limit or 200), 1000)))
    rows = await db.fetch_all(sql, tuple(params))
    return [_row_to_item(row) for row in rows]


async def get(trace_id: str) -> Optional[dict[str, Any]]:
    from backend.storage.db import db

    row = await db.fetch_one(
        "SELECT id, task_id, session_id, tool_name, params, result, status, duration_ms, "
        "confirmed, created_at FROM trace_log WHERE id = ?",
        (trace_id,),
    )
    return _row_to_item(row) if row is not None else None


async def clear(session_id: str = "") -> None:
    from backend.storage.db import db

    if session_id:
        await db.execute("DELETE FROM trace_log WHERE session_id = ?", (session_id,))
    else:
        await db.execute("DELETE FROM trace_log")
