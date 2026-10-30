"""MCP 管理器（FINAL_DEVELOPMENT_DOC 第七章）。

职责：
1. 商店：目录浏览 + 安装 / 卸载 / 配置 / 启停
2. 进程：复用 mcp_client.MCPClient（stdio 常驻，进程退出自动重连）
3. 工具发现：连接后 tools/list，包装成 BaseTool 注册进 Agent
4. 中间件：MCP 工具不单独做校验，统一走 tools 层的中间件链路

设计取舍：激活（拉起进程 + 发现工具）是慢操作，放在启动后台任务与安装/启停时执行，
`build_tools()` 只读缓存，避免每次构建 Graph 都启动子进程。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from backend.mcp_client.client import MCPClient, MCPError
from backend.mcp_client.http_client import MCPHttpClient, MCPHttpError, resolve_env
from backend.mcp_manager import store
from backend.mcp_manager.adapter import build_mcp_tool

logger = logging.getLogger("nova.mcp_manager")

ACTIVATE_TIMEOUT = 60


class McpManager:
    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, list[Any]] = {}
        self._errors: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # -- 生命周期 ---------------------------------------------------------

    async def activate_all(self) -> None:
        """启动时激活全部已启用的 MCP（失败只记录错误，不阻断服务）。"""
        try:
            records = await store.list_all()
        except Exception:
            return
        for record in records:
            if record.get("enabled"):
                await self._activate(record)

    async def refresh(self) -> None:
        """配置变更后重建全部连接。"""
        async with self._lock:
            for client in self._clients.values():
                try:
                    await client.close()
                except Exception:
                    pass
            self._clients.clear()
            self._tools.clear()
            self._errors.clear()
        await self.activate_all()

    async def close(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
        self._tools.clear()

    # -- 内部：激活单个服务 ------------------------------------------------

    def _make_client(self, record: dict[str, Any]) -> Any:
        server_id = str(record["id"])
        if record.get("transport") == store.TRANSPORT_HTTP:
            return MCPHttpClient(
                name=f"mcp:{server_id}",
                url=str(record.get("url") or ""),
                headers=record.get("headers") or {},
            )

        command = str(record.get("command") or "")
        args = [str(item) for item in record.get("args") or []]
        # 密钥类 env 在库里是 ${KEY} 占位，真实值从 .env / 进程环境取
        env: dict[str, str] = {}
        for key, value in (record.get("env") or {}).items():
            resolved = resolve_env(str(value))
            if resolved:
                env[str(key)] = resolved

        async def provider() -> list[str]:
            return [command, *args]

        return MCPClient(name=f"mcp:{server_id}", command_provider=provider, env=env)

    async def _activate(self, record: dict[str, Any]) -> None:
        server_id = str(record["id"])
        server_name = str(record.get("name") or server_id)
        # 配置可能刚被编辑过：先关掉旧连接，按最新配置重建，避免 HTTP 地址/请求头残留旧值
        previous = self._clients.pop(server_id, None)
        if previous is not None:
            try:
                await previous.close()
            except Exception:
                pass
        client = self._make_client(record)
        self._clients[server_id] = client

        def caller_factory():
            async def caller(tool_name: str, arguments: dict[str, Any]) -> str:
                return await client.call_tool(tool_name, arguments)

            return caller

        try:
            definitions = await asyncio.wait_for(client.list_tools(), timeout=ACTIVATE_TIMEOUT)
        except (MCPError, MCPHttpError, asyncio.TimeoutError, Exception) as exc:  # 启动失败不影响其它服务
            message = str(exc) or exc.__class__.__name__
            self._errors[server_id] = message
            self._tools.pop(server_id, None)
            logger.warning("[MCP] %s 激活失败：%s", server_id, message)
            return

        caller = caller_factory()
        tools = []
        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            tool = build_mcp_tool(server_id, server_name, definition, caller)
            if tool is not None:
                tools.append(tool)
        self._tools[server_id] = tools
        self._errors.pop(server_id, None)
        logger.info("[MCP] %s 已激活，工具 %d 个", server_id, len(tools))

    # -- 对外接口 ---------------------------------------------------------

    async def list_servers(self) -> list[dict[str, Any]]:
        """已安装服务 + 运行状态 + 工具清单（供商店管理页展示）。"""
        records = await store.list_all()
        items: list[dict[str, Any]] = []
        for record in records:
            server_id = str(record["id"])
            running = server_id in self._tools
            items.append(
                {
                    **record,
                    "status": "running" if running else ("error" if server_id in self._errors else "stopped"),
                    "error": self._errors.get(server_id, ""),
                    "tools": [tool.name for tool in self._tools.get(server_id, [])],
                    "tool_count": len(self._tools.get(server_id, [])),
                }
            )
        return items

    async def install(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = await store.upsert(payload)
        if record.get("enabled"):
            await self._activate(record)
        return record

    async def uninstall(self, server_id: str) -> bool:
        client = self._clients.pop(server_id, None)
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
        self._tools.pop(server_id, None)
        self._errors.pop(server_id, None)
        return await store.remove(server_id)

    async def set_enabled(self, server_id: str, enabled: bool) -> bool:
        if not await store.set_enabled(server_id, enabled):
            return False
        if enabled:
            record = await store.get(server_id)
            if record:
                await self._activate(record)
        else:
            client = self._clients.pop(server_id, None)
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
            self._tools.pop(server_id, None)
            self._errors.pop(server_id, None)
        return True

    async def discover(self, server_id: str) -> dict[str, Any]:
        """测试连接并返回工具清单（安装弹窗里的「测试」按钮）。"""
        record = await store.get(server_id)
        if record is None:
            raise ValueError("MCP 服务不存在")
        await self._activate(record)
        if server_id in self._errors:
            return {"ok": False, "message": self._errors[server_id], "tools": []}
        tools = [
            {"name": tool.name, "description": (tool.description or "")[:200]}
            for tool in self._tools.get(server_id, [])
        ]
        return {"ok": True, "message": f"连接成功，发现 {len(tools)} 个工具", "tools": tools}

    async def build_tools(self) -> list[Any]:
        """返回全部已激活 MCP 工具（只读缓存）。"""
        tools: list[Any] = []
        for items in self._tools.values():
            tools.extend(items)
        return tools


_MANAGER: Optional[McpManager] = None


def get_manager() -> McpManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = McpManager()
    return _MANAGER
