"""MCP 配置存储（mcp_config 表）。

支持两种传输：
- stdio：command + args + env（子进程）
- http：url + headers（Streamable HTTP）

安全约束（05-storage-spec / J1）：密钥不入库。
- stdio 的 env 里密钥类字段写入 .env，子进程从环境变量读取
- http 的请求头支持 ${ENV_NAME} 占位，运行时解析；明文 token 建议改成占位写法
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

SECRET_HINTS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS")

TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "http"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_secret_key(key: str) -> bool:
    upper = (key or "").upper()
    return any(hint in upper for hint in SECRET_HINTS)


async def list_all() -> list[dict[str, Any]]:
    from backend.storage.db import db

    rows = await db.fetch_all("SELECT * FROM mcp_config ORDER BY created_at ASC, rowid ASC")
    return [_to_item(row) for row in rows]


async def get(server_id: str) -> Optional[dict[str, Any]]:
    from backend.storage.db import db

    row = await db.fetch_one("SELECT * FROM mcp_config WHERE id = ?", (server_id,))
    return _to_item(row) if row is not None else None


def _to_item(row: Any) -> dict[str, Any]:
    item = dict(row)
    for field, default in (("args_json", "[]"), ("env_json", "{}"), ("headers_json", "{}")):
        raw = item.pop(field, default)
        try:
            item[field.replace("_json", "")] = json.loads(raw or default)
        except (TypeError, ValueError):
            item[field.replace("_json", "")] = json.loads(default)
    item["enabled"] = bool(item.get("enabled"))
    item["require_confirm"] = bool(item.get("require_confirm"))
    item["transport"] = item.get("transport") or TRANSPORT_STDIO
    item["url"] = item.get("url") or ""
    item["headers"] = item.get("headers") or {}
    return item


async def upsert(payload: dict[str, Any]) -> dict[str, Any]:
    """安装 / 更新一个 MCP 服务。id 已存在则覆盖配置。"""
    from backend.env_loader import set_env_value
    from backend.storage.db import db

    transport = str(payload.get("transport") or TRANSPORT_STDIO).lower()
    if transport not in (TRANSPORT_STDIO, TRANSPORT_HTTP):
        raise ValueError("transport 只能是 stdio 或 http")

    server_id = str(payload.get("id") or "").strip() or uuid.uuid4().hex[:12]
    name = str(payload.get("name") or "").strip() or server_id
    command = str(payload.get("command") or "").strip()
    url = str(payload.get("url") or "").strip()

    if transport == TRANSPORT_HTTP:
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP 传输需要填写以 http:// 或 https:// 开头的地址")
    elif not command:
        raise ValueError("stdio 传输的启动命令不能为空")

    args = payload.get("args") if isinstance(payload.get("args"), list) else []
    env = payload.get("env") if isinstance(payload.get("env"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}

    # 密钥类 env 写 .env，库里只留 ${KEY} 占位；留空表示不设置（保留 .env 原值）
    safe_env: dict[str, str] = {}
    secrets_written: list[str] = []
    for key, value in env.items():
        name = str(key)
        text = str(value)
        if is_secret_key(name):
            if not text:
                continue
            if text.startswith("${"):
                safe_env[name] = text
                continue
            set_env_value(name, text)
            secrets_written.append(name)
            safe_env[name] = "${" + name + "}"
            continue
        safe_env[name] = text

    now = _now()
    existing = await get(server_id)
    if existing is None:
        await db.execute(
            """
            INSERT INTO mcp_config
                (id, name, command, args_json, env_json, catalog_id, enabled,
                 risk_level, require_confirm, transport, url, headers_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                server_id,
                name,
                command,
                json.dumps(args, ensure_ascii=False),
                json.dumps(safe_env, ensure_ascii=False),
                payload.get("catalog_id"),
                1 if payload.get("enabled", True) else 0,
                str(payload.get("risk_level") or "normal"),
                0,
                transport,
                url,
                json.dumps(headers, ensure_ascii=False),
                now,
                now,
            ),
        )
    else:
        await db.execute(
            """
            UPDATE mcp_config
               SET name = ?, command = ?, args_json = ?, env_json = ?,
                   catalog_id = ?, enabled = ?, risk_level = ?,
                   transport = ?, url = ?, headers_json = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                name,
                command,
                json.dumps(args, ensure_ascii=False),
                json.dumps(safe_env, ensure_ascii=False),
                payload.get("catalog_id") or existing.get("catalog_id"),
                1 if payload.get("enabled", existing.get("enabled", True)) else 0,
                str(payload.get("risk_level") or existing.get("risk_level") or "normal"),
                transport,
                url,
                json.dumps(headers, ensure_ascii=False),
                now,
                server_id,
            ),
        )
    record = await get(server_id)
    result = record or {}
    if secrets_written:
        result["secrets_written"] = secrets_written
    return result


async def set_enabled(server_id: str, enabled: bool) -> bool:
    from backend.storage.db import db

    row = await db.fetch_one("SELECT id FROM mcp_config WHERE id = ?", (server_id,))
    if row is None:
        return False
    await db.execute(
        "UPDATE mcp_config SET enabled = ?, updated_at = ? WHERE id = ?",
        (1 if enabled else 0, _now(), server_id),
    )
    return True


async def remove(server_id: str) -> bool:
    from backend.storage.db import db

    row = await db.fetch_one("SELECT id FROM mcp_config WHERE id = ?", (server_id,))
    if row is None:
        return False
    await db.execute("DELETE FROM mcp_config WHERE id = ?", (server_id,))
    return True
