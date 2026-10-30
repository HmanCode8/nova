"""FastAPI 服务 + WebSocket 事件网关（127.0.0.1 本地服务）。

网关职责（09-runtime-middleware-spec.md）：
- 事件协议转换：user_message / confirm_result / control / voice  →  Agent 图 / 语音链路
- 流式推送：token、tool_status、human_confirm、message、error、card
- 语音推送：voice_status、voice_level、asr_result、tts_status
- 人工确认超时（默认 180s）自动取消，避免 Agent 卡死
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    Body,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from backend.agent.agent_graph import build_agent, extract_interrupt, thread_config
from backend.agent import model_profiles
from backend.agent.llm_adapter import LLMConfigError, build_chat_model, has_api_key, local_http_client
from backend.agent import memory_extractor
from backend.agent import context_compress
from backend.logging_setup import setup_logging
from backend.mcp_client.client import close_client as close_mcp_client
from backend.mcp_manager import catalog as mcp_catalog
from backend.mcp_manager import get_manager as get_mcp_manager
from backend.runtime import TaskRuntime
from backend.runtime.task_runtime import set_runtime as _set_runtime
from backend.storage import (
    file_extract,
    file_store,
    memory_store,
    project_store,
    session_store,
    task_store,
    trace_store,
)
from backend.storage.config_store import get_config, save_config
from backend.storage.db import APP_DATA_DIR, DB_PATH, db
from backend.tools import get_agent_tools
from backend.tools.tool_hook import is_executable_path
from backend.voice import asr as voice_asr
from backend.voice import tts as voice_tts

try:  # 日志初始化失败不能影响服务启动
    setup_logging()
except Exception:
    pass

logger = logging.getLogger("nova.server")

DEFAULT_CONFIRM_TIMEOUT = 180


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.init_db()
    logger.info("后端启动，数据库：%s", DB_PATH)
    try:
        await file_store.cleanup_old_files(days=7)
    except Exception:
        pass  # 清理失败不影响启动
    try:
        # 上次进程遗留的 pending/running 任务标记为中断，避免状态永远卡住
        stale = await task_store.mark_interrupted_tasks()
        if stale:
            logger.warning("启动清理：%d 个遗留后台任务已标记中断", stale)
    except Exception:
        pass
    get_task_runtime()
    # MCP 商店：后台激活已启用的服务（npx 首次拉包较慢，不阻塞启动）
    asyncio.create_task(get_mcp_manager().activate_all())
    # 语音模型后台预热：不阻塞启动，失败只影响语音功能
    asyncio.create_task(asyncio.to_thread(voice_asr.warmup))
    asyncio.create_task(asyncio.to_thread(voice_tts.warmup))
    yield
    try:
        await get_task_runtime().shutdown()
    except Exception:
        pass
    try:
        await get_mcp_manager().close()
    except Exception:
        pass
    await close_mcp_client()
    await db.close()


app = FastAPI(title="NovaSecretary Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 仅本地 127.0.0.1 服务，前端为 Vite / Electron
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Agent 图单例（含 InMemorySaver checkpointer，跨轮保留会话线程状态）
# ---------------------------------------------------------------------------

_graph: Optional[Any] = None
_graph_lock = asyncio.Lock()


async def get_agent_graph():
    """懒加载 Agent 图；模型配置变更后调用 reset_agent_graph() 重建。"""
    global _graph
    if _graph is not None:
        return _graph
    async with _graph_lock:
        if _graph is None:
            model = await build_chat_model(streaming=True)
            _graph = build_agent(model, tools=await get_agent_tools())
    return _graph


def reset_agent_graph() -> None:
    global _graph
    _graph = None


# ---------------------------------------------------------------------------
# 连接注册表 + 广播（后台任务日志需要推给所有打开的窗口）
# ---------------------------------------------------------------------------

_connections: "set[Any]" = set()
_task_runtime: Optional[TaskRuntime] = None


async def broadcast(payload: dict[str, Any]) -> None:
    """把事件推给所有在线窗口（后台任务没有单一归属连接）。"""
    for connection in list(_connections):
        try:
            await connection.send(payload)
        except Exception:
            _connections.discard(connection)


def get_task_runtime() -> TaskRuntime:
    global _task_runtime
    if _task_runtime is None:
        _task_runtime = TaskRuntime(get_agent_graph, broadcast)
        _set_runtime(_task_runtime)  # 供 start_background_task 工具取用
    return _task_runtime


# ---------------------------------------------------------------------------
# HTTP 接口
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, Any]:
    profile = await model_profiles.get_active_profile()
    return {
        "status": "ok",
        "db_path": str(DB_PATH),
        "model_configured": bool(profile and profile.get("has_key")) or has_api_key(),
        "vl_key_configured": bool((os.getenv("VL_API_KEY") or "").strip()),
    }


@app.post("/api/admin/shutdown")
async def api_admin_shutdown(request: Request) -> dict[str, Any]:
    """托管模式优雅退出：仅允许本机回环地址调用（Electron 退出前触发）。"""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="仅允许本机调用")
    from backend import server_runtime

    if not server_runtime.request_shutdown():
        raise HTTPException(status_code=409, detail="当前非托管模式，请直接结束后端进程")
    logger.info("收到托管退出请求，后端准备优雅关闭")
    return {"ok": True}


@app.get("/api/sessions")
async def api_list_sessions() -> dict[str, Any]:
    return {"sessions": await session_store.list_sessions()}


@app.post("/api/sessions")
async def api_create_session(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    title = str(payload.get("title") or "新会话")
    return await session_store.create_session(title)


@app.patch("/api/sessions/{session_id}")
async def api_rename_session(session_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not await session_store.update_session_title(session_id, title):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str) -> dict[str, Any]:
    if not await session_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    context_compress.clear_cache(session_id)
    try:
        await project_store.delete_session_plans(session_id)
    except Exception:
        pass
    try:
        await file_store.delete_session_files(session_id)
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/sessions/{session_id}/messages")
async def api_list_messages(session_id: str) -> dict[str, Any]:
    if await session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"messages": await session_store.list_messages(session_id)}


@app.get("/api/sessions/{session_id}/project")
async def api_get_project(session_id: str) -> dict[str, Any]:
    """当前会话最近一次项目计划（刷新页面 / 切会话后恢复看板）。"""
    if await session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"project": await project_store.get_latest_plan(session_id)}


@app.get("/api/config")
async def api_get_config() -> dict[str, Any]:
    return await get_config()


@app.get("/api/traces")
async def api_list_traces(
    session_id: str = "", task_id: str = "", search: str = "", limit: int = 200
) -> dict[str, Any]:
    """轨迹查询（FINAL_DEVELOPMENT_DOC 第三章）：按会话/任务/关键词过滤。"""
    items = await trace_store.query(
        session_id=session_id, task_id=task_id, search=search, limit=limit
    )
    return {"traces": items}


@app.delete("/api/traces")
async def api_clear_traces(session_id: str = "") -> dict[str, Any]:
    await trace_store.clear(session_id)
    return {"ok": True}


@app.get("/api/tasks")
async def api_list_tasks(session_id: str = "", limit: int = 50) -> dict[str, Any]:
    """后台任务列表（FINAL_DEVELOPMENT_DOC 第四章 Runtime 接口）。"""
    return {"tasks": await task_store.list_tasks(session_id=session_id, limit=limit)}


@app.post("/api/tasks")
async def api_create_task(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "")
    prompt = str(payload.get("prompt") or "").strip()
    title = str(payload.get("title") or "").strip()
    if await session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        task = await get_task_runtime().submit(session_id, prompt, title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task": task}


@app.post("/api/tasks/{task_id}/stop")
async def api_stop_task(task_id: str) -> dict[str, Any]:
    if not await get_task_runtime().stop(task_id):
        raise HTTPException(status_code=404, detail="任务不存在或已结束")
    return {"ok": True}


@app.get("/api/mcp/catalog")
async def api_mcp_catalog() -> dict[str, Any]:
    """MCP 商店目录（卡片画廊 / 分类 / 搜索的静态数据源）。"""
    return mcp_catalog.list_catalog()


@app.get("/api/mcp/servers")
async def api_mcp_servers() -> dict[str, Any]:
    return {"servers": await get_mcp_manager().list_servers()}


@app.post("/api/mcp/servers")
async def api_mcp_install(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """安装 / 更新 MCP 服务并立即激活（工具随即注册进 Agent）。"""
    try:
        normalized = mcp_catalog.resolve_install(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = await get_mcp_manager().install(normalized)
    reset_agent_graph()  # 工具集变化，重建图
    servers = await get_mcp_manager().list_servers()
    current = next((item for item in servers if item["id"] == record["id"]), record)
    return {"server": current}


@app.post("/api/mcp/servers/{server_id}/toggle")
async def api_mcp_toggle(server_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    if not await get_mcp_manager().set_enabled(server_id, enabled):
        raise HTTPException(status_code=404, detail="MCP 服务不存在")
    reset_agent_graph()
    servers = await get_mcp_manager().list_servers()
    return {"servers": servers}


@app.delete("/api/mcp/servers/{server_id}")
async def api_mcp_uninstall(server_id: str) -> dict[str, Any]:
    if not await get_mcp_manager().uninstall(server_id):
        raise HTTPException(status_code=404, detail="MCP 服务不存在")
    reset_agent_graph()
    return {"servers": await get_mcp_manager().list_servers()}


@app.post("/api/mcp/import")
async def api_mcp_import(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """粘贴配置导入：兼容 mcpServers 写法，自动识别 stdio / streamable-http。"""
    from backend.mcp_manager import importer

    try:
        items = importer.parse(str(payload.get("json") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    imported: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for item in items:
        try:
            normalized = mcp_catalog.resolve_install(item)
            record = await get_mcp_manager().install(normalized)
            imported.append(
                {"id": record.get("id"), "name": record.get("name"), "transport": record.get("transport")}
            )
        except Exception as exc:  # 单条失败不影响其它条目
            failed.append({"name": str(item.get("name") or ""), "error": str(exc)[:200]})

    if imported:
        reset_agent_graph()
    servers = await get_mcp_manager().list_servers()
    return {"imported": imported, "failed": failed, "servers": servers}


@app.post("/api/mcp/servers/{server_id}/test")
async def api_mcp_test(server_id: str) -> dict[str, Any]:
    """测试连接并返回工具清单。"""
    try:
        return await get_mcp_manager().discover(server_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


RADAR_KEYWORDS = ("email_list", "rss", "news", "feed", "list_today", "article")
RADAR_LIST_KEYS = ("emails", "items", "articles", "entries", "data", "list", "results")


def _radar_items(raw: str, source: str, limit: int) -> list[dict[str, str]]:
    """把 MCP 返回的原始数据归一化成资讯条目（只做字段映射，不做任何解析加工）。"""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        text = (raw or "").strip()
        return (
            [{"title": text[:80], "summary": text[:240], "source": source, "time": ""}]
            if text
            else []
        )
    if isinstance(payload, dict):
        entries: Any = []
        for key in RADAR_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                entries = value
                break
    elif isinstance(payload, list):
        entries = payload
    else:
        entries = []

    items: list[dict[str, str]] = []
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            continue
        title = str(
            entry.get("title") or entry.get("subject") or entry.get("name") or entry.get("id") or ""
        ).strip()
        if not title:
            continue
        summary = str(
            entry.get("summary") or entry.get("snippet") or entry.get("content") or entry.get("description") or ""
        ).strip()
        when = str(entry.get("time") or entry.get("date") or entry.get("published") or "")
        items.append(
            {
                "title": title[:120],
                "summary": summary[:240],
                "source": source,
                "time": when[:32],
            }
        )
    return items


@app.get("/api/radar")
async def api_radar(limit: int = 12) -> dict[str, Any]:
    """资讯雷达数据源：调用已安装 MCP 里的资讯类工具，原样取回条目。

    FINAL_DEVELOPMENT_DOC 第三章：左栏数据源来自 MCP；这里只做字段归一化，
    不做解析加工（附件解析仍交给内置工具）。
    """
    manager = get_mcp_manager()
    tools = await manager.build_tools()
    sources: list[dict[str, Any]] = []
    items: list[dict[str, str]] = []

    for tool in tools:
        name = getattr(tool, "name", "") or ""
        if not any(key in name.lower() for key in RADAR_KEYWORDS):
            continue
        entry = {"name": name, "ok": False, "message": "", "count": 0}
        try:
            raw = await tool.ainvoke({})
            parsed = _radar_items(str(raw), name, max(1, min(limit, 30)))
            items.extend(parsed)
            entry.update(ok=True, count=len(parsed), message=f"{len(parsed)} 条")
        except Exception as exc:  # 需要参数 / 未连接：如实标记，不影响其它源
            entry["message"] = str(exc)[:160]
        sources.append(entry)

    if not sources:
        servers = await manager.list_servers()
        for server in servers:
            sources.append(
                {
                    "name": server.get("name") or server.get("id"),
                    "ok": False,
                    "message": "该服务未提供资讯类工具",
                    "count": 0,
                }
            )
    return {"items": items[: max(1, min(limit, 60))], "sources": sources}


@app.post("/upload")
async def api_upload(
    session_id: str = Form(...), file: UploadFile = File(...)
) -> dict[str, Any]:
    """上传文件到会话隔离临时目录，返回 file_id（消息里只保留引用）。"""
    if await session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    config = await get_config()
    max_mb = int(config.get("max_file_size_mb") or 10)
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件超过 {max_mb}MB 上限")
    record = await file_store.save_upload(session_id, file.filename or "file", data)
    meta = await file_store.get_meta(record["file_id"], session_id)
    extracted: dict[str, Any] = {}
    if meta:
        try:
            extracted = await asyncio.to_thread(
                file_extract.extract, Path(meta["stored_path"]), meta["filename"]
            )
        except Exception as exc:
            extracted = {"kind": "other", "text": "", "note": f"解析失败：{exc}"}
    return {
        **record,
        "kind": extracted.get("kind") or file_extract.classify(record["filename"]),
        "ext": Path(record["filename"]).suffix.lower(),
        "preview": file_extract.preview_of(extracted),
        "chars": int(extracted.get("chars") or 0),
        "note": str(extracted.get("note") or ""),
    }


@app.get("/api/sessions/{session_id}/files/{file_id}")
async def api_get_file(session_id: str, file_id: str) -> FileResponse:
    """读取会话内上传文件（用于图片预览，仅本地服务）。"""
    meta = await file_store.get_meta(file_id, session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(meta["stored_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件已被清理")
    return FileResponse(path)


@app.post("/api/sessions/{session_id}/files/{file_id}/open")
async def api_open_file(session_id: str, file_id: str) -> dict[str, Any]:
    """用系统默认程序打开会话内上传文件（仅限该会话、禁止可执行后缀）。"""
    meta = await file_store.get_meta(file_id, session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(meta["stored_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件已被清理")
    if is_executable_path(path):
        raise HTTPException(status_code=400, detail="安全限制：禁止打开可执行文件")

    def _open() -> None:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - 已在白名单目录内校验
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    await asyncio.to_thread(_open)
    return {"ok": True}


@app.get("/api/generated/{name}")
async def api_generated_image(name: str) -> FileResponse:
    """返回 generate_image 生成的图片（只允许 generated 目录内的单层文件名）。"""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=404, detail="图片不存在")
    root = (APP_DATA_DIR / "generated").resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


def _normalize_config_patch(payload: dict[str, Any]) -> dict[str, Any]:
    """配置校验与归一化：拒绝非法值，密钥字段直接丢弃（绝不入库）。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="配置格式不正确")

    cleaned = {key: value for key, value in payload.items() if key != "api_key"}

    model = cleaned.get("model")
    if model is not None:
        if not isinstance(model, dict):
            raise HTTPException(status_code=400, detail="model 配置必须是对象")
        model = {key: value for key, value in model.items() if key != "api_key"}
        if "temperature" in model:
            try:
                model["temperature"] = float(model["temperature"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="temperature 必须是数字") from None
            if not 0 <= model["temperature"] <= 2:
                raise HTTPException(status_code=400, detail="temperature 需在 0 ~ 2 之间")
        if "base_url" in model:
            base_url = str(model["base_url"] or "").strip()
            if base_url and not base_url.startswith(("http://", "https://")):
                raise HTTPException(
                    status_code=400, detail="base_url 必须以 http:// 或 https:// 开头"
                )
            model["base_url"] = base_url
        if "model_name" in model:
            model["model_name"] = str(model["model_name"] or "").strip()
        if "max_tokens" in model:
            try:
                max_tokens = int(model["max_tokens"] or 0)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="max_tokens 必须是整数") from None
            if not 0 <= max_tokens <= 32000:
                raise HTTPException(status_code=400, detail="max_tokens 需在 0 ~ 32000 之间")
            model["max_tokens"] = max_tokens
        if "top_p" in model:
            try:
                top_p = float(model["top_p"] or 0)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="top_p 必须是数字") from None
            if not 0 <= top_p <= 1:
                raise HTTPException(status_code=400, detail="top_p 需在 0 ~ 1 之间")
            model["top_p"] = top_p
        if "reasoning_effort" in model:
            effort = str(model["reasoning_effort"] or "").strip().lower()
            if effort not in ("", "minimal", "low", "medium", "high", "max"):
                raise HTTPException(
                    status_code=400,
                    detail="reasoning_effort 只能是 minimal / low / medium / high / max 或留空",
                )
            model["reasoning_effort"] = effort
        if "thinking_enabled" in model:
            model["thinking_enabled"] = bool(model["thinking_enabled"])
        if "thinking_budget" in model:
            try:
                budget = int(model["thinking_budget"] or 0)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="思考预算必须是整数") from None
            if not 0 <= budget <= 32000:
                raise HTTPException(status_code=400, detail="思考预算需在 0 ~ 32000 之间")
            model["thinking_budget"] = budget
        if "extra_body" in model:
            body = model["extra_body"]
            if isinstance(body, str):
                text = body.strip()
                if not text:
                    body = {}
                else:
                    try:
                        body = json.loads(text)
                    except (TypeError, ValueError):
                        raise HTTPException(
                            status_code=400, detail="额外请求参数必须是合法的 JSON 对象"
                        ) from None
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="额外请求参数必须是 JSON 对象")
            model["extra_body"] = body
        cleaned["model"] = model

    if "max_file_size_mb" in cleaned:
        try:
            size = int(cleaned["max_file_size_mb"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="单文件大小上限必须是整数") from None
        if not 1 <= size <= 100:
            raise HTTPException(status_code=400, detail="单文件大小上限需在 1 ~ 100MB 之间")
        cleaned["max_file_size_mb"] = size

    if "confirm_timeout_seconds" in cleaned:
        try:
            timeout = int(cleaned["confirm_timeout_seconds"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="确认超时必须是整数秒") from None
        if not 5 <= timeout <= 600:
            raise HTTPException(status_code=400, detail="确认超时需在 5 ~ 600 秒之间")
        cleaned["confirm_timeout_seconds"] = timeout

    if "max_context_tokens" in cleaned:
        try:
            max_tokens = int(cleaned["max_context_tokens"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="上下文 token 上限必须是整数") from None
        if not 1000 <= max_tokens <= 32000:
            raise HTTPException(
                status_code=400, detail="上下文 token 上限需在 1000 ~ 32000 之间"
            )
        cleaned["max_context_tokens"] = max_tokens

    if "vl_base_url" in cleaned:
        vl_base_url = str(cleaned["vl_base_url"] or "").strip()
        if vl_base_url and not vl_base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400, detail="视觉模型地址必须以 http:// 或 https:// 开头"
            )
        cleaned["vl_base_url"] = vl_base_url
    if "vl_model_name" in cleaned:
        cleaned["vl_model_name"] = str(cleaned["vl_model_name"] or "").strip()

    if "vision_source" in cleaned:
        source = str(cleaned["vision_source"] or "main").strip().lower()
        if source not in ("main", "separate"):
            raise HTTPException(
                status_code=400, detail="vision_source 只能是 main 或 separate"
            )
        cleaned["vision_source"] = source

    if "image_gen_base_url" in cleaned:
        image_base = str(cleaned["image_gen_base_url"] or "").strip()
        if image_base and not image_base.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400, detail="文生图服务地址必须以 http:// 或 https:// 开头"
            )
        cleaned["image_gen_base_url"] = image_base
    if "image_gen_model" in cleaned:
        cleaned["image_gen_model"] = str(cleaned["image_gen_model"] or "").strip()
    if "image_gen_size" in cleaned:
        image_size = str(cleaned["image_gen_size"] or "").strip().lower()
        if image_size and not re.fullmatch(r"\d{2,5}x\d{2,5}", image_size):
            raise HTTPException(
                status_code=400, detail="文生图尺寸格式应为 宽x高，例如 1024x1024"
            )
        cleaned["image_gen_size"] = image_size or "1024x1024"

    if "allowed_dirs" in cleaned:
        dirs = cleaned["allowed_dirs"]
        if not isinstance(dirs, list):
            raise HTTPException(status_code=400, detail="目录白名单必须是数组")
        normalized: list[str] = []
        for item in dirs:
            path = Path(str(item)).expanduser()
            if not path.is_absolute():
                raise HTTPException(status_code=400, detail=f"目录必须是绝对路径：{item}")
            if not path.is_dir():
                raise HTTPException(status_code=400, detail=f"目录不存在：{item}")
            resolved = str(path.resolve())
            if resolved not in normalized:
                normalized.append(resolved)
        cleaned["allowed_dirs"] = normalized

    for key in (
        "autonomy_mode",
        "shell_enabled",
        "web_search_enabled",
        "auto_memory_enabled",
        "tts_enabled",
        "vl_enabled",
        "vl_require_confirm",
        "image_gen_enabled",
    ):
        if key in cleaned:
            cleaned[key] = bool(cleaned[key])

    return cleaned


@app.put("/api/config")
async def api_save_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    merged = await save_config(_normalize_config_patch(payload))
    reset_agent_graph()  # 模型参数可能变化，下一轮重建
    return merged


# ---------------------------------------------------------------------------
# 模型档案：多套模型一键切换（密钥只写 .env，前端拿不到明文）
# ---------------------------------------------------------------------------

@app.get("/api/models")
async def api_list_models() -> dict[str, Any]:
    return await model_profiles.list_profiles()


@app.post("/api/models")
async def api_upsert_model(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        result = await model_profiles.upsert_profile(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reset_agent_graph()
    return result


@app.post("/api/models/{profile_id}/activate")
async def api_activate_model(profile_id: str) -> dict[str, Any]:
    try:
        result = await model_profiles.activate_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    reset_agent_graph()
    return result


@app.put("/api/models/{profile_id}/key")
async def api_set_model_key(
    profile_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    try:
        result = await model_profiles.set_profile_key(profile_id, str(payload.get("api_key") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reset_agent_graph()
    return result


@app.delete("/api/models/{profile_id}")
async def api_delete_model(profile_id: str) -> dict[str, Any]:
    try:
        result = await model_profiles.delete_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reset_agent_graph()
    return result


@app.post("/api/models/test")
async def api_test_model(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """连通性测试：发一句最短请求，返回耗时；不在响应里泄露密钥。

    同时回报该档案声明的能力是否配置完整（不触发真实生图，避免产生费用）。
    """
    profile_id = str(payload.get("id") or "").strip()
    data = await model_profiles.list_profiles()
    target = next(
        (p for p in data["profiles"] if p["id"] == (profile_id or data["active_id"])), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail="模型档案不存在")

    image_info = _image_capability_info(target)
    if not target.get("has_key"):
        return {"ok": False, "message": f"未配置密钥（{target['api_key_env']}）", "image": image_info}
    if not target.get("base_url") or not target.get("model_name"):
        return {"ok": False, "message": "Base URL 或模型名称未填写", "image": image_info}

    started = time.monotonic()
    base_url = target["base_url"]
    http_client = local_http_client(base_url)
    try:
        model = ChatOpenAI(
            model=target["model_name"],
            base_url=base_url,
            api_key=os.getenv(target["api_key_env"]) or os.getenv("LLM_API_KEY") or "ollama",
            temperature=0,
            max_retries=0,
            timeout=20,
            streaming=False,
            **({"http_async_client": http_client} if http_client else {}),
        )
        await asyncio.wait_for(model.ainvoke("只回复 ok"), timeout=25)
    except Exception as exc:  # 网络 / 鉴权 / 模型不存在都统一回报
        return {"ok": False, "message": f"连接失败：{exc}", "image": image_info}
    return {
        "ok": True,
        "message": "连接正常",
        "latency_ms": int((time.monotonic() - started) * 1000),
        "image": image_info,
    }


def _image_capability_info(profile: dict[str, Any]) -> dict[str, Any]:
    """生图能力的本地校验结果（不发起真实请求）。"""
    capabilities = profile.get("capabilities") or []
    if "image" not in capabilities:
        return {"enabled": False, "ready": False, "message": "未声明可生成图片"}
    image = profile.get("image") or {}
    provider = "百炼原生" if image.get("provider") == "dashscope" else "OpenAI 兼容"
    model = image.get("model") or profile.get("model_name") or ""
    base_url = image.get("base_url") or profile.get("base_url") or ""
    if not model or not base_url:
        return {"enabled": True, "ready": False, "message": "生图模型或服务地址未填写", "provider": provider}
    if not profile.get("has_key"):
        return {"enabled": True, "ready": False, "message": "缺少密钥", "provider": provider, "model": model}
    return {
        "enabled": True,
        "ready": True,
        "provider": provider,
        "model": model,
        "message": f"生图已就绪（{provider} / {model}）",
    }


# ---------------------------------------------------------------------------
# 记忆管理接口
# ---------------------------------------------------------------------------

def _check_scope(scope: str) -> None:
    if scope not in ("session", "global"):
        raise HTTPException(status_code=400, detail="scope 必须是 session 或 global")


@app.get("/api/memory")
async def api_list_memory(session_id: str = "") -> dict[str, Any]:
    global_items = await memory_store.list_memories("global")
    session_items = await memory_store.list_memories("session", session_id) if session_id else []
    return {"global": global_items, "session": session_items}


@app.post("/api/memory")
async def api_add_memory(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    scope = str(payload.get("scope") or "")
    _check_scope(scope)
    session_id = str(payload.get("session_id") or "")
    if scope == "session" and not session_id:
        raise HTTPException(status_code=400, detail="写入会话记忆需要 session_id")
    record = await memory_store.add_memory(scope, str(payload.get("text") or ""), session_id)
    if record is None:
        raise HTTPException(status_code=400, detail="未写入：内容为空、重复，或已达条数上限")
    return record


@app.patch("/api/memory/{scope}/{memory_id}")
async def api_update_memory(
    scope: str, memory_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    _check_scope(scope)
    if not await memory_store.update_memory(scope, memory_id, str(payload.get("text") or "")):
        raise HTTPException(status_code=404, detail="记忆不存在或内容为空")
    return {"ok": True}


@app.delete("/api/memory/{scope}/{memory_id}")
async def api_delete_memory(scope: str, memory_id: str) -> dict[str, Any]:
    _check_scope(scope)
    if not await memory_store.delete_memory(scope, memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


@app.delete("/api/memory")
async def api_clear_memory(scope: str, session_id: str = "") -> dict[str, Any]:
    _check_scope(scope)
    if scope == "session" and not session_id:
        raise HTTPException(status_code=400, detail="清空会话记忆需要 session_id")
    return {"deleted": await memory_store.clear_memories(scope, session_id)}


# ---------------------------------------------------------------------------
# WebSocket 事件网关
# ---------------------------------------------------------------------------

SESSION_LOCKS: dict[str, asyncio.Lock] = {}


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        SESSION_LOCKS[session_id] = lock
    return lock


def _chunk_reasoning(chunk: Any) -> str:
    """提取流式 chunk 里的思考内容（各家字段名不同，缺失时返回空串）。"""
    extra = getattr(chunk, "additional_kwargs", None) or {}
    if not isinstance(extra, dict):
        return ""
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = extra.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested = value.get("content") or value.get("text")
            if isinstance(nested, str) and nested:
                return nested
    return ""


def _chunk_text(chunk: Any) -> str:
    """从流式 chunk 提取文本（兼容 str 与多模态 block 列表）。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _extract_search_items(content: str, limit: int = 5) -> tuple[str, list[dict[str, str]]]:
    """从 tavily_web_search 的结构化 JSON 结果中提取查询词与卡片数据。"""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return "", []
    if not isinstance(data, dict):
        return "", []
    query = str(data.get("query") or "")
    results = data.get("results")
    if not isinstance(results, list):
        return query, []
    items: list[dict[str, str]] = []
    for entry in results[:limit]:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "title": str(entry.get("title") or "")[:160],
                "url": str(entry.get("url") or ""),
                "content": str(entry.get("content") or "")[:260],
            }
        )
    return query, items


def _extract_session_created(content: str) -> dict[str, str]:
    """解析 create_new_session 工具返回 JSON，用于推送 session_created 事件。"""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    session_id = str(data.get("session_id") or "")
    if not session_id:
        return {}
    return {"session_id": session_id, "title": str(data.get("title") or "新会话")}


CARD_TOOL_KINDS: dict[str, str] = {
    "email_list_today": "emails",
    "email_read_detail": "email_detail",
    "calendar_list_today": "calendar",
    "email_send": "email_sent",
    "calendar_create": "calendar_created",
    "plan_project": "project_plan",
    "update_project_step": "project_plan",
    "generate_image": "image_result",
    "show_image": "image_result",
}


def _extract_card(tool_name: str, content: str) -> Optional[dict[str, Any]]:
    """把 MCP 工具的结构化 JSON 结果转成前端卡片事件。"""
    kind = CARD_TOOL_KINDS.get(tool_name)
    if not kind:
        return None
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {"kind": kind, "data": data}


class ChatConnection:
    """一条 WebSocket 连接 = 一个前端聊天窗口。"""

    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self._send_lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._pending: Optional[dict[str, Any]] = None
        self._timer: Optional[asyncio.Task] = None
        self._level_task: Optional[asyncio.Task] = None
        self._speak_task: Optional[asyncio.Task] = None
        self._voice_busy = False
        self._speak_next = False
        self.closed = False

    async def send(self, payload: dict[str, Any]) -> None:
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self.ws.send_json(payload)
            except Exception:
                self.closed = True

    async def close(self) -> None:
        self.closed = True
        for task in (self._task, self._timer, self._level_task, self._speak_task):
            if task and not task.done():
                task.cancel()
        recorder = voice_asr.get_recorder()
        if recorder.recording:
            await asyncio.to_thread(recorder.stop)

    async def handle(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type == "user_message":
            await self._on_user_message(message)
        elif msg_type == "confirm_result":
            await self._on_confirm_result(message)
        elif msg_type == "control":
            await self._on_control(message)
        elif msg_type == "task_create":
            await self._on_task_create(message)
        elif msg_type == "voice":
            await self._on_voice(message)
        else:
            await self.send({"type": "error", "message": f"未知事件类型：{msg_type}"})

    # -- 入站事件 ---------------------------------------------------------

    async def _on_user_message(self, message: dict[str, Any]) -> None:
        session_id = str(message.get("session_id") or "")
        text = str(message.get("message") or "").strip()
        if self._task and not self._task.done():
            await self.send({"type": "error", "message": "上一条消息仍在处理中，请等待完成"})
            return
        if await session_store.get_session(session_id) is None:
            await self.send({"type": "error", "message": "会话不存在，请先新建会话"})
            return
        attachments, attachment_block = await self._prepare_attachments(
            session_id, message.get("attachments")
        )
        if not text and not attachments:
            await self.send({"type": "error", "message": "消息内容为空"})
            return
        # 语音发起的对话在回复完成后自动播报
        self._speak_next = str(message.get("source") or "") == "voice"
        self._task = asyncio.create_task(
            self._run_turn(session_id, text, attachments, attachment_block)
        )

    async def _on_confirm_result(self, message: dict[str, Any]) -> None:
        confirm_id = str(message.get("confirm_id") or "")
        accepted = bool(message.get("accepted"))
        if not self._pending or self._pending["confirm_id"] != confirm_id:
            # 不属于当前连接的交互式对话，尝试路由到后台任务
            if await get_task_runtime().resolve_confirm(confirm_id, accepted):
                return
            await self.send({"type": "error", "message": "确认已失效或不存在"})
            return
        if self._task and not self._task.done():
            return
        pending = self._pending
        self._pending = None
        self._cancel_timer()
        self._task = asyncio.create_task(self._resume_turn(pending, accepted))

    async def _on_control(self, message: dict[str, Any]) -> None:
        action = message.get("action")
        task_id = str(message.get("task_id") or "")
        # 带 task_id 的控制指令作用于后台任务（FINAL_DEVELOPMENT_DOC 第十一章）
        if task_id and action in ("stop", "cancel", "stop_task"):
            stopped = await get_task_runtime().stop(task_id)
            await self.send(
                {
                    "type": "task_status",
                    "task_id": task_id,
                    "status": "cancelled" if stopped else "unknown",
                }
            )
            return
        # stop_task 是 FINAL_DEVELOPMENT_DOC 第十一章的协议名，stop/cancel 为历史别名
        if action in ("stop", "cancel", "stop_task"):
            if self._task and not self._task.done():
                self._task.cancel()
            self._speak_next = False
            if self._speak_task and not self._speak_task.done():
                self._speak_task.cancel()
            if self._pending:
                pending = self._pending
                self._pending = None
                self._cancel_timer()
                asyncio.create_task(self._abort_pending(pending))
            await self.send({"type": "error", "message": "已停止当前生成"})

    # -- 语音链路（按住说话 → ASR；回复完成 → TTS） -------------------------

    async def _on_task_create(self, message: dict[str, Any]) -> None:
        """新建后台长任务：立即返回 task_id，执行过程通过广播推送 task_log。"""
        session_id = str(message.get("session_id") or "")
        prompt = str(message.get("prompt") or "").strip()
        title = str(message.get("title") or "").strip()
        if await session_store.get_session(session_id) is None:
            await self.send({"type": "error", "message": "会话不存在，请先新建会话"})
            return
        try:
            task = await get_task_runtime().submit(session_id, prompt, title)
        except ValueError as exc:
            await self.send({"type": "error", "message": str(exc)})
            return
        await self.send(
            {
                "type": "task_created",
                "task_id": task["id"],
                "session_id": session_id,
                "title": task.get("title", ""),
            }
        )

    async def _on_voice(self, message: dict[str, Any]) -> None:
        action = str(message.get("action") or "")
        if action == "start":
            await self._start_voice()
        elif action == "stop":
            await self._finish_voice()
        else:
            await self.send({"type": "error", "message": f"未知语音指令：{action}"})

    async def _start_voice(self) -> None:
        recorder = voice_asr.get_recorder()
        if recorder.recording:
            await self.send({"type": "voice_status", "status": "recording"})
            return
        if self._voice_busy:
            await self.send({"type": "error", "message": "正在识别上一段语音，请稍候"})
            return
        try:
            await asyncio.to_thread(recorder.start)
        except RuntimeError as exc:
            await self.send({"type": "voice_status", "status": "idle"})
            await self.send({"type": "error", "message": str(exc)})
            return
        await self.send({"type": "voice_status", "status": "recording"})
        self._level_task = asyncio.create_task(self._push_levels())

    async def _push_levels(self) -> None:
        """录音期间推送音量包络，供前端实时波形展示。"""
        recorder = voice_asr.get_recorder()
        try:
            while recorder.recording and not recorder.limit_reached:
                await self.send({"type": "voice_level", "level": round(recorder.level, 3)})
                await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            raise
        finally:
            self._level_task = None
        # 达到录音上限：主动收尾并转写
        if recorder.limit_reached:
            await self._finish_voice()

    async def _finish_voice(self) -> None:
        if self._voice_busy:
            return
        recorder = voice_asr.get_recorder()
        if not recorder.recording:
            await self.send({"type": "voice_status", "status": "idle"})
            return
        self._voice_busy = True
        task = self._level_task
        self._level_task = None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
        try:
            audio = await asyncio.to_thread(recorder.stop)
            await self.send({"type": "voice_status", "status": "transcribing"})
            try:
                text = await voice_asr.transcribe(audio)
            except Exception as exc:  # 模型缺失 / 下载失败
                await self.send({"type": "voice_status", "status": "idle"})
                await self.send({"type": "error", "message": f"语音识别失败：{exc}"})
                return
            if not text:
                await self.send({"type": "voice_status", "status": "idle"})
                await self.send({"type": "error", "message": "没有识别到语音内容，请再试一次"})
                return
            await self.send({"type": "asr_result", "text": text})
            await self.send({"type": "voice_status", "status": "idle"})
        finally:
            self._voice_busy = False

    async def _speak(self, text: str) -> None:
        """本地 TTS 播报（不阻塞本轮消息收尾）。"""
        config = await get_config()
        if not config.get("tts_enabled", True):
            return
        await self.send({"type": "tts_status", "status": "speaking"})
        try:
            engine = await asyncio.to_thread(voice_tts.speak_blocking, text)
            await self.send({"type": "tts_status", "status": "idle", "engine": engine})
        except Exception as exc:
            await self.send({"type": "tts_status", "status": "failed", "message": str(exc)})

    # -- 出站流程 ---------------------------------------------------------

    async def _prepare_attachments(
        self, session_id: str, raw: Any
    ) -> tuple[list[dict[str, Any]], str]:
        """校验附件归属、解析内容，返回（精简元信息, 本轮注入的附件上下文）。"""
        attachments: list[dict[str, Any]] = []
        blocks: list[str] = []
        entries = raw if isinstance(raw, list) else []
        for entry in entries[:5]:
            file_id = str((entry or {}).get("file_id") or "") if isinstance(entry, dict) else ""
            if not file_id:
                continue
            meta = await file_store.get_meta(file_id, session_id)
            if not meta:
                continue
            path = Path(meta["stored_path"])
            if not path.is_file():
                continue
            try:
                extracted = await asyncio.to_thread(
                    file_extract.extract, path, meta["filename"]
                )
            except Exception:
                extracted = {"kind": "other", "text": "", "note": "解析失败"}
            size = path.stat().st_size
            attachments.append(
                {
                    "file_id": file_id,
                    "filename": meta["filename"],
                    "size": size,
                    "kind": extracted.get("kind") or "other",
                }
            )
            if extracted.get("kind") == "image":
                # 图片不注入 OCR 文本，避免模型绕过 image_vl / ocr_image 自行作答
                blocks.append(
                    f"【附件】{meta['filename']}（图片，{size} 字节）\n"
                    f"【file_id】{file_id}\n"
                    "【提示】图片内容未自动转文字：提取文字请调用 ocr_image，"
                    "理解画面/UI/流程图请调用 image_vl。"
                )
            else:
                blocks.append(
                    file_extract.context_block(
                        meta["filename"], size, extracted, file_id=file_id
                    )
                )
        block = "\n\n".join(blocks)
        return attachments, block[:12000]

    async def _run_turn(
        self,
        session_id: str,
        text: str,
        attachments: Optional[list[dict[str, Any]]] = None,
        attachment_block: str = "",
    ) -> None:
        lock = _session_lock(session_id)
        async with lock:
            attachments = attachments or []
            persisted = text
            if not persisted and attachments:
                names = "、".join(item["filename"] for item in attachments)
                persisted = f"（已附带文件：{names}）"
            await session_store.add_message(
                session_id, "user", persisted, attachments=attachments or None
            )
            await session_store.maybe_auto_title(session_id, persisted)
            rows = await session_store.get_llm_history(session_id)
            config = await get_config()
            messages, summary = await self._prepare_context(session_id, rows, config)
            if attachment_block:
                turn_content = f"{text}\n\n{attachment_block}".strip() if text else attachment_block
                if messages and isinstance(messages[-1], HumanMessage):
                    messages[-1] = HumanMessage(content=turn_content)
                else:
                    messages.append(HumanMessage(content=turn_content))
            if not messages:
                messages = [HumanMessage(content=text or "（已附带文件）")]
            thread_id = f"{session_id}#{uuid.uuid4().hex[:8]}"
            token = memory_store.CURRENT_SESSION.set(session_id)
            try:
                await self._stream(
                    {
                        "messages": messages,
                        "session_id": session_id,
                        "history_summary": summary,
                    },
                    thread_id,
                    session_id,
                )
            finally:
                memory_store.CURRENT_SESSION.reset(token)

    async def _prepare_context(
        self, session_id: str, rows: list[dict[str, Any]], config: dict[str, Any]
    ) -> tuple[list[Any], str]:
        """按 token 上限决定是否压缩历史；失败时回退为完整历史。"""
        try:
            return await context_compress.prepare_history(
                session_id, rows, config.get("max_context_tokens")
            )
        except Exception:
            return context_compress.rows_to_messages(rows), ""

    async def _resume_turn(self, pending: dict[str, Any], accepted: bool) -> None:
        lock = _session_lock(pending["session_id"])
        async with lock:
            token = memory_store.CURRENT_SESSION.set(pending["session_id"])
            try:
                await self._stream(
                    Command(resume={"accepted": accepted}),
                    pending["thread_id"],
                    pending["session_id"],
                )
            finally:
                memory_store.CURRENT_SESSION.reset(token)

    async def _abort_pending(self, pending: dict[str, Any]) -> None:
        """控制指令取消待确认操作：以拒绝方式恢复，让 Agent 收尾，不产生副作用。"""
        await self._resume_turn(pending, False)

    async def _stream(self, graph_input: Any, thread_id: str, session_id: str) -> None:
        try:
            graph = await get_agent_graph()
        except LLMConfigError as exc:
            await self.send({"type": "error", "message": str(exc)})
            return

        config = thread_config(thread_id)
        text_parts: list[str] = []
        reason_parts: list[str] = []
        interrupt_payload: Optional[dict[str, Any]] = None

        try:
            async for mode, data in graph.astream(
                graph_input, config=config, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, metadata = data
                    # finalize 是循环熔断后的收尾节点，它的输出同样要流式推给前端
                    if metadata.get("langgraph_node") in ("agent", "finalize"):
                        reasoning = _chunk_reasoning(chunk)
                        if reasoning:
                            reason_parts.append(reasoning)
                            await self.send({"type": "reasoning", "delta": reasoning})
                        delta = _chunk_text(chunk)
                        if delta:
                            text_parts.append(delta)
                            await self.send({"type": "token", "delta": delta})
                    continue

                if not isinstance(data, dict):
                    continue
                if "__interrupt__" in data:
                    interrupt_payload = extract_interrupt(data)
                    continue
                if "agent" in data:
                    for msg in data["agent"].get("messages", []):
                        for call in getattr(msg, "tool_calls", None) or []:
                            await self.send(
                                {
                                    "type": "tool_status",
                                    "tool_name": call.get("name", ""),
                                    "status": "running",
                                }
                            )
                if "tools" in data:
                    for msg in data["tools"].get("messages", []):
                        tool_name = getattr(msg, "name", "") or ""
                        await self.send(
                            {
                                "type": "tool_status",
                                "tool_name": tool_name,
                                "status": "done",
                            }
                        )
                        if tool_name in ("tavily_web_search", "tavily_search"):
                            query, items = _extract_search_items(str(getattr(msg, "content", "")))
                            if items:
                                await self.send(
                                    {"type": "search_results", "query": query, "items": items}
                                )
                        if tool_name == "create_new_session":
                            created = _extract_session_created(str(getattr(msg, "content", "")))
                            if created:
                                await self.send({"type": "session_created", **created})
                        card = _extract_card(tool_name, str(getattr(msg, "content", "")))
                        if card:
                            await self.send({"type": "card", **card})
                        await session_store.add_message(
                            session_id,
                            "tool",
                            tool_name=getattr(msg, "name", None),
                            tool_result=str(getattr(msg, "content", "")),
                        )
        except asyncio.CancelledError:
            raise
        except GraphRecursionError:
            # 兜底：熔断没拦住时也不要把原始异常甩给用户，带上已产出的内容优雅收尾
            self._speak_next = False
            logger.warning("Agent 触发递归上限：session=%s", session_id)
            notice = (
                "本轮工具调用次数过多，已自动停止以免陷入死循环。"
                "如果任务还没做完，请把需求拆小一点（例如先只做第一项）再试。"
            )
            partial = "".join(text_parts).strip()
            content = f"{partial}\n\n{notice}" if partial else notice
            await session_store.add_message(session_id, "assistant", content)
            await session_store.touch_session(session_id)
            await self.send(
                {"type": "message", "role": "assistant", "content": content, "session_id": session_id}
            )
            return
        except Exception as exc:  # 兜底：任何异常都要回前端，避免前端无限转圈
            self._speak_next = False
            logger.exception("Agent 执行失败：session=%s", session_id)
            await self.send({"type": "error", "message": f"Agent 执行失败：{exc}"})
            return

        if interrupt_payload:
            confirm_id = str(interrupt_payload.get("confirm_id") or uuid.uuid4().hex)
            self._pending = {
                "confirm_id": confirm_id,
                "thread_id": thread_id,
                "session_id": session_id,
            }
            action = str(interrupt_payload.get("action") or interrupt_payload.get("tool_name") or "")
            # 协议对齐（FINAL_DEVELOPMENT_DOC 第十一章）：删除用 delete_confirm 事件，
            # 其它副作用工具沿用 human_confirm；两者字段一致，前端同一套弹窗处理。
            event_type = (
                "delete_confirm" if action in ("file_delete", "delete_file") else "human_confirm"
            )
            await self.send(
                {
                    "type": event_type,
                    "confirm_id": confirm_id,
                    "action": action,
                    "tool_name": interrupt_payload.get("tool_name", ""),
                    "preview_text": interrupt_payload.get("preview_text", ""),
                    "params": interrupt_payload.get("params", {}),
                    "path": (interrupt_payload.get("params") or {}).get("path", ""),
                }
            )
            self._start_timeout(confirm_id)
            return

        final_text = "".join(text_parts).strip()
        final_reasoning = "".join(reason_parts).strip()
        if final_text:
            await session_store.add_message(
                session_id, "assistant", final_text, reasoning=final_reasoning or None
            )
            await session_store.touch_session(session_id)
            await self.send(
                {"type": "message", "role": "assistant", "content": final_text, "session_id": session_id}
            )
            # 语音发起的对话：回复后自动本地播报（后台任务，不阻塞收尾）
            if self._speak_next:
                self._speak_next = False
                self._speak_task = asyncio.create_task(self._speak(final_text))
            # 后台自动记忆抽取，不阻塞本轮响应
            asyncio.create_task(self._maybe_extract_memory(session_id, final_text))

    async def _maybe_extract_memory(self, session_id: str, assistant_text: str) -> None:
        """自动记忆开关打开时，由 LLM 提炼值得长期记住的信息。"""
        try:
            config = await get_config()
            if not config.get("auto_memory_enabled"):
                return
            model = await build_chat_model(streaming=False)
            await memory_extractor.extract_and_store(session_id, assistant_text, model)
        except Exception:
            return

    # -- 确认超时 ---------------------------------------------------------

    def _start_timeout(self, confirm_id: str) -> None:
        async def waiter() -> None:
            config = await get_config()
            seconds = int(config.get("confirm_timeout_seconds") or DEFAULT_CONFIRM_TIMEOUT)
            await asyncio.sleep(max(1, seconds))
            if self._pending and self._pending["confirm_id"] == confirm_id:
                pending = self._pending
                self._pending = None
                await self.send(
                    {
                        "type": "error",
                        "message": f"人工确认超时（{seconds} 秒未响应），已自动取消本次操作",
                    }
                )
                await self._resume_turn(pending, False)

        self._cancel_timer()
        self._timer = asyncio.create_task(waiter())

    def _cancel_timer(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()
        self._timer = None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    connection = ChatConnection(websocket)
    _connections.add(connection)  # 后台任务日志需要广播到所有窗口
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                await connection.handle(message)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _connections.discard(connection)
        await connection.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )
