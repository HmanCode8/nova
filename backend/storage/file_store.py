"""上传文件存储：会话隔离临时目录 + 元信息表（05-storage-spec.md）。

目录：%APPDATA%/NovaSecretary/temp/{session_id}/{file_id}_{filename}
启动时清理 7 天前的临时文件；删除会话时同步清理。
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from backend.storage.db import APP_DATA_DIR, db

# NOVA_TEMP_DIR 仅用于开发/自测隔离上传目录，生产使用应用数据目录
TEMP_ROOT = Path(os.getenv("NOVA_TEMP_DIR") or (APP_DATA_DIR / "temp"))
MAX_FILENAME_LENGTH = 120


def session_dir(session_id: str) -> Path:
    return TEMP_ROOT / session_id


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_name(filename: str) -> str:
    name = Path(filename or "file").name.strip() or "file"
    return name[:MAX_FILENAME_LENGTH]


async def save_upload(session_id: str, filename: str, data: bytes) -> dict[str, Any]:
    file_id = uuid.uuid4().hex
    safe_name = _safe_name(filename)
    target_dir = session_dir(session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_path = target_dir / f"{file_id}_{safe_name}"
    stored_path.write_bytes(data)

    now = _now()
    await db.execute(
        """
        INSERT INTO uploaded_file_meta (id, session_id, file_id, filename, stored_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, session_id, file_id, safe_name, str(stored_path), now),
    )
    return {
        "file_id": file_id,
        "filename": safe_name,
        "size": len(data),
        "created_at": now,
    }


async def list_meta(session_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        """
        SELECT file_id, filename, stored_path, created_at FROM uploaded_file_meta
        WHERE session_id = ? ORDER BY created_at DESC
        """,
        (session_id,),
    )
    return [dict(row) for row in rows]


async def get_meta(file_id: str, session_id: str) -> Optional[dict[str, Any]]:
    row = await db.fetch_one(
        """
        SELECT file_id, filename, stored_path, created_at FROM uploaded_file_meta
        WHERE file_id = ? AND session_id = ?
        """,
        (file_id, session_id),
    )
    return dict(row) if row else None


async def delete_session_files(session_id: str) -> None:
    await db.execute("DELETE FROM uploaded_file_meta WHERE session_id = ?", (session_id,))
    target = session_dir(session_id)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


async def cleanup_old_files(days: int = 7) -> int:
    """清理超过 N 天的上传临时文件（目录 + 元信息），返回清理目录数。"""
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_text = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    rows = await db.fetch_all(
        "SELECT session_id FROM uploaded_file_meta WHERE created_at < ? GROUP BY session_id",
        (cutoff_text,),
    )
    removed = 0
    for row in rows:
        session_id = row["session_id"]
        await db.execute(
            "DELETE FROM uploaded_file_meta WHERE session_id = ? AND created_at < ?",
            (session_id, cutoff_text),
        )
        target = session_dir(session_id)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            removed += 1
    if TEMP_ROOT.exists():
        for child in TEMP_ROOT.iterdir():
            if child.is_dir() and not await db.fetch_one(
                "SELECT 1 FROM uploaded_file_meta WHERE session_id = ? LIMIT 1", (child.name,)
            ):
                shutil.rmtree(child, ignore_errors=True)
    return removed
