"""飞书邮箱 MCP Server（IMAP 收信 + SMTP 发信，stdio JSON-RPC 2.0）。

为什么不用 MCP 官方邮箱服务：飞书官方 lark-mcp 不覆盖邮箱，飞书邮箱提供标准
IMAP/SMTP（imap.feishu.cn:993 / smtp.feishu.cn:465），这里把它包装成与 Mock
完全一致的 MCP 工具，Agent 与前端无需区分数据来源。

安全：账号、客户端专用密码只从 backend/.env 读取，不写入 sqlite、不发给前端。

直接运行（供 MCP Client 拉起，不要手动执行）：
    python -m backend.mcp_client.mail_server
"""

from __future__ import annotations

import email
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import uuid
from datetime import datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any

from backend.env_loader import load_env

load_env()

SERVER_INFO = {"name": "nova-feishu-mail", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"

IMAP_HOST = (os.getenv("MAIL_IMAP_HOST") or "imap.feishu.cn").strip()
IMAP_PORT = int(os.getenv("MAIL_IMAP_PORT") or 993)
SMTP_HOST = (os.getenv("MAIL_SMTP_HOST") or "smtp.feishu.cn").strip()
SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT") or 465)
MAILBOX = (os.getenv("MAIL_MAILBOX") or "INBOX").strip()
LIST_LIMIT = int(os.getenv("MAIL_LIST_LIMIT") or 8)
SUMMARY_CHARS = 120
DETAIL_CHARS = 6000

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _log(message: str) -> None:
    print(f"[mail-mcp] {message}", file=sys.stderr, flush=True)


def _credentials() -> tuple[str, str]:
    username = (os.getenv("MAIL_USERNAME") or "").strip()
    password = (os.getenv("MAIL_PASSWORD") or "").strip()
    if not username or not password:
        raise RuntimeError(
            "未配置邮箱：请在 backend/.env 填写 MAIL_USERNAME（完整邮箱地址）"
            "与 MAIL_PASSWORD（飞书邮箱的客户端专用密码）。"
        )
    return username, password


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------

def _imap_date(moment: datetime) -> str:
    # IMAP 日期必须是英文月份缩写，不能用 strftime('%b')（受系统语言影响）
    return f"{moment.day:02d}-{MONTHS[moment.month - 1]}-{moment.year}"


def _connect_imap() -> imaplib.IMAP4_SSL:
    username, password = _credentials()
    try:
        client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
        client.login(username, password)
    except imaplib.IMAP4.error as exc:
        raise RuntimeError(
            f"邮箱登录失败：{exc}。请确认飞书邮箱已开启 IMAP/SMTP，"
            "并使用「客户端专用密码」而不是登录密码。"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"无法连接邮箱服务器 {IMAP_HOST}:{IMAP_PORT}：{exc}") from exc
    try:
        client.select(MAILBOX, readonly=False)
    except imaplib.IMAP4.error as exc:
        raise RuntimeError(f"无法打开邮箱目录 {MAILBOX}：{exc}") from exc
    return client


def _decode(value: Any) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _message_text(message: email.message.Message, limit: int) -> str:
    plain = ""
    html = ""
    if message.is_multipart():
        for part in message.walk():
            disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in disposition:
                continue
            content_type = part.get_content_type()
            if content_type not in ("text/plain", "text/html"):
                continue
            raw = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = raw.decode(charset, "ignore")
            if content_type == "text/plain" and not plain:
                plain = text
            elif content_type == "text/html" and not html:
                html = text
    else:
        raw = message.get_payload(decode=True) or b""
        charset = message.get_content_charset() or "utf-8"
        plain = raw.decode(charset, "ignore")
    text = plain.strip() or _html_to_text(html)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def _fetch_message(client: imaplib.IMAP4_SSL, uid: bytes) -> tuple[email.message.Message, bool]:
    status, data = client.uid("fetch", uid, "(BODY.PEEK[] FLAGS)")
    if status != "OK" or not data:
        raise RuntimeError(f"读取邮件失败（UID {uid.decode()}）")
    raw: bytes | None = None
    unread = True
    for item in data:
        if isinstance(item, tuple):
            header, payload = item[0], item[1]
            if isinstance(payload, bytes):
                raw = payload
            flags = header if isinstance(header, bytes) else b""
            if b"\\Seen" in flags:
                unread = False
    if raw is None:
        raise RuntimeError("邮件内容为空")
    return email.message_from_bytes(raw), unread


def _list_today() -> dict[str, Any]:
    client = _connect_imap()
    try:
        status, data = client.uid("search", None, "SINCE", _imap_date(datetime.now()))
        if status != "OK":
            raise RuntimeError("邮箱搜索失败")
        uids = data[0].split() if data and data[0] else []
        uids = list(reversed(uids))[:LIST_LIMIT]
        emails: list[dict[str, Any]] = []
        unread_count = 0
        for uid in uids:
            message, unread = _fetch_message(client, uid)
            subject = _decode(message.get("Subject")) or "（无主题）"
            sender = _decode(message.get("From")) or "（未知发件人）"
            date_header = message.get("Date")
            try:
                sent = parsedate_to_datetime(date_header) if date_header else datetime.now()
                sent_local = sent.astimezone()
            except Exception:
                sent_local = datetime.now()
            if sent_local.date() == datetime.now().date():
                time_text = sent_local.strftime("%H:%M")
            else:
                time_text = sent_local.strftime("%m-%d %H:%M")
            summary = _message_text(message, SUMMARY_CHARS) or "（无正文摘要）"
            unread_count += 1 if unread else 0
            emails.append(
                {
                    "id": f"uid:{uid.decode()}",
                    "from": sender,
                    "subject": subject,
                    "time": time_text,
                    "unread": unread,
                    "summary": summary,
                }
            )
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(emails),
            "unread": unread_count,
            "emails": emails,
            "source": "imap",
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _read_detail(email_id: str) -> dict[str, Any]:
    uid_text = email_id.strip()
    if uid_text.startswith("uid:"):
        uid_text = uid_text[4:]
    if not uid_text.isdigit():
        raise RuntimeError(f"邮件 id 不合法：{email_id}")
    client = _connect_imap()
    try:
        message, unread = _fetch_message(client, uid_text.encode())
        date_header = message.get("Date")
        try:
            sent = parsedate_to_datetime(date_header).astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            sent = _decode(date_header)
        return {
            "id": f"uid:{uid_text}",
            "from": _decode(message.get("From")),
            "to": _decode(message.get("To")),
            "subject": _decode(message.get("Subject")) or "（无主题）",
            "time": sent,
            "unread": unread,
            "summary": _message_text(message, SUMMARY_CHARS),
            "body": _message_text(message, DETAIL_CHARS),
            "source": "imap",
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------

def _send(to: str, subject: str, body: str) -> dict[str, Any]:
    username, password = _credentials()
    recipient = (to or "").strip()
    if "@" not in recipient:
        raise RuntimeError("收件人邮箱不合法")
    if not subject.strip():
        raise RuntimeError("邮件主题不能为空")
    if not body.strip():
        raise RuntimeError("邮件正文不能为空")

    message = EmailMessage()
    display = (os.getenv("MAIL_FROM_NAME") or "").strip()
    message["From"] = f"{display} <{username}>" if display else username
    message["To"] = recipient
    message["Subject"] = subject
    message["Message-ID"] = f"<{uuid.uuid4().hex}@nova-secretary>"
    message.set_content(body)

    try:
        if SMTP_PORT == 465:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                SMTP_HOST, SMTP_PORT, timeout=30, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        try:
            client.login(username, password)
            client.send_message(message)
        finally:
            try:
                client.quit()
            except Exception:
                pass
    except Exception as exc:
        raise RuntimeError(f"邮件发送失败：{exc}") from exc

    return {
        "status": "sent",
        "message_id": message["Message-ID"],
        "to": recipient,
        "subject": subject,
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": "已通过飞书邮箱 SMTP 发送",
        "source": "imap",
    }


# ---------------------------------------------------------------------------
# MCP 协议（与 mock_server 一致的最小子集）
# ---------------------------------------------------------------------------

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
            "properties": {"email_id": {"type": "string", "description": "邮件 id（uid:xxx）"}},
            "required": ["email_id"],
            "additionalProperties": False,
        },
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
]


def _text(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "email_list_today":
            return _text(_list_today())
        if name == "email_read_detail":
            return _text(_read_detail(str(args.get("email_id") or "")))
        if name == "email_send":
            return _text(
                _send(
                    str(args.get("to") or ""),
                    str(args.get("subject") or ""),
                    str(args.get("body") or ""),
                )
            )
        return _text(f"未知工具：{name}", is_error=True)
    except Exception as exc:
        return _text(f"工具执行失败：{exc}", is_error=True)


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
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        return {"jsonrpc": "2.0", "id": request_id, "result": _call_tool(name, arguments)}
    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    _log("started")
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
