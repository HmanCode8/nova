"""统一工具钩子（tool_hook）。

- 副作用识别 + 人工确认载荷构造（write_file / open_local_file / email_send / calendar_create）
- 路径硬校验：目录白名单 + 可执行后缀黑名单（04-security / 06-agent-tools-list）
- 工具返回值截断摘要

所有工具调用的前置校验、确认识别都收口到这里，供 agent_graph 与各工具共用。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# 带副作用、必须人工确认的工具（04-security / 08-human-confirm）
SIDE_EFFECT_TOOLS: frozenset[str] = frozenset(
    {"write_file", "write_project_files", "open_local_file", "email_send", "calendar_create"}
)

# 项目模式批量写入上限：一批一次确认，避免单次 state 过大
MAX_BATCH_FILES = 10
MAX_BATCH_CHARS = 200_000

# 可执行/脚本后缀黑名单：只读不拦，写入与打开一律拦截
EXECUTABLE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".exe", ".bat", ".cmd", ".ps1", ".psm1", ".com", ".msi", ".scr",
        ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".lnk",
        ".reg", ".dll", ".jar", ".cpl", ".pif",
    }
)


class ToolValidationError(ValueError):
    """工具硬校验不通过：直接返回错误给 Agent，不弹人工确认。"""



async def needs_confirmation(tool_name: str) -> bool:
    """是否需要人工确认：固定副作用工具 + 可配置的视觉理解工具。"""
    if tool_name in SIDE_EFFECT_TOOLS:
        return True
    if tool_name == "image_vl":
        try:
            from backend.storage.config_store import get_config  # 延迟导入避免循环依赖

            config = await get_config()
            return bool(config.get("vl_require_confirm"))
        except Exception:
            return False
    return False


def new_confirm_id() -> str:
    return uuid.uuid4().hex


def _preview_for(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "write_file":
        path = args.get("file_path") or args.get("path") or "（未提供路径）"
        content = str(args.get("content", ""))
        return f"即将写入文件：{path}（{len(content)} 字符，将覆盖原内容）"
    if tool_name == "write_project_files":
        files = args.get("files") if isinstance(args.get("files"), list) else []
        entries = [item for item in files if isinstance(item, dict)]
        names = [str(item.get("path") or "（未命名）") for item in entries]
        total = sum(len(str(item.get("content") or "")) for item in entries)
        shown = "、".join(names[:8]) + (f" 等 {len(names)} 个" if len(names) > 8 else "")
        return (
            f"即将写入 {len(names)} 个文件到 {args.get('root_dir') or '（未提供目录）'}："
            f"{shown}（合计 {total} 字符，同名文件将被覆盖）"
        )
    if tool_name == "open_local_file":
        path = args.get("file_path") or args.get("path") or "（未提供路径）"
        return f"即将用系统默认程序打开文件：{path}"
    if tool_name == "email_send":
        return f"即将发送邮件：收件人 {args.get('to', '（未提供）')}，主题 {args.get('subject', '（无主题）')}"
    if tool_name == "calendar_create":
        return f"即将新建日程：{args.get('title', '（无标题）')}，时间 {args.get('start_time', '（未提供）')}"
    return f"即将执行高副作用操作：{tool_name}"


def build_confirm_payload(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """构造推送给前端的轻量确认事件（不携带大段正文）。"""
    params = _light_params(args)
    if tool_name == "write_project_files":
        # 批量文件正文不进确认载荷，只保留路径与字符数
        files = args.get("files") if isinstance(args.get("files"), list) else []
        params["files"] = [
            {
                "path": str(item.get("path") or ""),
                "chars": len(str(item.get("content") or "")),
            }
            for item in files
            if isinstance(item, dict)
        ]
    return {
        "event": "human_confirm",
        "confirm_id": new_confirm_id(),
        "action": tool_name,
        "tool_name": tool_name,
        "preview_text": _preview_for(tool_name, args),
        "params": params,
    }


def _light_params(args: dict[str, Any], max_chars: int = 300) -> dict[str, Any]:
    """确认载荷瘦身：content 等大字段只保留长度标记。"""
    light: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > max_chars:
            light[key] = f"[已省略 {len(value)} 字符]"
        else:
            light[key] = value
    return light


def summarize_tool_result(result: Any, max_chars: int = 12000) -> str:
    """工具返回值转字符串并截断，避免超长内容撑爆本轮 state。"""
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(result)
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...[结果已截断，原长 {len(text)} 字符]"
    return text


# ---------------------------------------------------------------------------
# 路径硬校验：目录白名单 + 后缀黑名单
# ---------------------------------------------------------------------------

def is_executable_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in EXECUTABLE_SUFFIXES


async def get_allowed_dirs() -> list[Path]:
    """读取设置面板配置的目录白名单（只保留存在且为绝对路径的目录）。"""
    from backend.storage.config_store import get_config  # 延迟导入避免循环依赖

    config = await get_config()
    allowed: list[Path] = []
    for item in config.get("allowed_dirs") or []:
        if not isinstance(item, str) or not item.strip():
            continue
        path = Path(item).expanduser()
        if path.is_absolute() and path.exists():
            allowed.append(path.resolve())
    return allowed


def _is_within(candidate: Path, root: Path) -> bool:
    """判断 candidate 是否位于 root 之内（Windows 大小写不敏感）。"""
    left = os.path.normcase(str(candidate))
    right = os.path.normcase(str(root))
    try:
        return os.path.commonpath([left, right]) == right
    except ValueError:  # 不同盘符
        return False


async def ensure_path_allowed(path_str: str, *, must_exist: bool = False) -> Path:
    """白名单校验：必须绝对路径，且落在配置的授权目录内。"""
    raw = (path_str or "").strip().strip('"')
    if not raw:
        raise ToolValidationError("路径为空，请提供文件的绝对路径。")

    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ToolValidationError(f"请使用绝对路径：{raw}")

    resolved = path.resolve(strict=False)
    allowed = await get_allowed_dirs()
    if not allowed:
        raise ToolValidationError(
            "目录白名单为空，暂时无法访问本地文件。请先在设置面板添加允许访问的目录。"
        )
    if not any(_is_within(resolved, root) for root in allowed):
        joined = "、".join(str(item) for item in allowed)
        raise ToolValidationError(
            f"路径不在授权目录内：{resolved}\n当前授权目录：{joined}"
        )

    if must_exist and not resolved.exists():
        raise ToolValidationError(f"路径不存在：{resolved}")
    return resolved


async def ensure_readable_file(path_str: str, max_size_mb: int = 10) -> Path:
    """只读工具校验：授权目录内的普通文件 + 大小上限。"""
    path = await ensure_path_allowed(path_str, must_exist=True)
    if not path.is_file():
        raise ToolValidationError(f"不是文件：{path}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ToolValidationError(
            f"文件超过 {max_size_mb}MB 上限（当前 {size_mb:.1f}MB）：{path}"
        )
    return path


async def ensure_writable_file(path_str: str) -> Path:
    """写入工具校验：授权目录内、非可执行后缀、父目录必须已存在。"""
    path = await ensure_path_allowed(path_str)
    if is_executable_path(path):
        raise ToolValidationError(f"安全限制：禁止写入可执行文件后缀 {path.suffix}：{path}")
    if not path.parent.exists():
        raise ToolValidationError(f"目标目录不存在，请先创建目录：{path.parent}")
    if path.exists() and path.is_dir():
        raise ToolValidationError(f"目标是目录，不能写入：{path}")
    return path


async def ensure_openable_file(path_str: str) -> Path:
    """打开工具校验：授权目录内、存在、且不在可执行后缀黑名单。"""
    path = await ensure_path_allowed(path_str, must_exist=True)
    if is_executable_path(path):
        raise ToolValidationError(f"安全限制：禁止打开可执行文件：{path}")
    if not path.is_file():
        raise ToolValidationError(f"不是文件：{path}")
    return path


async def ensure_project_batch(
    root_dir: str, files: Any
) -> tuple[Path, list[tuple[Path, str]]]:
    """项目模式批量写入校验：根目录在白名单内，文件必须落在根目录下。

    - 相对路径按 root_dir 拼接，自动建父目录交给调用方执行
    - 绝对路径也必须在 root_dir 内，防止借批量写绕过白名单
    - 复用可执行后缀黑名单 + 单批文件数/总字符上限
    """
    if not isinstance(files, list) or not files:
        raise ToolValidationError("files 不能为空，请提供 [{path, content}] 列表。")
    if len(files) > MAX_BATCH_FILES:
        raise ToolValidationError(
            f"单批最多 {MAX_BATCH_FILES} 个文件（当前 {len(files)} 个），请拆成多次写入。"
        )

    root = await ensure_path_allowed(root_dir)
    if root.is_file():
        raise ToolValidationError(f"项目根目录不能是文件：{root}")

    items: list[tuple[Path, str]] = []
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise ToolValidationError("files 每一项必须是 {path, content} 结构。")
        rel = str(entry.get("path") or entry.get("file_path") or "").strip()
        content = entry.get("content")
        if not rel:
            raise ToolValidationError("files 中存在空路径。")
        if not isinstance(content, str):
            raise ToolValidationError(f"文件内容必须是字符串：{rel}")

        candidate = Path(rel)
        target = candidate if candidate.is_absolute() else root / candidate
        resolved = await ensure_path_allowed(str(target))
        if not _is_within(resolved, root):
            raise ToolValidationError(f"文件必须位于项目根目录内：{resolved}")
        if is_executable_path(resolved):
            raise ToolValidationError(
                f"安全限制：禁止写入可执行文件后缀 {resolved.suffix}：{resolved}"
            )
        if resolved.exists() and resolved.is_dir():
            raise ToolValidationError(f"目标是目录，不能写入：{resolved}")
        total += len(content)
        items.append((resolved, content))

    if total > MAX_BATCH_CHARS:
        raise ToolValidationError(
            f"单批内容超过 {MAX_BATCH_CHARS} 字符上限（当前 {total}），请拆成多次写入。"
        )
    return root, items


IMAGE_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})


async def ensure_ocr_source(path_str: str, max_size_mb: int = 20) -> Path:
    """OCR 图片来源校验：允许截图目录（应用数据目录）或授权目录内的图片文件。"""
    from backend.storage.db import APP_DATA_DIR  # 延迟导入，避免循环依赖

    raw = (path_str or "").strip().strip('"')
    if not raw:
        raise ToolValidationError("图片路径为空，请提供截图的绝对路径。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ToolValidationError(f"请使用绝对路径：{raw}")

    resolved = path.resolve(strict=False)
    if not resolved.is_file():
        raise ToolValidationError(f"图片不存在：{resolved}")
    if resolved.suffix.lower() not in IMAGE_SUFFIXES:
        raise ToolValidationError(f"不支持的图片格式：{resolved.suffix}")

    screenshot_dir = (APP_DATA_DIR / "screenshots").resolve()
    from backend.storage.file_store import TEMP_ROOT  # 延迟导入避免循环依赖

    upload_root = TEMP_ROOT.resolve()
    allowed = await get_allowed_dirs()
    if not (
        _is_within(resolved, screenshot_dir)
        or _is_within(resolved, upload_root)
        or any(_is_within(resolved, d) for d in allowed)
    ):
        raise ToolValidationError(
            f"图片不在截图目录、上传目录或授权目录内：{resolved}\n请先在设置面板添加所在目录。"
        )

    size_mb = resolved.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ToolValidationError(f"图片超过 {max_size_mb}MB 上限（当前 {size_mb:.1f}MB）")
    return resolved


async def hard_validate(tool_name: str, args: dict[str, Any]) -> str | None:
    """副作用工具的前置硬校验（在弹确认之前执行）。

    返回错误文案表示直接拒绝且不弹确认；返回 None 表示可以进入确认流程。
    """
    try:
        if tool_name == "write_file":
            await ensure_writable_file(str(args.get("file_path") or ""))
        elif tool_name == "write_project_files":
            await ensure_project_batch(str(args.get("root_dir") or ""), args.get("files"))
        elif tool_name == "open_local_file":
            await ensure_openable_file(str(args.get("file_path") or ""))
        elif tool_name == "email_send":
            to = str(args.get("to") or "").strip()
            subject = str(args.get("subject") or "").strip()
            body = str(args.get("body") or "").strip()
            if "@" not in to:
                return "收件人邮箱不合法，请提供有效的邮箱地址。"
            if not subject:
                return "邮件主题不能为空。"
            if not body:
                return "邮件正文不能为空。"
        elif tool_name == "calendar_create":
            title = str(args.get("title") or "").strip()
            start_time = str(args.get("start_time") or "").strip()
            end_time = str(args.get("end_time") or "").strip()
            if not title:
                return "日程标题不能为空。"
            if not start_time:
                return "日程开始时间不能为空。"
            try:
                start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            except ValueError:
                return "开始时间格式需为 YYYY-MM-DD HH:MM。"
            if end_time:
                try:
                    end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
                except ValueError:
                    return "结束时间格式需为 YYYY-MM-DD HH:MM。"
                if end_dt <= start_dt:
                    return "结束时间必须晚于开始时间。"
    except ToolValidationError as exc:
        return str(exc)
    return None
