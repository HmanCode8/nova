"""本地 Mock 邮件 / 日历 MCP Server（stdio + JSON-RPC 2.0，换行分隔）。

用途：阶段2.5 先用本地 Mock 打通「MCP Client → 工具注册 → Agent 链式调用」全链路，
后续替换真实 Gmail / Outlook / 飞书 MCP Server 时，只需替换启动命令与工具命名，
Agent 与前端无需改动。

协议子集（与 MCP 2024-11-05 对齐，足够覆盖 tools/list + tools/call）：
    initialize / notifications/initialized / tools/list / tools/call / ping

直接运行（供 MCP Client 拉起，不要手动执行）：
    python -m backend.mcp_client.mock_server
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta
from typing import Any

SERVER_INFO = {"name": "nova-mock-mail-calendar", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _mock_emails() -> list[dict[str, Any]]:
    return [
        {
            "id": "m1",
            "from": "张伟 <zhangwei@example.com>",
            "subject": "周三产品评审会议材料",
            "time": f"{_today()} 08:42",
            "unread": True,
            "summary": "附件是评审用的需求文档 v2，麻烦会前过一遍第 3 章。",
        },
        {
            "id": "m2",
            "from": "GitHub <notifications@github.com>",
            "subject": "[nova-secretary] PR #42 已合并",
            "time": f"{_today()} 07:15",
            "unread": True,
            "summary": "feat: 人工确认卡片支持超时自动取消，已合并到 main。",
        },
        {
            "id": "m3",
            "from": "财务部 <finance@example.com>",
            "subject": "9 月报销单已通过审核",
            "time": "昨天 18:30",
            "unread": False,
            "summary": "报销金额 1,286.00 元，预计 3 个工作日内到账。",
        },
    ]


def _mock_events() -> list[dict[str, Any]]:
    return [
        {
            "title": "产品评审会",
            "start": f"{_today()} 10:00",
            "end": f"{_today()} 11:00",
            "location": "会议室 A / 飞书",
            "attendees": ["张伟", "李娜"],
        },
        {
            "title": "与设计对齐悬浮球交互",
            "start": f"{_today()} 14:30",
            "end": f"{_today()} 15:00",
            "location": "线上",
            "attendees": ["王敏"],
        },
        {
            "title": "周报提交截止",
            "start": f"{_today()} 18:00",
            "end": f"{_today()} 18:00",
            "location": "—",
            "attendees": [],
        },
    ]


TOOLS: list[dict[str, Any]] = [
    {
        "name": "email_list_today",
        "description": "查询今日邮件摘要列表（只读）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "email_read_detail",
        "description": "根据邮件 id 读取单封邮件全文（只读）。",
        "inputSchema": {
            "type": "object",
            "properties": {"email_id": {"type": "string", "description": "邮件 id"}},
            "required": ["email_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calendar_list_today",
        "description": "查询今日日程 / 会议列表（只读）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "email_send",
        "description": "发送邮件（带副作用，调用前必须人工确认）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "收件人邮箱"},
                "subject": {"type": "string", "description": "邮件主题"},
                "body": {"type": "string", "description": "邮件正文"},
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calendar_create",
        "description": "新建日程（带副作用，调用前必须人工确认）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "日程标题"},
                "start_time": {"type": "string", "description": "开始时间 YYYY-MM-DD HH:MM"},
                "end_time": {"type": "string", "description": "结束时间 YYYY-MM-DD HH:MM"},
                "location": {"type": "string", "description": "地点"},
                "description": {"type": "string", "description": "备注"},
            },
            "required": ["title", "start_time"],
            "additionalProperties": False,
        },
    },
]


def _text(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "email_list_today":
        emails = _mock_emails()
        return _text(
            {
                "date": _today(),
                "count": len(emails),
                "unread": sum(1 for item in emails if item["unread"]),
                "emails": emails,
                "source": "mock",
            }
        )

    if name == "email_read_detail":
        email_id = str(args.get("email_id") or "").strip()
        for email in _mock_emails():
            if email["id"] == email_id:
                return _text(
                    {
                        **email,
                        "body": (
                            f"{email['summary']}\n\n"
                            "补充说明：\n"
                            "1. 会议材料已放入共享盘；\n"
                            "2. 请重点关注第 3 章「人工确认交互」；\n"
                            "3. 如时间冲突请提前在群里说明。\n\n"
                            "—— 本地 Mock MCP 数据，仅用于链路联调"
                        ),
                    }
                )
        return _text(f"未找到邮件：{email_id}", is_error=True)

    if name == "calendar_list_today":
        events = _mock_events()
        return _text({"date": _today(), "count": len(events), "events": events, "source": "mock"})

    if name == "email_send":
        to = str(args.get("to") or "").strip()
        subject = str(args.get("subject") or "").strip()
        body = str(args.get("body") or "").strip()
        if "@" not in to:
            return _text("收件人邮箱不合法", is_error=True)
        if not subject or not body:
            return _text("邮件主题和正文不能为空", is_error=True)
        return _text(
            {
                "status": "sent",
                "message_id": f"mock-{uuid.uuid4().hex[:10]}",
                "to": to,
                "subject": subject,
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "note": "本地 Mock MCP：未真实发送邮件",
            }
        )

    if name == "calendar_create":
        title = str(args.get("title") or "").strip()
        start_time = str(args.get("start_time") or "").strip()
        end_time = str(args.get("end_time") or "").strip()
        if not title or not start_time:
            return _text("日程标题和开始时间不能为空", is_error=True)
        try:
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        except ValueError:
            return _text("开始时间格式需为 YYYY-MM-DD HH:MM", is_error=True)
        if not end_time:
            end_time = (start_dt + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
        return _text(
            {
                "status": "created",
                "event_id": f"mock-{uuid.uuid4().hex[:8]}",
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "location": str(args.get("location") or ""),
                "note": "本地 Mock MCP：未真实写入日历",
            }
        )

    return _text(f"未知工具：{name}", is_error=True)


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None  # 通知无需响应
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            result = _call_tool(name, arguments)
        except Exception as exc:  # Mock Server 不因单个工具异常退出
            result = _text(f"工具执行失败：{exc}", is_error=True)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    # 日志只走 stderr，stdout 专用于 JSON-RPC 消息
    print("[mock-mcp] started", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            response = _handle(request) if isinstance(request, dict) else None
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
