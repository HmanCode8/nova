"""截图与本地 OCR 工具。

- take_screenshot：截取当前屏幕（Windows 全部显示器），保存到应用数据目录 screenshots/
- ocr_image：使用 RapidOCR（本地 ONNX 推理，不上传云端）识别图片文字
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from langchain_core.tools import tool
from PIL import ImageGrab

from backend.storage.db import APP_DATA_DIR
from backend.tools.image_source import resolve_image
from backend.tools.tool_hook import ToolValidationError

SCREENSHOT_DIR = APP_DATA_DIR / "screenshots"
MAX_OCR_CHARS = 8000

_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    """RapidOCR 首次加载约 1~2 秒，进程内复用单例。"""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
    return _engine


def run_ocr_sync(path: str | Path) -> list[str]:
    """同步 OCR（供工具与上传解析共用），返回逐行文本。"""
    engine = _get_engine()
    with _engine_lock:  # ONNX 会话非线程安全，推理串行执行
        result, _ = engine(str(path))
    lines: list[str] = []
    for item in result or []:
        if len(item) > 1 and item[1]:
            lines.append(str(item[1]))
    return lines


def _capture_screen() -> tuple[Path, tuple[int, int]]:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    # Windows：all_screens=True 覆盖全部显示器；macOS 分支待后续阶段验证
    image = ImageGrab.grab(all_screens=True)
    path = SCREENSHOT_DIR / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"
    image.save(path, format="PNG")
    return path, image.size


@tool
async def take_screenshot() -> str:
    """截取当前屏幕并保存为本地 PNG（无副作用，仅本地文件）。

    返回截图绝对路径；需要识别截图中文字时，再调用 ocr_image 传入该路径。
    """
    try:
        path, size = await asyncio.to_thread(_capture_screen)
    except Exception as exc:
        return f"截图失败：{exc}"
    return f"截图已保存：{path}\n分辨率：{size[0]}x{size[1]}\n如需识别文字请调用 ocr_image。"


@tool
async def ocr_image(image_path: str) -> str:
    """对本地图片做文字识别（RapidOCR 本地推理，不上传云端）。

    参数:
        image_path: 上传图片的 file_id，或图片绝对路径
                   （截图目录 / 上传目录 / 授权目录内，支持 png/jpg/jpeg/bmp/webp）
    """
    try:
        path = await resolve_image(image_path)
    except ToolValidationError as exc:
        return f"OCR 失败：{exc}"

    def _run() -> list[str]:
        return run_ocr_sync(path)

    try:
        lines = await asyncio.to_thread(_run)
    except Exception as exc:
        return f"OCR 失败：{exc}"

    if not lines:
        return f"未识别到文字：{path}（图片可能不含文本或分辨率过低）"

    text = "\n".join(lines)
    truncated = len(text) > MAX_OCR_CHARS
    body = text[:MAX_OCR_CHARS]
    header = f"【OCR 结果】{path}\n【识别行数】{len(lines)}"
    if truncated:
        header += f"\n【提示】文字过多，仅返回前 {MAX_OCR_CHARS} 字符"
    return f"{header}\n---\n{body}"
