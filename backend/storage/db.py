"""SQLite 存储基座：应用数据目录、连接管理、建表、异步写锁。

存储规范见 .trae/rules/05-storage-spec.md：
- Windows: %APPDATA%/NovaSecretary/nova.db
- macOS:   ~/Library/Application Support/NovaSecretary/nova.db
- 全部数据库操作只在 Python 后端执行；写入使用异步锁避免并发损坏。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite

APP_NAME = "NovaSecretary"


def get_app_data_dir() -> Path:
    """返回应用数据目录并确保存在（不放在项目源码目录内）。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        # Windows：%APPDATA%，取不到时退回用户主目录
        base = Path(os.getenv("APPDATA") or Path.home())
    app_dir = base / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


APP_DATA_DIR = get_app_data_dir()
# NOVA_DB_PATH 仅用于开发/自测隔离数据库，生产直接使用应用数据目录
DB_PATH = Path(os.getenv("NOVA_DB_PATH") or (APP_DATA_DIR / "nova.db"))

# 六张表的建表语句（字段严格对齐 05-storage-spec.md）
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '新会话',
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        tool_name TEXT,
        tool_result TEXT,
        file_id TEXT,
        created_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS session_memory (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        memory_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_session_memory_session ON session_memory(session_id)",
    """
    CREATE TABLE IF NOT EXISTS global_memory (
        id TEXT PRIMARY KEY,
        memory_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS uploaded_file_meta (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        file_id TEXT NOT NULL UNIQUE,
        filename TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_uploaded_file_session ON uploaded_file_meta(session_id)",
    """
    CREATE TABLE IF NOT EXISTS app_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_plans (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        goal TEXT NOT NULL DEFAULT '',
        root_dir TEXT NOT NULL DEFAULT '',
        steps_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_project_plans_session ON project_plans(session_id, created_at)",
    # ---- v2 新增（FINAL_DEVELOPMENT_DOC 第十章）----
    """
    CREATE TABLE IF NOT EXISTS whitelist_dirs (
        id TEXT PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trace_log (
        id TEXT PRIMARY KEY,
        task_id TEXT,
        session_id TEXT,
        tool_name TEXT NOT NULL,
        params TEXT,
        result TEXT,
        status TEXT NOT NULL,
        duration_ms INTEGER DEFAULT 0,
        started_at REAL DEFAULT 0,
        confirmed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_session ON trace_log(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_trace_task ON trace_log(task_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        title TEXT NOT NULL DEFAULT '',
        prompt TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        result TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS mcp_config (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        command TEXT NOT NULL,
        args_json TEXT NOT NULL DEFAULT '[]',
        env_json TEXT NOT NULL DEFAULT '{}',
        catalog_id TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        risk_level TEXT NOT NULL DEFAULT 'normal',
        require_confirm INTEGER NOT NULL DEFAULT 0,
        transport TEXT NOT NULL DEFAULT 'stdio',
        url TEXT NOT NULL DEFAULT '',
        headers_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_summary (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        memory_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_summary_session ON memory_summary(session_id)",
)


class Database:
    """单进程单连接的 aiosqlite 封装，写操作统一走 write_lock 串行化。"""

    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self._connect_lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()

    async def connect(self) -> aiosqlite.Connection:
        """懒加载连接：WAL 模式 + 外键约束 + Row 工厂。"""
        if self._conn is not None:
            return self._conn
        async with self._connect_lock:
            if self._conn is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(self.path)
                try:
                    conn.row_factory = aiosqlite.Row
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA foreign_keys=ON")
                    await conn.commit()
                except Exception:
                    # 初始化失败必须关连接，否则 aiosqlite 工作线程会挂住进程
                    await conn.close()
                    raise
                self._conn = conn
        return self._conn

    async def init_db(self) -> None:
        """后端启动时自动建表（幂等）+ 极简迁移。"""
        conn = await self.connect()
        async with self.write_lock:
            for statement in SCHEMA_STATEMENTS:
                await conn.execute(statement)
            await self._migrate(conn)
            await conn.commit()

    async def _migrate(self, conn: aiosqlite.Connection) -> None:
        """仅做必要的增量列迁移，不引入 ORM。"""
        cursor = await conn.execute("PRAGMA table_info(messages)")
        rows = await cursor.fetchall()
        await cursor.close()
        columns = {row[1] for row in rows}
        if "attachments_json" not in columns:
            await conn.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT")
        if "reasoning" not in columns:
            # 思考过程（推理模型的 reasoning_content），仅用于界面回显，不参与上下文
            await conn.execute("ALTER TABLE messages ADD COLUMN reasoning TEXT")

        cursor = await conn.execute("PRAGMA table_info(trace_log)")
        trace_rows = await cursor.fetchall()
        await cursor.close()
        trace_columns = {row[1] for row in trace_rows}
        if "confirmed" not in trace_columns:
            # 标记该次调用是否经过人工确认（删除类操作），最终 status 仍记为执行结果
            await conn.execute(
                "ALTER TABLE trace_log ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 0"
            )

        cursor = await conn.execute("PRAGMA table_info(mcp_config)")
        mcp_rows = await cursor.fetchall()
        await cursor.close()
        mcp_columns = {row[1] for row in mcp_rows}
        # v2：支持 Streamable HTTP 传输与自定义请求头
        for column, ddl in (
            ("transport", "ALTER TABLE mcp_config ADD COLUMN transport TEXT NOT NULL DEFAULT 'stdio'"),
            ("url", "ALTER TABLE mcp_config ADD COLUMN url TEXT NOT NULL DEFAULT ''"),
            (
                "headers_json",
                "ALTER TABLE mcp_config ADD COLUMN headers_json TEXT NOT NULL DEFAULT '{}'",
            ),
        ):
            if column not in mcp_columns:
                await conn.execute(ddl)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        conn = await self.connect()
        async with self.write_lock:
            await conn.execute(sql, tuple(params))
            await conn.commit()

    async def executemany(self, sql: str, seq_params: Iterable[Iterable[Any]]) -> None:
        conn = await self.connect()
        async with self.write_lock:
            await conn.executemany(sql, [tuple(p) for p in seq_params])
            await conn.commit()

    async def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[aiosqlite.Row]:
        conn = await self.connect()
        cursor = await conn.execute(sql, tuple(params))
        row = await cursor.fetchone()
        await cursor.close()
        return row

    async def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        conn = await self.connect()
        cursor = await conn.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        await cursor.close()
        return list(rows)


# 全局单例：server 启动时调用 init_db()
db = Database()
