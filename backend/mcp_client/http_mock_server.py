"""本地 Streamable HTTP MCP 测试服务（仅用于验证 HTTP 传输链路）。

启动：
    uv run uvicorn backend.mcp_client.http_mock_server:app --port 8765

端点：POST http://127.0.0.1:8765/mcp
- 支持 initialize / notifications/initialized / tools/list / tools/call
- 请求头带 Accept: text/event-stream 时用 SSE 返回，否则返回 JSON（覆盖两条解析分支）
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import FastAPI, Request, Response

PROTOCOL_VERSION = "2025-03-26"
SESSION_HEADER = "Mcp-Session-Id"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "http_ping",
        "description": "返回一条固定文本，用于验证 HTTP MCP 链路是否连通。",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
        },
    },
    {
        "name": "http_now",
        "description": "返回当前服务器时间。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

app = FastAPI(title="Nova HTTP MCP Mock")


def _text(value: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": value}]}


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    payload = await request.json()
    method = payload.get("method")
    request_id = payload.get("id")
    wants_sse = "text/event-stream" in (request.headers.get("accept") or "")
    session_id = request.headers.get(SESSION_HEADER) or ""

    if method == "initialize":
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "nova-http-mock", "version": "0.1.0"},
            },
        }
        headers = {SESSION_HEADER: session_id or uuid.uuid4().hex}
        return _respond(message, headers, wants_sse)

    if method == "notifications/initialized":
        return Response(status_code=202)

    if method == "tools/list":
        return _respond(
            {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}},
            {SESSION_HEADER: session_id},
            wants_sse,
        )

    if method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "http_ping":
            message = _text(f"pong:{arguments.get('text', '')}")
        elif name == "http_now":
            from datetime import datetime

            message = _text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        else:
            return _respond(
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"未知工具 {name}"}},
                {SESSION_HEADER: session_id},
                wants_sse,
            )
        return _respond(
            {"jsonrpc": "2.0", "id": request_id, "result": message},
            {SESSION_HEADER: session_id},
            wants_sse,
        )

    return _respond(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"未实现 {method}"}},
        {SESSION_HEADER: session_id},
        wants_sse,
    )


def _respond(message: dict[str, Any], headers: dict[str, str], sse: bool) -> Response:
    if sse:
        body = f"event: message\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"
        return Response(
            content=body,
            media_type="text/event-stream",
            headers={**headers, "Cache-Control": "no-cache"},
        )
    return Response(content=json.dumps(message, ensure_ascii=False), media_type="application/json", headers=headers)
