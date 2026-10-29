"""文件类工具：read_file / write_file / list_dir / open_local_file。

所有路径先过 tool_hook 硬校验（目录白名单 + 可执行后缀黑名单）：
- 只读工具直接执行
- write_file / open_local_file 带副作用，由 agent_graph 的 gate 节点 interrupt 确认后才真正执行
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from backend.storage.config_store import get_config
from backend.tools.tool_hook import (
    ToolValidationError,
    ensure_openable_file,
    ensure_path_allowed,
    ensure_readable_file,
    ensure_writable_file,
)

MAX_READ_CHARS = 12000
MAX_DIR_ENTRIES = 200
BINARY_SNIFF_BYTES = 8192


def _read_text(path: Path) -> tuple[str, str]:
    """按 utf-8 → gbk 顺序尝试解码，最后兜底 utf-8 替换（兼容 Windows 中文文本）。"""
    raw = path.read_bytes()
    if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
        raise ToolValidationError(f"疑似二进制文件，已拒绝读取：{path}")
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(替换非法字节)"


@tool
async def read_file(file_path: str, max_chars: int = MAX_READ_CHARS) -> str:
    """读取授权目录内的文本/代码文件内容（只读，无副作用）。

    参数:
        file_path: 文件的绝对路径（必须位于用户授权的目录白名单内）
        max_chars: 单次最多返回的字符数，默认 12000
    """
    config = await get_config()
    max_size_mb = int(config.get("max_file_size_mb") or 10)
    try:
        path = await ensure_readable_file(file_path, max_size_mb=max_size_mb)
        text, encoding = _read_text(path)
    except ToolValidationError as exc:
        return f"读取失败：{exc}"
    except OSError as exc:
        return f"读取失败：{exc}"

    limit = max(200, min(int(max_chars), MAX_READ_CHARS))
    truncated = len(text) > limit
    body = text[:limit] if truncated else text
    lines = text.count("\n") + 1
    header = f"【文件】{path}\n【编码】{encoding}\n【大小】{lines} 行 / {len(text)} 字符"
    if truncated:
        header += f"\n【提示】内容已截断，仅返回前 {limit} 字符（需要更多请缩小范围或用 list_dir 定位）"
    return f"{header}\n---\n{body}"


@tool
async def write_file(file_path: str, content: str) -> str:
    """写入或覆盖授权目录内的文本文件（带人工确认，用户确认后才真正写入）。

    参数:
        file_path: 目标文件的绝对路径（必须位于授权目录内，父目录需已存在）
        content: 要写入的完整文本内容（覆盖原内容）
    """
    try:
        path = await ensure_writable_file(file_path)
    except ToolValidationError as exc:
        return f"写入失败：{exc}"
    try:
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        return f"写入失败：{exc}"
    return f"已写入文件：{path}（{len(content)} 字符）"


@tool
async def list_dir(dir_path: str, max_entries: int = MAX_DIR_ENTRIES) -> str:
    """列出授权目录下的文件与子目录（不递归，只读，无副作用）。

    参数:
        dir_path: 目录的绝对路径（必须位于授权目录内）
        max_entries: 最多返回的条目数，默认 200
    """
    try:
        path = await ensure_path_allowed(dir_path, must_exist=True)
        if not path.is_dir():
            raise ToolValidationError(f"不是目录：{path}")
        entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except ToolValidationError as exc:
        return f"列目录失败：{exc}"
    except OSError as exc:
        return f"列目录失败：{exc}"

    limit = max(10, min(int(max_entries), MAX_DIR_ENTRIES))
    lines = [f"【目录】{path}", f"【条目】{len(entries)} 个"]
    for item in entries[:limit]:
        try:
            if item.is_dir():
                lines.append(f"[DIR]  {item.name}")
            else:
                size_kb = item.stat().st_size / 1024
                lines.append(f"[FILE] {item.name}  ({size_kb:.1f} KB)")
        except OSError:
            lines.append(f"[?]    {item.name}")
    if len(entries) > limit:
        lines.append(f"...（仅显示前 {limit} 条，共 {len(entries)} 条）")
    return "\n".join(lines)


@tool
async def open_local_file(file_path: str) -> str:
    """用系统默认程序打开本地文档（带人工确认，用户确认后才执行；禁止可执行文件）。

    参数:
        file_path: 要打开的文件的绝对路径（必须位于授权目录内）
    """
    try:
        path = await ensure_openable_file(file_path)
    except ToolValidationError as exc:
        return f"打开失败：{exc}"

    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # Windows 专用；macOS 分支留待后续阶段验证
        else:
            subprocess.run(["open", str(path)], check=True)
    except OSError as exc:
        return f"打开失败：{exc}"
    return f"已调用系统默认程序打开：{path}"
