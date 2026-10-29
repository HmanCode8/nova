"""项目任务存储：project_plans 表（会话级项目计划 + 步骤状态）。

存储边界（05-storage-spec.md）：
- 只存计划标题、步骤名、状态、项目根目录，不存文件正文
- 全部读写只在 Python 后端执行
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from backend.storage.db import db

STEP_STATUSES: tuple[str, ...] = ("pending", "done", "failed", "skipped")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_steps(raw: Optional[str]) -> list[dict[str, str]]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    steps: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        steps.append(
            {
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or "pending"),
                "note": str(item.get("note") or ""),
            }
        )
    return steps


def _snapshot(row: Any) -> dict[str, Any]:
    """数据库行 → 前端卡片/接口可直接渲染的计划快照。"""
    steps = _load_steps(row["steps_json"])
    done = sum(1 for step in steps if step["status"] in ("done", "skipped"))
    return {
        "plan_id": row["id"],
        "title": row["title"],
        "goal": row["goal"],
        "root_dir": row["root_dir"],
        "status": row["status"],
        "done": done,
        "total": len(steps),
        "steps": [
            {
                "index": index,
                "name": step["name"],
                "status": step["status"],
                "note": step["note"],
            }
            for index, step in enumerate(steps)
        ],
        "updated_at": row["updated_at"],
    }


async def create_plan(
    session_id: str,
    title: str,
    goal: str,
    root_dir: str,
    steps: list[str],
) -> dict[str, Any]:
    """新建项目计划；同一会话的旧计划标记为 archived，只保留一个当前计划。"""
    plan_id = uuid.uuid4().hex
    now = _now()
    payload = [
        {"name": name.strip(), "status": "pending", "note": ""}
        for name in steps
        if name and name.strip()
    ]
    await db.execute(
        "UPDATE project_plans SET status = 'archived', updated_at = ? "
        "WHERE session_id = ? AND status = 'active'",
        (now, session_id),
    )
    await db.execute(
        "INSERT INTO project_plans "
        "(id, session_id, title, goal, root_dir, steps_json, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
        (plan_id, session_id, title, goal, root_dir, json.dumps(payload, ensure_ascii=False), now, now),
    )
    row = await db.fetch_one("SELECT * FROM project_plans WHERE id = ?", (plan_id,))
    return _snapshot(row) if row else {}


def summary_text(plan: dict[str, Any]) -> str:
    """把计划压成一段文字，注入 system prompt 供 Agent 继续推进。"""
    lines = [
        f"项目《{plan.get('title')}》 进度 {plan.get('done')}/{plan.get('total')}，"
        f"根目录 {plan.get('root_dir') or '（未设置）'}"
    ]
    for step in plan.get("steps") or []:
        mark = {"done": "✓", "failed": "✕", "skipped": "—"}.get(step["status"], "·")
        line = f"{mark} {step['index']}. {step['name']}"
        if step.get("note"):
            line += f"（{step['note']}）"
        lines.append(line)
    return "\n".join(lines)


async def get_latest_plan(session_id: str) -> Optional[dict[str, Any]]:
    """取会话最近一次计划（含已归档），用于刷新页面后恢复看板。"""
    row = await db.fetch_one(
        "SELECT * FROM project_plans WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    )
    return _snapshot(row) if row else None


async def update_step(
    session_id: str, step: int, status: str, note: str = ""
) -> tuple[Optional[dict[str, Any]], str]:
    """更新某一步状态，返回 (计划快照, 错误信息)。"""
    if status not in STEP_STATUSES:
        return None, f"状态不合法：{status}（可选：{'/'.join(STEP_STATUSES)}）"
    row = await db.fetch_one(
        "SELECT * FROM project_plans WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    )
    if row is None:
        return None, "当前会话还没有项目计划，请先调用 plan_project 生成计划。"

    steps = _load_steps(row["steps_json"])
    index = int(step)
    if index < 0 or index >= len(steps):
        return None, f"步骤序号越界：{index}（当前共 {len(steps)} 步，从 0 开始）"

    steps[index]["status"] = status
    if note:
        steps[index]["note"] = note.strip()[:200]
    finished = all(item["status"] in ("done", "skipped") for item in steps)
    plan_status = "done" if finished else "active"
    now = _now()
    await db.execute(
        "UPDATE project_plans SET steps_json = ?, status = ?, updated_at = ? WHERE id = ?",
        (json.dumps(steps, ensure_ascii=False), plan_status, now, row["id"]),
    )
    refreshed = await db.fetch_one("SELECT * FROM project_plans WHERE id = ?", (row["id"],))
    return (_snapshot(refreshed) if refreshed else None), ""


async def delete_session_plans(session_id: str) -> None:
    """删除会话时清理其项目计划。"""
    await db.execute("DELETE FROM project_plans WHERE session_id = ?", (session_id,))
