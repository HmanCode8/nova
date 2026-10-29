"""上传文件配套工具：只允许访问当前会话的临时目录。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from langchain_core.tools import tool

from backend.storage import file_extract, file_store
from backend.storage.memory_store import CURRENT_SESSION

MAX_READ_CHARS = 12000
MAX_FILE_CHARS = 8000


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("疑似二进制文件，无法按文本读取")
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(替换非法字节)"


@tool
async def list_uploaded_files() -> str:
    """列出当前会话已上传的文件（文件名、file_id、类型、大小、上传时间）。"""
    session_id = CURRENT_SESSION.get()
    if not session_id:
        return "当前没有会话上下文，无法列出上传文件。"
    items = await file_store.list_meta(session_id)
    if not items:
        return "当前会话还没有上传文件。"
    lines = [f"【已上传文件】共 {len(items)} 个"]
    for item in items:
        path = Path(item["stored_path"])
        size = path.stat().st_size if path.is_file() else 0
        kind = file_extract.KIND_LABELS.get(file_extract.classify(item["filename"]), "文件")
        lines.append(
            f"- {item['filename']}（{kind}，{size} 字节，file_id: {item['file_id']}，{item['created_at']}）"
        )
    return "\n".join(lines)


@tool
async def read_uploaded_file(file_id: str, max_chars: int = MAX_READ_CHARS) -> str:
    """读取当前会话已上传文件的内容（文本/代码直接读，图片走本地 OCR）。

    参数:
        file_id: 上传文件返回的 file_id
        max_chars: 单次最多返回的字符数，默认 12000
    """
    session_id = CURRENT_SESSION.get()
    if not session_id:
        return "读取失败：当前没有会话上下文。"
    meta = await file_store.get_meta(file_id, session_id)
    if not meta:
        return "读取失败：文件不存在，或不属于当前会话。"
    path = Path(meta["stored_path"])
    if not path.is_file():
        return f"读取失败：临时文件已被清理（{meta['filename']}）。"
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 20:
        return f"读取失败：文件超过 20MB 上限（{size_mb:.1f}MB）。"

    limit = max(200, min(int(max_chars), MAX_READ_CHARS))
    kind = file_extract.classify(meta["filename"])

    if kind == "image":
        try:
            extracted = await asyncio.to_thread(file_extract.extract, path, meta["filename"])
        except Exception as exc:
            return f"读取失败：图片 OCR 异常（{exc}）"
        text = str(extracted.get("text") or "").strip()
        if not text:
            return f"图片未识别到文字：{meta['filename']}"
        truncated = len(text) > limit
        header = (
            f"【上传图片】{meta['filename']}\n【file_id】{file_id}\n"
            f"【OCR】{extracted.get('note') or '本地识别'}\n【字符数】{len(text)}"
        )
        if truncated:
            header += f"\n【提示】内容已截断，仅返回前 {limit} 字符"
        return f"{header}\n---\n{text[:limit]}"

    if kind == "other":
        return (
            f"读取失败：暂不支持解析 {path.suffix or '该'} 格式。"
            "请转成 txt/md/代码文件，或截图后作为图片上传。"
        )

    try:
        text, encoding = _read_text(path)
    except (ValueError, OSError) as exc:
        return f"读取失败：{exc}"

    truncated = len(text) > limit
    body = text[:limit]
    header = (
        f"【上传文件】{meta['filename']}\n【file_id】{file_id}\n"
        f"【编码】{encoding}\n【大小】{len(text)} 字符"
    )
    if truncated:
        header += f"\n【提示】内容已截断，仅返回前 {limit} 字符"
    return f"{header}\n---\n{body}"
