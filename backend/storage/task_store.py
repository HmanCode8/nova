"""后台任务存储（tasks 表）。

对应 FINAL_DEVELOPMENT_DOC 第四章 Runtime 层与第十章 tasks 表：
- 只持久化任务元信息与最终结果，执行日志走 WebSocket 实时推送，不落库（避免无限膨胀）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

# 任务状态机
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_TIMEOUT = "timeout"

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_RUNNING)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def create(session_id: str, prompt: str, title: str = "") -> dict[str, Any]:
    from backend.storage.db import db

    task_id = uuid.uuid4().hex
    now = _now()
    await db.execute(
        """
        INSERT INTO tasks (id, session_id, title, prompt, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            session_id,
            (title or prompt or "后台任务").strip()[:80],
            prompt[:4000],
            STATUS_PENDING,
            now,
            now,
        ),
    )
    record = await get(task_id)
    return record or {"id": task_id}


async def update(
    task_id: str,
    status: str = "",
    result: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    from backend.storage.db import db

    fields = ["updated_at = ?"]
    params: list[Any] = [_now()]
    if status:
        fields.append("status = ?")
        params.append(status)
    if result is not None:
        fields.append("result = ?")
        params.append(result[:20000])
    if error is not None:
        fields.append("error = ?")
        params.append(error[:2000])
    params.append(task_id)
    await db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", tuple(params))


async def get(task_id: str) -> Optional[dict[str, Any]]:
    from backend.storage.db import db

    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return dict(row) if row is not None else None


async def list_tasks(session_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    from backend.storage.db import db

    sql = "SELECT * FROM tasks"
    params: list[Any] = []
    if session_id:
        sql += " WHERE session_id = ?"
        params.append(session_id)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(int(limit or 50), 200)))
    rows = await db.fetch_all(sql, tuple(params))
    return [dict(row) for row in rows]


async def count_active() -> int:
    from backend.storage.db import db

    row = await db.fetch_one(
        "SELECT COUNT(*) AS total FROM tasks WHERE status IN (?, ?)", ACTIVE_STATUSES
    )
    return int(row["total"] or 0) if row is not None else 0


async def mark_interrupted_tasks() -> int:
    """进程重启后把遗留的 pending/running 标记为 failed，避免状态永远卡住。"""
    from backend.storage.db import db

    row = await db.fetch_one(
        "SELECT COUNT(*) AS total FROM tasks WHERE status IN (?, ?)", ACTIVE_STATUSES
    )
    total = int(row["total"] or 0) if row is not None else 0
    if total:
        await db.execute(
            "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE status IN (?, ?)",
            (STATUS_FAILED, "后端重启，任务已中断", _now(), *ACTIVE_STATUSES),
        )
    return total
