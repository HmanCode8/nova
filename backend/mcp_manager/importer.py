"""粘贴配置导入（兼容 Claude Desktop / Cursor 的 mcpServers 写法）。

支持三类输入：
1) {"mcpServers": {"name": {"command": ..., "args": [...], "env": {...}}}}
2) {"mcpServers": {"name": {"url": "https://...", "headers": {...}}}}    ← Streamable HTTP
3) 单个服务对象：{"name": "...", "command": ...} 或 {"name": "...", "url": ...}

安全：请求头 / URL 查询串里的明文密钥会写入 .env 并替换成 ${ENV_NAME} 占位，避免落库（J1）。
"""

from __future__ import annotations

import json
import re
import uuid
from hashlib import md5
from typing import Any

from backend.env_loader import set_env_value
from backend.mcp_manager.store import is_secret_key

_SLUG = re.compile(r"[^a-z0-9]+")
# URL 查询串里这些参数名一律视为密钥（高德 ?key=xxx、?token=xxx、?access_token=xxx）
_SECRET_PARAMS = ("key", "token", "secret", "password", "pass", "sign")


def _slug(value: str) -> str:
    text = _SLUG.sub("-", (value or "").lower()).strip("-")
    return text or uuid.uuid4().hex[:8]


def _env_token(value: str) -> str:
    """把服务名 / 请求头名转成稳定的环境变量片段（中文名退化为名称哈希，避免随机名）。"""
    text = _SLUG.sub("_", (value or "").lower()).strip("_")
    if text:
        return text.upper()
    return "S" + md5((value or "").encode("utf-8")).hexdigest()[:6].upper()


def clean_value(value: Any) -> str:
    """去掉首尾空白、反引号、引号（从聊天/文档里复制的地址常被包裹）。"""
    return str(value or "").strip().strip("`'\"").strip()


def secure_url(server_name: str, url: str) -> str:
    """把 URL 查询串里的明文密钥换成 ${ENV} 占位并写入 .env（如高德 ?key=xxx）。"""
    text = (url or "").strip()
    if not text or "?" not in text:
        return text
    base, _, query = text.partition("?")
    pairs: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        name, sep, value = pair.partition("=")
        lowered = name.strip().lower()
        if sep and value and not value.startswith("${") and any(h in lowered for h in _SECRET_PARAMS):
            env_name = f"MCP_{_env_token(server_name)}_{_env_token(name)}"
            try:
                set_env_value(env_name, value)
                pairs.append(f"{name}=${{{env_name}}}")
                continue
            except OSError:
                pass  # 写 .env 失败时退回原值，保证功能可用
        pairs.append(pair)
    return f"{base}?{'&'.join(pairs)}"


def _secure_headers(server_name: str, headers: dict[str, Any]) -> dict[str, str]:
    """把明文密钥请求头转成 ${ENV} 占位并写入 .env。"""
    resolved: dict[str, str] = {}
    for key, value in (headers or {}).items():
        text = str(value)
        if is_secret_key(str(key)) and text and not text.startswith("${"):
            env_name = f"MCP_{_env_token(server_name)}_{_env_token(str(key))}"
            try:
                set_env_value(env_name, text)
                resolved[str(key)] = "${" + env_name + "}"
                continue
            except OSError:
                pass  # 写 .env 失败时退回原值，保证功能可用
        resolved[str(key)] = text
    return resolved


def _normalize_one(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    command = clean_value(entry.get("command"))
    url = clean_value(entry.get("url") or entry.get("serverUrl"))
    transport = str(entry.get("transport") or entry.get("type") or "").lower()
    if not transport:
        transport = "http" if url else "stdio"

    headers = entry.get("headers") if isinstance(entry.get("headers"), dict) else {}
    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}

    payload = {
        "id": _slug(name),
        "name": name,
        "catalog_id": None,
        "transport": transport,
        "command": command,
        "args": entry.get("args") if isinstance(entry.get("args"), list) else [],
        "url": secure_url(name, url),
        "headers": _secure_headers(name, headers),
        "env": env,
        "enabled": True,
    }
    if transport == "http":
        payload["command"] = ""
        payload["args"] = []
    return payload


def parse(text: str) -> list[dict[str, Any]]:
    """把粘贴的 JSON 文本解析成待安装配置列表。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("配置内容为空")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        if "Extra data" in str(exc):
            raise ValueError("一次只能粘贴一个 JSON 配置块，请分两次导入") from exc
        raise ValueError(f"JSON 格式错误：{exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("配置必须是 JSON 对象")

    servers = data.get("mcpServers")
    if isinstance(servers, dict):
        items: list[dict[str, Any]] = []
        for name, entry in servers.items():
            if isinstance(entry, dict):
                items.append(_normalize_one(str(name), entry))
        if not items:
            raise ValueError("mcpServers 里没有可识别的服务配置")
        return items

    if "command" in data or "url" in data or "serverUrl" in data:
        name = str(data.get("name") or data.get("id") or "imported-mcp")
        return [_normalize_one(name, data)]

    raise ValueError("未找到 mcpServers 或 command/url 字段，请检查粘贴内容")
