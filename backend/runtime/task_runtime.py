"""Runtime 任务运行时层（FINAL_DEVELOPMENT_DOC 第四章）。

职责：
1. 任务生命周期管理：创建 / 启动 / 停止 / 超时回收
2. 任务上下文隔离：独立 LangGraph thread_id，不污染会话主线程；工具上下文绑定会话
3. 并发控制：限制同时运行的后台任务数
4. 删除确认透传：后台任务里的 interrupt 同样推送 delete_confirm，等待前端确认后 resume
5. 流式日志：token / 工具状态统一转成 task_log 推送

边界：Runtime 只做调度与生命周期，不做任何业务决策。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Optional

from langchain_core.messages import HumanMessage
from langgraph.types import Command

logger = logging.getLogger("nova.runtime")

LOG_FLUSH_CHARS = 240


class TaskRuntime:
    """后台长任务调度器（单进程内）。"""

    def __init__(
        self,
        graph_factory: Callable[[], Awaitable[Any]],
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._graph_factory = graph_factory
        self._broadcast = broadcast
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._closed = False

    # -- 对外接口 ---------------------------------------------------------

    async def submit(self, session_id: str, prompt: str, title: str = "") -> dict[str, Any]:
        """创建并启动一个后台任务。"""
        from backend.storage import task_store
        from backend.storage.config_store import get_config

        text = (prompt or "").strip()
        if not text:
            raise ValueError("任务内容为空")
        config = await get_config()
        max_concurrent = int(config.get("max_concurrent_tasks") or 2)
        if len(self._tasks) >= max_concurrent:
            raise ValueError(
                f"并发任务已达上限（{max_concurrent} 个），请等待现有任务完成或先停止一个"
            )

        record = await task_store.create(session_id, text, title)
        task_id = record["id"]
        runner = asyncio.create_task(self._run(task_id, session_id, text))
        self._tasks[task_id] = runner
        runner.add_done_callback(lambda _t, tid=task_id: self._tasks.pop(tid, None))
        await self._broadcast(
            {
                "type": "task_status",
                "task_id": task_id,
                "status": task_store.STATUS_PENDING,
                "title": record.get("title", ""),
                "session_id": session_id,
            }
        )
        return record

    async def stop(self, task_id: str, reason: str = "user") -> bool:
        """停止任务：取消协程 + 结束挂起的确认。"""
        from backend.storage import task_store

        runner = self._tasks.get(task_id)
        if runner is None or runner.done():
            return False
        for confirm_id, future in list(self._pending.items()):
            if not future.done():
                future.set_result(False)
            self._pending.pop(confirm_id, None)
        runner.cancel()
        await task_store.update(task_id, status=task_store.STATUS_CANCELLED, error=f"已停止（{reason}）")
        await self._broadcast(
            {"type": "task_status", "task_id": task_id, "status": task_store.STATUS_CANCELLED}
        )
        return True

    async def resolve_confirm(self, confirm_id: str, accepted: bool) -> bool:
        """路由前端的删除确认到对应后台任务。"""
        future = self._pending.pop(confirm_id, None)
        if future is None or future.done():
            return False
        future.set_result(bool(accepted))
        return True

    def is_running(self, task_id: str) -> bool:
        runner = self._tasks.get(task_id)
        return bool(runner and not runner.done())

    async def shutdown(self) -> None:
        """优雅退出：取消全部运行中的任务。"""
        self._closed = True
        for task_id in list(self._tasks):
            runner = self._tasks.get(task_id)
            if runner and not runner.done():
                runner.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    # -- 内部执行 ---------------------------------------------------------

    async def _run(self, task_id: str, session_id: str, prompt: str) -> None:
        from backend.storage import task_store
        from backend.storage.config_store import get_config
        from backend.storage.memory_store import CURRENT_SESSION

        config = await get_config()
        timeout = int(config.get("task_timeout_seconds") or 900)

        await task_store.update(task_id, status=task_store.STATUS_RUNNING)
        await self._broadcast(
            {"type": "task_status", "task_id": task_id, "status": task_store.STATUS_RUNNING}
        )

        token = CURRENT_SESSION.set(session_id)
        buffer: list[str] = []
        collected: list[str] = []
        try:
            await asyncio.wait_for(
                self._drive(task_id, session_id, prompt, buffer, collected),
                timeout=max(30, timeout),
            )
        except asyncio.TimeoutError:
            await self._flush(task_id, buffer)
            message = f"任务超时（{timeout} 秒）已回收"
            await task_store.update(task_id, status=task_store.STATUS_TIMEOUT, error=message)
            await self._broadcast(
                {"type": "task_status", "task_id": task_id, "status": task_store.STATUS_TIMEOUT, "error": message}
            )
        except asyncio.CancelledError:
            await self._flush(task_id, buffer)
            raise
        except Exception as exc:  # 任务异常不拖垮服务
            logger.exception("后台任务失败：%s", task_id)
            await self._flush(task_id, buffer)
            await task_store.update(task_id, status=task_store.STATUS_FAILED, error=str(exc))
            await self._broadcast(
                {"type": "task_status", "task_id": task_id, "status": task_store.STATUS_FAILED, "error": str(exc)}
            )
        else:
            await self._flush(task_id, buffer)
            result = "".join(collected).strip()
            await task_store.update(
                task_id, status=task_store.STATUS_SUCCESS, result=result or "（无文本输出）"
            )
            await self._broadcast(
                {
                    "type": "task_status",
                    "task_id": task_id,
                    "status": task_store.STATUS_SUCCESS,
                    "result": result,
                }
            )
        finally:
            CURRENT_SESSION.reset(token)

    async def _drive(
        self,
        task_id: str,
        session_id: str,
        prompt: str,
        buffer: list[str],
        collected: list[str],
    ) -> None:
        """驱动 Agent 图直到结束；遇到 interrupt 就等待确认后 resume。"""
        from backend.agent.agent_graph import extract_interrupt, thread_config
        from backend.storage import task_store

        graph = await self._graph_factory()
        # 独立 thread：后台任务与主会话互不干扰（上下文隔离）
        cfg = thread_config(f"task:{task_id}")
        graph_input: Any = {
            "messages": [HumanMessage(content=prompt)],
            "session_id": session_id,
        }

        while True:
            interrupt_payload: Optional[dict[str, Any]] = None
            async for mode, data in graph.astream(
                graph_input, config=cfg, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, metadata = data
                    if metadata.get("langgraph_node") not in ("agent", "finalize"):
                        continue
                    delta = _chunk_text(chunk)
                    if not delta:
                        continue
                    collected.append(delta)
                    buffer.append(delta)
                    if "\n" in delta or sum(len(item) for item in buffer) >= LOG_FLUSH_CHARS:
                        await self._flush(task_id, buffer)
                    continue

                if not isinstance(data, dict):
                    continue
                if "__interrupt__" in data:
                    interrupt_payload = extract_interrupt(data)
                    continue
                if "agent" in data:
                    for msg in data["agent"].get("messages", []):
                        for call in getattr(msg, "tool_calls", None) or []:
                            await self._broadcast(
                                {
                                    "type": "tool_status",
                                    "task_id": task_id,
                                    "tool_name": call.get("name", ""),
                                    "status": "running",
                                }
                            )
                if "tools" in data:
                    for msg in data["tools"].get("messages", []):
                        name = getattr(msg, "name", "") or ""
                        await self._broadcast(
                            {
                                "type": "tool_status",
                                "task_id": task_id,
                                "tool_name": name,
                                "status": "done",
                            }
                        )
                        await self._broadcast(
                            {
                                "type": "task_log",
                                "task_id": task_id,
                                "log": f"[工具] {name} 完成",
                            }
                        )

            if interrupt_payload is None:
                return

            accepted = await self._wait_confirm(task_id, interrupt_payload)
            await task_store.update(task_id, status=task_store.STATUS_RUNNING)
            graph_input = Command(resume={"accepted": accepted})

    async def _wait_confirm(self, task_id: str, payload: dict[str, Any]) -> bool:
        """后台任务的删除确认：推送事件并等待前端响应，超时按取消处理。"""
        from backend.storage.config_store import get_config

        confirm_id = str(payload.get("confirm_id") or uuid.uuid4().hex)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[confirm_id] = future

        action = str(payload.get("action") or payload.get("tool_name") or "")
        event_type = (
            "delete_confirm" if action in ("file_delete", "delete_file") else "human_confirm"
        )
        await self._broadcast(
            {
                "type": event_type,
                "task_id": task_id,
                "confirm_id": confirm_id,
                "action": action,
                "tool_name": payload.get("tool_name", ""),
                "preview_text": payload.get("preview_text", ""),
                "params": payload.get("params", {}),
                "path": (payload.get("params") or {}).get("path", ""),
            }
        )
        await self._broadcast(
            {
                "type": "task_log",
                "task_id": task_id,
                "log": "等待人工确认删除操作…",
            }
        )

        config = await get_config()
        timeout = int(config.get("confirm_timeout_seconds") or 180)
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=max(5, timeout))
        except asyncio.TimeoutError:
            self._pending.pop(confirm_id, None)
            await self._broadcast(
                {
                    "type": "task_log",
                    "task_id": task_id,
                    "log": f"确认超时（{timeout} 秒），已按取消处理",
                }
            )
            return False

    async def _flush(self, task_id: str, buffer: list[str]) -> None:
        if not buffer:
            return
        text = "".join(buffer).strip()
        buffer.clear()
        if text:
            await self._broadcast({"type": "task_log", "task_id": task_id, "log": text})


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return ""


# 进程级单例：供工具层（start_background_task）在运行时取用，避免 tools 反向 import server
_RUNTIME: Optional["TaskRuntime"] = None


def set_runtime(runtime: Optional["TaskRuntime"]) -> None:
    global _RUNTIME
    _RUNTIME = runtime


def get_runtime() -> Optional["TaskRuntime"]:
    return _RUNTIME
