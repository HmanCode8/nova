"""MCP Streamable HTTP 客户端（协议版本 2025-03-26）。

与 stdio 客户端（client.py）对外接口保持一致：ensure_connected / list_tools / call_tool / close，
这样 McpManager 无需区分传输方式。

协议要点：
- 所有请求走 POST {url}，头部 Accept: application/json, text/event-stream
- 响应可能是 application/json，也可能是 text/event-stream（逐条 data: {...}）
- initialize 响应头里的 Mcp-Session-Id 需要带回后续每个请求
- notifications/initialized 是通知（无 id），服务端通常返回 202/204
- 请求头支持 ${ENV_NAME} 占位，运行时从 .env / 环境变量取，避免把 token 写死在配置里
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger("nova.mcp.http")

PROTOCOL_VERSION = "2025-03-26"
_CLIENT_INFO = {"name": "NovaSecretary", "version": "0.2.0"}
_ENV_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_ENV_INLINE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MCPHttpError(RuntimeError):
    """HTTP 传输层错误。"""


def resolve_env(value: str) -> str:
    """把 ${ENV_NAME} 解析成环境变量值；不是占位则原样返回。"""
    match = _ENV_PATTERN.match((value or "").strip())
    if not match:
        return value
    return os.getenv(match.group(1), "")


def expand_env(value: str) -> str:
    """把文本里任意位置的 ${ENV_NAME} 替换成环境变量值（URL 查询串里的 ?key=${X} 用）。"""
    return _ENV_INLINE.sub(lambda m: os.getenv(m.group(1), ""), value or "")


def resolve_headers(headers: Optional[dict[str, Any]]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, value in (headers or {}).items():
        text = expand_env(str(value))
        if text:
            resolved[str(key)] = text
    return resolved


class MCPHttpClient:
    """一条 Streamable HTTP 连接（无长连接进程，靠 session id 维系）。"""

    def __init__(
        self,
        name: str,
        url: str,
        headers: Optional[dict[str, Any]] = None,
        timeout: float = 60,
    ) -> None:
        self.name = name
        self.url = expand_env(url)  # 支持 ?key=${MCP_XXX_KEY} 这类占位
        self._headers = resolve_headers(headers)
        self._timeout = timeout
        self._session_id = ""
        self._ready = False
        self._next_id = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._local = self.url.startswith(("http://127.0.0.1", "http://localhost"))

    # -- 生命周期 ---------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                trust_env=not self._local,  # 本机地址绕开系统代理，避免 502
            )
        return self._client

    async def ensure_connected(self) -> None:
        if self._ready and self._session_id:
            return
        await self._initialize()

    async def close(self) -> None:
        self._ready = False
        self._session_id = ""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    # -- 协议 -------------------------------------------------------------

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        client = await self._ensure_client()
        try:
            response = await client.post(self.url, json=payload, headers=self._base_headers())
        except httpx.HTTPError as exc:
            raise MCPHttpError(f"HTTP 请求失败：{exc}") from exc

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        if response.status_code >= 400:
            detail = (response.text or "")[:300].replace("\n", " ")
            raise MCPHttpError(f"MCP HTTP {response.status_code}：{detail}")

        if "id" not in payload:  # 通知类请求不期待响应体
            return None

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text, payload.get("id"))
        try:
            return response.json()
        except ValueError as exc:
            raise MCPHttpError("响应不是 JSON 或 SSE，请确认地址是 MCP Streamable HTTP 端点") from exc

    def _parse_sse(self, text: str, request_id: Any) -> Optional[dict[str, Any]]:
        """从 SSE 文本里挑出 id 匹配的那条 JSON-RPC 响应。"""
        fallback: Optional[dict[str, Any]] = None
        for line in (text or "").splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                message = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("id") == request_id:
                return message
            fallback = message if "result" in message or "error" in message else fallback
        return fallback

    @staticmethod
    def _unwrap(message: Optional[dict[str, Any]]) -> dict[str, Any]:
        if message is None:
            return {}
        if "error" in message:
            error = message.get("error") or {}
            raise MCPHttpError(str(error.get("message") or error))
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    async def _initialize(self) -> None:
        self._next_id += 1
        await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": _CLIENT_INFO,
                },
            }
        )
        await self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        self._ready = True
        logger.info("[%s] HTTP 已连接（session=%s）", self.name, self._session_id or "-")

    # -- 业务接口 ---------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.ensure_connected()
        self._next_id += 1
        result = self._unwrap(
            await self._post(
                {"jsonrpc": "2.0", "id": self._next_id, "method": "tools/list", "params": {}}
            )
        )
        tools = result.get("tools")
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        await self.ensure_connected()
        self._next_id += 1
        result = self._unwrap(
            await self._post(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}},
                }
            )
        )
        content = result.get("content")
        texts: list[str] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(str(block.get("text") or ""))
        text = "\n".join(item for item in texts if item)
        if result.get("isError"):
            raise MCPHttpError(text or f"工具 {name} 执行失败")
        return text or json.dumps(result, ensure_ascii=False)
