r"""真实服务自测：飞书日历（lark-mcp）+ 飞书邮箱（IMAP/SMTP）。

前置：
1. backend/.env 填好 FEISHU_APP_ID / FEISHU_APP_SECRET，
   并在开放平台配置重定向地址（默认 http://localhost:3000/callback）
2. 首次执行：python -m backend.mcp_client.feishu_auth login
3. 填好 MAIL_USERNAME / MAIL_PASSWORD（飞书邮箱客户端专用密码）
4. 设置 NOVA_CALENDAR_PROVIDER=feishu、NOVA_MAIL_PROVIDER=imap

运行（PowerShell）：
    $env:Path="$env:USERPROFILE\.local\bin;$env:Path"
    $env:PYTHONPATH="e:\nova-secretary"
    uv run --project backend python -m backend.mcp_client.selftest_real_mcp
"""

from __future__ import annotations

import asyncio
import json

from backend.mcp_client.client import MCPAuthRequired, MCPError, close_all_clients, get_client
from backend.mcp_client.servers import calendar_provider, mail_provider
from backend.tools.mcp_tools import calendar_list_today, email_list_today


def _summary(text: str) -> dict:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def main() -> int:
    errors: list[str] = []
    print(f"邮件数据源：{mail_provider()}")
    print(f"日历数据源：{calendar_provider()}")

    if mail_provider() == "mock":
        print("⏭  邮件仍是 Mock，跳过真实邮箱验证")
    else:
        try:
            payload = _summary(await email_list_today.ainvoke({}))
            print(f"📧 今日邮件：{payload.get('count')} 封，未读 {payload.get('unread')}")
            for mail in (payload.get("emails") or [])[:3]:
                print(f"   - [{mail.get('time')}] {mail.get('subject')}（{mail.get('from')}）")
            if int(payload.get("count") or 0) < 1:
                print("   （今日收件箱为空，链路本身正常）")
        except Exception as exc:
            errors.append(f"邮件服务失败：{exc}")

    if calendar_provider() == "mock":
        print("⏭  日历仍是 Mock，跳过真实日历验证")
    else:
        try:
            client = await get_client("calendar")
            tool_names = sorted(str(item.get("name")) for item in await client.list_tools())
            print(f"🔧 lark-mcp 工具：{tool_names}")
            if "calendar_v4_calendarEvent_list" not in tool_names:
                errors.append("lark-mcp 未启用 calendar_v4_calendarEvent_list")
            payload = _summary(await calendar_list_today.ainvoke({}))
            print(f"📅 今日日程：{payload.get('count')} 个")
            for event in (payload.get("events") or [])[:5]:
                print(f"   - {event.get('start')} {event.get('title')}（{event.get('location') or '无地点'}）")
        except MCPAuthRequired as exc:
            errors.append(f"飞书未授权：{exc}")
        except MCPError as exc:
            errors.append(f"日历服务失败：{exc}")
        except Exception as exc:
            errors.append(f"日历服务异常：{exc}")

    await close_all_clients()

    if errors:
        print("\n❌ 真实服务自测未通过：")
        for item in errors:
            print(f" - {item}")
        return 1
    print("\n✅ 真实服务自测通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
