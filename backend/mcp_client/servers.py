"""MCP 服务装配：按 .env 选择 Mock / 飞书 / IMAP 实现。

服务名：
- mail：邮件能力（mock / 飞书邮箱 IMAP+SMTP）
- calendar：日程能力（mock / 飞书日历，官方 lark-mcp@0.3.1）

为什么飞书用 0.3.1：0.4+ 依赖 keytar 原生模块，Windows 没有 VS Build Tools 时
npm 安装会直接失败；0.3.1 无原生依赖，且支持 -u 传入用户 access_token。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from backend.env_loader import load_env

from backend.mcp_client.client import MCPError
from backend.mcp_client.feishu_auth import ensure_access_token

load_env()

LARK_PACKAGE = "@larksuiteoapi/lark-mcp@0.3.1"
LARK_TOOLS = "preset.calendar.default,calendar.v4.calendarEvent.list"


@dataclass
class ServerSpec:
    command_provider: Callable[[], Awaitable[list[str]]]
    env: dict[str, str]


def mail_provider() -> str:
    return (os.getenv("NOVA_MAIL_PROVIDER") or "mock").strip().lower()


def calendar_provider() -> str:
    return (os.getenv("NOVA_CALENDAR_PROVIDER") or "mock").strip().lower()


async def _mock_command() -> list[str]:
    return [sys.executable, "-m", "backend.mcp_client.mock_server"]


async def _mail_command() -> list[str]:
    username = (os.getenv("MAIL_USERNAME") or "").strip()
    password = (os.getenv("MAIL_PASSWORD") or "").strip()
    if not username or not password:
        raise MCPError(
            "未配置飞书邮箱：请在 backend/.env 填写 MAIL_USERNAME（完整邮箱地址）"
            "与 MAIL_PASSWORD（客户端专用密码）。"
        )
    return [sys.executable, "-m", "backend.mcp_client.mail_server"]


async def _feishu_command() -> list[str]:
    app_id = (os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (os.getenv("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise MCPError(
            "未配置飞书应用：请在 backend/.env 填写 FEISHU_APP_ID / FEISHU_APP_SECRET。"
        )
    token = await ensure_access_token()
    domain = (os.getenv("FEISHU_DOMAIN") or "https://open.feishu.cn").rstrip("/")
    return [
        "npx",
        "-y",
        LARK_PACKAGE,
        "mcp",
        "-a",
        app_id,
        "-s",
        app_secret,
        "-d",
        domain,
        "-t",
        LARK_TOOLS,
        "-l",
        "zh",
        "-u",
        token,
        "--token-mode",
        "user_access_token",
    ]


async def get_server_spec(name: str) -> ServerSpec:
    if name == "mail":
        if mail_provider() == "imap":
            return ServerSpec(command_provider=_mail_command, env={})
        return ServerSpec(command_provider=_mock_command, env={})
    if name == "calendar":
        if calendar_provider() == "feishu":
            return ServerSpec(command_provider=_feishu_command, env={})
        return ServerSpec(command_provider=_mock_command, env={})
    raise MCPError(f"未知 MCP 服务：{name}")
