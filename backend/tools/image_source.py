"""图片引用解析：会话上传 file_id 或绝对路径 → 本地图片路径（含安全校验）。

OCR 与视觉理解工具共用，保证两条链路对图片的准入规则完全一致。
"""

from __future__ import annotations

from pathlib import Path

from backend.storage import file_store
from backend.storage.memory_store import CURRENT_SESSION
from backend.tools.tool_hook import ToolValidationError, ensure_ocr_source


async def resolve_image(image_ref: str) -> Path:
    """支持三种入参：上传 file_id、绝对路径、带引号的绝对路径。"""
    ref = (image_ref or "").strip().strip('"').strip("'")
    if not ref:
        raise ToolValidationError("图片引用为空：请传上传文件的 file_id 或图片绝对路径。")

    path = Path(ref).expanduser()
    if not path.is_absolute():
        session_id = CURRENT_SESSION.get()
        if not session_id:
            raise ToolValidationError("当前没有会话上下文，无法按 file_id 读取上传图片。")
        meta = await file_store.get_meta(ref, session_id)
        if not meta:
            raise ToolValidationError(f"未找到上传图片：{ref}（请确认 file_id 属于当前会话）")
        stored = Path(meta["stored_path"])
        if not stored.is_file():
            raise ToolValidationError(f"上传图片已被清理：{meta['filename']}")
        return await ensure_ocr_source(str(stored))

    return await ensure_ocr_source(str(path))
