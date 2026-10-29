"""剪贴板工具：读取 / 写入系统剪贴板（pyperclip，Windows/macOS 通用）。"""

from __future__ import annotations

import asyncio

import pyperclip
from langchain_core.tools import tool

MAX_CLIPBOARD_CHARS = 8000


@tool
async def clipboard_read() -> str:
    """读取当前系统剪贴板中的文本内容（只读，无副作用）。"""
    try:
        text = await asyncio.to_thread(pyperclip.paste)
    except Exception as exc:
        return f"读取剪贴板失败：{exc}"
    if not text:
        return "剪贴板为空，或当前内容不是文本。"
    truncated = len(text) > MAX_CLIPBOARD_CHARS
    body = text[:MAX_CLIPBOARD_CHARS]
    header = f"【剪贴板文本】{len(text)} 字符"
    if truncated:
        header += f"，仅返回前 {MAX_CLIPBOARD_CHARS} 字符"
    return f"{header}\n---\n{body}"


@tool
async def clipboard_write(content: str) -> str:
    """把文本写入系统剪贴板（覆盖当前剪贴板内容）。

    参数:
        content: 要写入剪贴板的完整文本
    """
    if not content:
        return "写入失败：内容为空。"
    try:
        await asyncio.to_thread(pyperclip.copy, content)
    except Exception as exc:
        return f"写入剪贴板失败：{exc}"
    return f"已写入剪贴板（{len(content)} 字符）"
