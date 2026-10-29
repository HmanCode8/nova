"""MCP Client：stdio 方式连接本地 / 远程 MCP Server（JSON-RPC 2.0，换行分隔）。

- 支持任意启动命令（Python 内置 Server、npx 拉起的官方 Server）
- 每次调用前重新计算启动命令：token 刷新后自动重启子进程
- 进程常驻复用；进程退出后下次调用自动重连
- 只实现 tools/list + tools/call 子集
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("nova.mcp")


class MCPError(RuntimeError):
    """MCP 通信或工具执行错误。"""


class MCPAuthRequired(MCPError):
    """需要用户先完成授权（例如飞书 OAuth 登录）。"""


CommandProvider = Callable[[], Awaitable[list[str]]]


def _resolve_executable(name: str) -> str:
    """解析可执行文件；Windows 下 npx/npm 是 .cmd，create_subprocess_exec 需要完整路径。"""
    if os.name == "nt" and name in ("npx", "npm", "npx.cmd", "npm.cmd"):
        found = shutil.which("npx.cmd" if name.startswith("npx") else "npm.cmd")
    else:
        found = shutil.which(name)
    return found or name


class MCPClient:
    """一条常驻 stdio 连接。"""

    def __init__(
        self,
        name: str,
        command_provider: CommandProvider,
        env: Optional[dict[str, str]] = None,
        cwd: Path = PROJECT_ROOT,
    ) -> None:
        self.name = name
        self._command_provider = command_provider
        self._env = env or {}
        self._cwd = cwd
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.Task] = None
        self._stderr_reader: Optional[asyncio.Task] = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._lock = asyncio.Lock()
        self._ready = False
        self._command: list[str] = []

    # -- 生命周期 ---------------------------------------------------------

    async def _spawn(self, command: list[str]) -> None:
        env = dict(os.environ)
        env.update(self._env)
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        executable = _resolve_executable(command[0])
        self._proc = await asyncio.create_subprocess_exec(
            executable,
            *command[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._cwd),
            env=env,
        )
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "NovaSecretary", "version": "0.1.0"},
            },
            timeout=30,
        )
        await self._notify("notifications/initialized", {})
        self._ready = True
        logger.info("[%s] 已连接（pid=%s）", self.name, self._proc.pid)

    async def ensure_connected(self) -> None:
        command = await self._command_provider()
        if (
            self._ready
            and self._proc
            and self._proc.returncode is None
            and command == self._command
        ):
            return
        # 命令变化（例如用户 token 刷新）或进程已退出：重建连接
        await self.close()
        self._command = command
        await self._spawn(command)

    async def close(self) -> None:
        self._ready = False
        proc = self._proc
        self._proc = None
        # 先结束子进程，让读取任务自然读到 EOF，避免 Windows 管道资源警告
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3)
            except Exception:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except Exception:
                    pass
        for task in (self._reader, self._stderr_reader):
            if task and not task.done():
                task.cancel()
            if task:
                try:
                    await asyncio.wait_for(task, timeout=2)
                except BaseException:  # 已取消 / 已结束都忽略
                    pass
        self._reader = None
        self._stderr_reader = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPError("MCP 连接已关闭"))
        self._pending.clear()

    # -- 读取循环 ---------------------------------------------------------

    async def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "ignore").strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning("[%s] 忽略非法消息：%s", self.name, text[:200])
                    continue
                message_id = message.get("id")
                future = self._pending.pop(message_id, None) if isinstance(message_id, int) else None
                if future and not future.done():
                    future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[%s] 读取失败", self.name)
        finally:
            self._ready = False
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(MCPError("MCP Server 已退出"))
            self._pending.clear()

    async def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", "ignore").rstrip()
                if text:
                    logger.info("[%s] %s", self.name, text[:400])
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    # -- 协议 -------------------------------------------------------------

    async def _write(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise MCPError("MCP Server 未运行")
        proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(
        self, method: str, params: dict[str, Any], timeout: float = 30
    ) -> dict[str, Any]:
        async with self._lock:
            self._next_id += 1
            request_id = self._next_id
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            try:
                await self._write(
                    {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
                )
                message = await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                raise MCPError(f"MCP 请求超时：{method}") from None
            finally:
                self._pending.pop(request_id, None)

            if "error" in message:
                error = message["error"] or {}
                raise MCPError(str(error.get("message") or error))
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    # -- 业务接口 ---------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.ensure_connected()
        result = await self._request("tools/list", {})
        tools = result.get("tools")
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        await self.ensure_connected()
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}, timeout=90
        )
        content = result.get("content")
        texts: list[str] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(str(block.get("text") or ""))
        text = "\n".join(item for item in texts if item)
        if result.get("isError"):
            raise MCPError(text or f"工具 {name} 执行失败")
        return text or json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 客户端注册表：按服务名复用连接
# ---------------------------------------------------------------------------

_clients: dict[str, MCPClient] = {}
_client_lock = asyncio.Lock()


async def get_client(name: str) -> MCPClient:
    """获取指定服务（mail / calendar）的常驻连接。"""
    from backend.mcp_client.servers import get_server_spec  # 延迟导入避免循环依赖

    client = _clients.get(name)
    if client is None:
        async with _client_lock:
            client = _clients.get(name)
            if client is None:
                spec = await get_server_spec(name)
                client = MCPClient(
                    name=name, command_provider=spec.command_provider, env=spec.env
                )
                _clients[name] = client
    return client


async def close_all_clients() -> None:
    for client in list(_clients.values()):
        await client.close()
    _clients.clear()


# 兼容旧调用：阶段2.5 初版只连一个 Mock Server
async def close_client() -> None:
    await close_all_clients()
