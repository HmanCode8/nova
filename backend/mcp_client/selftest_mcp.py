r"""Mock MCP 邮件 / 日历链路自测（不需要 LLM）。

覆盖：stdio 连接、tools/list、5 个工具调用、参数错误分支、人工确认硬校验。

运行（PowerShell）：
    $env:Path="$env:USERPROFILE\.local\bin;$env:Path"
    $env:PYTHONPATH="e:\nova-secretary"
    uv run --project backend python -m backend.mcp_client.selftest_mcp
"""

from __future__ import annotations

import asyncio
import json

from backend.mcp_client.client import MCPError, close_all_clients, get_client
from backend.tools.tool_hook import hard_validate


def _parse(text: str) -> dict:
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


async def main() -> int:
    errors: list[str] = []
    mail = await get_client("mail")
    calendar = await get_client("calendar")

    mail_tools = {str(item.get("name")) for item in await mail.list_tools()}
    calendar_tools = {str(item.get("name")) for item in await calendar.list_tools()}
    print(f"1) mail tools：{sorted(mail_tools)}")
    print(f"   calendar tools：{sorted(calendar_tools)}")
    if not {"email_list_today", "email_read_detail", "email_send"}.issubset(mail_tools):
        errors.append("mail 服务缺少邮件工具")
    if not {"calendar_list_today", "calendar_create"}.issubset(calendar_tools):
        errors.append("calendar 服务缺少日程工具")

    emails = _parse(await mail.call_tool("email_list_today", {}))
    print(f"2) email_list_today：{emails.get('count')} 封，未读 {emails.get('unread')}")
    if int(emails.get("count") or 0) < 1:
        errors.append("email_list_today 返回空列表")

    detail = _parse(await mail.call_tool("email_read_detail", {"email_id": "m1"}))
    print(f"3) email_read_detail：{str(detail.get('subject'))[:30]}")
    if not detail.get("body"):
        errors.append("email_read_detail 未返回正文")

    events = _parse(await calendar.call_tool("calendar_list_today", {}))
    print(f"4) calendar_list_today：{events.get('count')} 个日程")
    if int(events.get("count") or 0) < 1:
        errors.append("calendar_list_today 返回空列表")

    sent = _parse(
        await mail.call_tool(
            "email_send", {"to": "test@example.com", "subject": "自测邮件", "body": "链路自测"}
        )
    )
    print(f"5) email_send：{sent.get('status')} / {sent.get('message_id')}")
    if sent.get("status") != "sent":
        errors.append("email_send 未返回 sent")

    created = _parse(
        await calendar.call_tool(
            "calendar_create",
            {"title": "链路自测日程", "start_time": "2026-10-30 09:00", "end_time": "2026-10-30 09:30"},
        )
    )
    print(f"6) calendar_create：{created.get('status')} / {created.get('event_id')}")
    if created.get("status") != "created":
        errors.append("calendar_create 未返回 created")

    print("7) 参数错误分支……")
    try:
        await mail.call_tool("email_send", {"to": "bad", "subject": "x", "body": "y"})
        errors.append("email_send 未拦截非法收件人")
    except MCPError as exc:
        print(f"   非法收件人已拦截：{exc}")
    try:
        await calendar.call_tool(
            "calendar_create", {"title": "错误时间", "start_time": "明天上午"}
        )
        errors.append("calendar_create 未拦截非法时间")
    except MCPError as exc:
        print(f"   非法时间已拦截：{exc}")

    print("8) 人工确认硬校验……")
    if await hard_validate("email_send", {"to": "a@b.com", "subject": "s", "body": "b"}):
        errors.append("正常 email_send 参数被误拦截")
    if not await hard_validate("email_send", {"to": "no-at", "subject": "s", "body": "b"}):
        errors.append("非法 email_send 参数未被拦截")
    if not await hard_validate(
        "calendar_create", {"title": "x", "start_time": "2026-10-30 09:00", "end_time": "2026-10-30 08:00"}
    ):
        errors.append("结束时间早于开始时间未被拦截")

    await close_all_clients()

    if errors:
        print("\n❌ 自测失败：")
        for item in errors:
            print(f" - {item}")
        return 1
    print("\n✅ Mock MCP 邮件 / 日历链路自测通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
