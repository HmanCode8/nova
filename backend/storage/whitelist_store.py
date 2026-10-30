"""目录白名单存储（whitelist_dirs 表）。

设计说明（FINAL_DEVELOPMENT_DOC 第二章）：
- 白名单是兜底防线，Agent 只能访问这里配置的根目录；白名单外一律拒绝
- 表结构独立于 app_config，便于后续做「目录 + 备注 + 创建时间」的扩展
- 兼容旧数据：首次访问时把 app_config.allowed_dirs 迁移进白名单表
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def _raw_config_dirs() -> list[str]:
    """直接从 app_config 读取历史 allowed_dirs（不依赖 config_store，避免循环导入）。"""
    from backend.storage.db import db  # 延迟导入，便于测试替换

    row = await db.fetch_one("SELECT config_json FROM app_config ORDER BY id LIMIT 1")
    if row is None:
        return []
    try:
        payload = json.loads(row["config_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    dirs = payload.get("allowed_dirs") if isinstance(payload, dict) else None
    if not isinstance(dirs, list):
        return []
    return [item.strip() for item in dirs if isinstance(item, str) and item.strip()]


async def ensure_seeded() -> None:
    """把旧的 allowed_dirs 迁移进白名单表（只在表为空时执行一次）。"""
    from backend.storage.db import db

    row = await db.fetch_one("SELECT COUNT(*) AS total FROM whitelist_dirs")
    if row and int(row["total"] or 0) > 0:
        return
    for path in await _raw_config_dirs():
        await db.execute(
            "INSERT OR IGNORE INTO whitelist_dirs (id, path, created_at) VALUES (?, ?, ?)",
            (uuid.uuid4().hex, path, _now()),
        )


async def list_dirs() -> list[str]:
    """返回白名单目录（按创建顺序）。"""
    from backend.storage.db import db

    await ensure_seeded()
    rows = await db.fetch_all(
        "SELECT path FROM whitelist_dirs ORDER BY created_at ASC, rowid ASC"
    )
    return [str(row["path"]) for row in rows]


async def replace_all(dirs: list[str]) -> list[str]:
    """整份替换白名单（设置面板保存时调用），返回去重后的结果。"""
    from backend.storage.db import db

    cleaned: list[str] = []
    for item in dirs:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value and value not in cleaned:
            cleaned.append(value)

    await db.execute("DELETE FROM whitelist_dirs")
    for value in cleaned:
        await db.execute(
            "INSERT OR IGNORE INTO whitelist_dirs (id, path, created_at) VALUES (?, ?, ?)",
            (uuid.uuid4().hex, value, _now()),
        )
    return cleaned


async def summary() -> list[dict[str, Any]]:
    """带创建时间的白名单（供前端展示 / 排障）。"""
    from backend.storage.db import db

    await ensure_seeded()
    rows = await db.fetch_all(
        "SELECT id, path, created_at FROM whitelist_dirs ORDER BY created_at ASC, rowid ASC"
    )
    return [dict(row) for row in rows]
