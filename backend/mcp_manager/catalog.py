"""MCP 商店内置目录（FINAL_DEVELOPMENT_DOC 第七章）。

约定：
- 这里只是「可安装清单」，不含任何密钥；安装时由用户填写 env_schema 里的字段
- 命令模板里的 {python} 会在安装时替换为当前解释器绝对路径，保证离线可用
- 目录里的命令、参数都允许用户在安装弹窗里改（自定义 MCP 直接留空模板）
"""

from __future__ import annotations

import sys
from typing import Any

from backend.mcp_manager.importer import clean_value, secure_url

CATALOG: list[dict[str, Any]] = [
    {
        "id": "nova-mock",
        "name": "本地示例 MCP",
        "summary": "内置邮件/日历示例服务，用于验证安装、启停与工具发现，无需联网。",
        "category": "示例",
        "verified": True,
        "command": "{python}",
        "args": ["-m", "backend.mcp_client.mock_server"],
        "env": {},
        "env_schema": [],
    },
    {
        "id": "everything",
        "name": "Everything（官方综合示例）",
        "summary": "官方 everything 参考服务器：echo、环境变量、结构化返回、资源引用等 13 个演示工具。",
        "category": "示例",
        "verified": True,
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-everything"],
        "env": {},
        "env_schema": [],
    },
    {
        "id": "filesystem",
        "name": "文件系统 MCP",
        "summary": "官方 filesystem server：按目录白名单提供读写、搜索、编辑等 14 个工具。",
        "category": "文件",
        "verified": True,
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{dir}"],
        "env": {},
        "env_schema": [
            {
                "key": "dir",
                "label": "允许访问的目录（绝对路径）",
                "required": True,
                "secret": False,
                "target": "arg",
            }
        ],
    },
    {
        "id": "memory",
        "name": "知识记忆 MCP",
        "summary": "官方 memory server：以知识图谱形式存取实体与关系，共 9 个工具。",
        "category": "记忆",
        "verified": True,
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env": {},
        "env_schema": [],
    },
    {
        "id": "sequential-thinking",
        "name": "顺序思考 MCP",
        "summary": "官方 sequential-thinking server：把复杂问题拆成可回溯的思考步骤。",
        "category": "推理",
        "verified": True,
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "env": {},
        "env_schema": [],
    },
    {
        "id": "github",
        "name": "GitHub MCP",
        "summary": "官方 GitHub server：仓库、文件、议题、PR 共 26 个工具（调用需要 Token）。",
        "category": "开发",
        "verified": True,
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {},
        "env_schema": [
            {
                "key": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "label": "GitHub Token（写入 .env）",
                "required": False,
                "secret": True,
                "target": "env",
            }
        ],
    },
    {
        "id": "http-custom",
        "name": "远程 HTTP MCP",
        "summary": "接入支持 Streamable HTTP 的远程 MCP 服务（填端点地址与请求头即可）。",
        "category": "自定义",
        "verified": True,
        "transport": "http",
        "command": "",
        "args": [],
        "url": "",
        "headers": {},
        "env": {},
        "env_schema": [],
    },
    {
        "id": "custom",
        "name": "自定义 stdio MCP",
        "summary": "接入任意 stdio MCP Server：命令、参数、环境变量全部自己填。",
        "category": "自定义",
        "verified": True,
        "transport": "stdio",
        "command": "",
        "args": [],
        "env": {},
        "env_schema": [],
    },
]

CATALOG_MAP: dict[str, dict[str, Any]] = {item["id"]: item for item in CATALOG}

CATEGORIES: list[str] = []
for _item in CATALOG:
    if _item["category"] not in CATEGORIES:
        CATEGORIES.append(_item["category"])


def python_executable() -> str:
    return sys.executable


def list_catalog() -> dict[str, Any]:
    """返回商店目录与分类（不含任何密钥）。"""
    return {"items": CATALOG, "categories": CATEGORIES}


def resolve_template(value: str, variables: dict[str, str]) -> str:
    """把 {python} / {dir} 这类占位替换成实际值。"""
    text = value or ""
    for key, replacement in variables.items():
        text = text.replace("{" + key + "}", replacement)
    return text


def resolve_install(payload: dict[str, Any]) -> dict[str, Any]:
    """把安装请求归一化成可直接落库的配置（含占位替换与必填校验）。

    支持三种用法：
    1) catalog_id + variables：从目录模板生成命令与参数（stdio）
    2) 直接给 command / args / env：自定义 stdio MCP
    3) 直接给 url / headers：远程 Streamable HTTP MCP
    """
    catalog_id = str(payload.get("catalog_id") or "").strip()
    base = CATALOG_MAP.get(catalog_id, {})
    transport = str(payload.get("transport") or base.get("transport") or "stdio").lower()
    if transport not in ("stdio", "http"):
        raise ValueError("transport 只能是 stdio 或 http")

    variables = payload.get("variables")
    variables = variables if isinstance(variables, dict) else {}
    variables = {str(k): str(v) for k, v in variables.items() if str(v).strip()}
    variables.setdefault("python", python_executable())

    for field in base.get("env_schema") or []:
        if field.get("target") == "arg" and field.get("required"):
            if not variables.get(str(field["key"])):
                raise ValueError(f"缺少必填参数：{field.get('label') or field['key']}")

    name = str(payload.get("name") or base.get("name") or "自定义 MCP").strip()

    url = clean_value(payload.get("url") or base.get("url") or "")
    headers = dict(base.get("headers") or {})
    if isinstance(payload.get("headers"), dict):
        headers.update({str(k): str(v) for k, v in payload["headers"].items() if str(v).strip()})

    command = clean_value(payload.get("command") or base.get("command") or "")
    raw_args = payload.get("args")
    args = raw_args if isinstance(raw_args, list) else list(base.get("args") or [])
    env = dict(base.get("env") or {})
    if isinstance(payload.get("env"), dict):
        env.update({str(k): str(v) for k, v in payload["env"].items()})

    if transport == "http":
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP 传输需要填写以 http:// 或 https:// 开头的 MCP 端点地址")
        url = secure_url(name, url)
        command = ""
        args = []
    elif not command:
        raise ValueError("启动命令不能为空")

    return {
        "id": str(payload.get("id") or "").strip() or catalog_id or "",
        "name": name,
        "transport": transport,
        "command": resolve_template(command, variables),
        "args": [resolve_template(str(item), variables) for item in args],
        "url": url,
        "headers": headers,
        "env": env,
        "catalog_id": catalog_id or None,
        "enabled": bool(payload.get("enabled", True)),
        "risk_level": str(payload.get("risk_level") or "normal"),
    }
