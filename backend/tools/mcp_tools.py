"""MCP 邮件 / 日历工具：对 Agent 暴露的 LangChain 工具包装。

- 邮件：Mock 服务 或 飞书邮箱 IMAP/SMTP 服务（NOVA_MAIL_PROVIDER=imap）
- 日历：Mock 服务 或 飞书官方 lark-mcp（NOVA_CALENDAR_PROVIDER=feishu）
- 返回结构统一为前端卡片可直接渲染的 JSON，切换数据源前端无感知
- email_send / calendar_create 带副作用，由 agent_graph 的 gate 节点统一人工确认
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from langchain_core.tools import tool

from backend.mcp_client.client import MCPError, get_client
from backend.mcp_client.servers import calendar_provider

FEISHU_TOOL_PRIMARY = "calendar_v4_calendar_primary"
FEISHU_TOOL_LIST = "calendar_v4_calendarEvent_list"
FEISHU_TOOL_CREATE = "calendar_v4_calendarEvent_create"
TIMEZONE = "Asia/Shanghai"

_primary_cache: dict[str, Any] = {"calendar_id": "", "expires_at": 0.0}


async def _call(server: str, tool_name: str, arguments: dict[str, Any]) -> str:
    client = await get_client(server)
    return await client.call_tool(tool_name, arguments)


def _parse(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_calendar(node: Any) -> dict[str, Any] | None:
    """递归查找带 calendar_id 的日历对象（兼容不同返回层级）。"""
    if isinstance(node, dict):
        calendar = node.get("calendar")
        if isinstance(calendar, dict) and calendar.get("calendar_id"):
            return calendar
        if node.get("calendar_id"):
            return node
        for value in node.values():
            found = _find_calendar(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_calendar(value)
            if found:
                return found
    return None


def _find_events(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        items = node.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        for value in node.values():
            found = _find_events(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_events(value)
            if found:
                return found
    return []


def _find_event(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        event = node.get("event")
        if isinstance(event, dict) and event.get("event_id"):
            return event
        if node.get("event_id"):
            return node
        for value in node.values():
            found = _find_event(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_event(value)
            if found:
                return found
    return None


def _format_bound(bound: Any) -> str:
    if not isinstance(bound, dict):
        return ""
    if bound.get("date"):
        return str(bound["date"])
    timestamp = bound.get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return str(timestamp)
    return ""


def _attendees(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for person in item.get("attendees") or []:
        if not isinstance(person, dict):
            continue
        name = person.get("display_name") or person.get("user_id") or ""
        if name:
            names.append(str(name))
    return names


async def _primary_calendar_id() -> str:
    now = time.time()
    if _primary_cache["calendar_id"] and float(_primary_cache["expires_at"]) > now:
        return str(_primary_cache["calendar_id"])
    text = await _call("calendar", FEISHU_TOOL_PRIMARY, {"params": {}, "useUAT": True})
    calendar = _find_calendar(_parse(text))
    if not calendar or not calendar.get("calendar_id"):
        raise MCPError(f"未获取到飞书主日历：{text[:300]}")
    calendar_id = str(calendar["calendar_id"])
    _primary_cache.update(calendar_id=calendar_id, expires_at=now + 3600)
    return calendar_id


def _today_range() -> tuple[int, int]:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


async def _feishu_list_today() -> str:
    calendar_id = await _primary_calendar_id()
    start, end = _today_range()
    text = await _call(
        "calendar",
        FEISHU_TOOL_LIST,
        {
            "params": {
                "start_time": str(start),
                "end_time": str(end),
                "page_size": 100,
            },
            "path": {"calendar_id": calendar_id},
            "useUAT": True,
        },
    )
    events: list[dict[str, Any]] = []
    for item in _find_events(_parse(text)):
        if str(item.get("status") or "").lower() == "cancelled":
            continue
        events.append(
            {
                "title": str(item.get("summary") or "（无标题日程）"),
                "start": _format_bound(item.get("start_time")),
                "end": _format_bound(item.get("end_time")),
                "location": str((item.get("location") or {}).get("name") or ""),
                "attendees": _attendees(item),
            }
        )
    events.sort(key=lambda item: item["start"])
    return json.dumps(
        {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(events),
            "events": events,
            "source": "feishu",
        },
        ensure_ascii=False,
    )


async def _feishu_create(
    title: str, start_time: str, end_time: str, location: str, description: str
) -> str:
    calendar_id = await _primary_calendar_id()
    try:
        start = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
    except ValueError:
        raise MCPError("开始时间格式需为 YYYY-MM-DD HH:MM") from None
    if end_time:
        try:
            end = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
        except ValueError:
            raise MCPError("结束时间格式需为 YYYY-MM-DD HH:MM") from None
    else:
        end = start + timedelta(minutes=30)
    if end <= start:
        raise MCPError("结束时间必须晚于开始时间")

    data: dict[str, Any] = {
        "summary": title,
        "start_time": {"timestamp": str(int(start.timestamp())), "timezone": TIMEZONE},
        "end_time": {"timestamp": str(int(end.timestamp())), "timezone": TIMEZONE},
    }
    if description:
        data["description"] = description
    if location:
        data["location"] = {"name": location}

    text = await _call(
        "calendar",
        FEISHU_TOOL_CREATE,
        {"path": {"calendar_id": calendar_id}, "params": {}, "data": data, "useUAT": True},
    )
    event = _find_event(_parse(text))
    if not event or not event.get("event_id"):
        raise MCPError(f"飞书未返回日程 id：{text[:300]}")
    return json.dumps(
        {
            "status": "created",
            "event_id": str(event["event_id"]),
            "title": title,
            "start_time": start.strftime("%Y-%m-%d %H:%M"),
            "end_time": end.strftime("%Y-%m-%d %H:%M"),
            "location": location,
            "note": "已写入飞书日历",
            "source": "feishu",
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Agent 工具
# ---------------------------------------------------------------------------


@tool
async def email_list_today() -> str:
    """查询今日邮件摘要列表（发件人、主题、时间、是否未读）。只读，无副作用。"""
    return await _call("mail", "email_list_today", {})


@tool
async def email_read_detail(email_id: str) -> str:
    """读取单封邮件全文。email_id 来自 email_list_today 的返回结果。只读，无副作用。"""
    return await _call("mail", "email_read_detail", {"email_id": email_id})


@tool
async def email_send(to: str, subject: str, body: str) -> str:
    """发送邮件。带副作用，系统会在执行前请用户人工确认。

    to：收件人邮箱；subject：主题；body：正文。
    """
    return await _call("mail", "email_send", {"to": to, "subject": subject, "body": body})


@tool
async def calendar_list_today() -> str:
    """查询今日日程与会议（标题、起止时间、地点、参会人）。只读，无副作用。"""
    if calendar_provider() == "feishu":
        return await _feishu_list_today()
    return await _call("calendar", "calendar_list_today", {})


@tool
async def calendar_create(
    title: str,
    start_time: str,
    end_time: str = "",
    location: str = "",
    description: str = "",
) -> str:
    """新建日程。带副作用，系统会在执行前请用户人工确认。

    title：日程标题；start_time / end_time 格式为 YYYY-MM-DD HH:MM；
    end_time 为空时默认开始后 30 分钟；location、description 可选。
    """
    if calendar_provider() == "feishu":
        return await _feishu_create(title, start_time, end_time, location, description)
    return await _call(
        "calendar",
        "calendar_create",
        {
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
            "description": description,
        },
    )
