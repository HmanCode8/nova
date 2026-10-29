"""M6 自测脚本：剪贴板 / 截图 / 本地 OCR / Tavily 联网搜索。

运行：
    cd e:\nova-secretary
    $env:PYTHONPATH = "e:\nova-secretary"
    uv run --project backend python -m backend.tools.selftest_misc_tools

注意：
- 会临时改写 app_config.allowed_dirs / web_search_enabled，结束时恢复
- 剪贴板测试会恢复原始剪贴板内容
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pyperclip
from PIL import Image, ImageDraw, ImageFont

from backend.storage.config_store import get_config, save_config
from backend.storage.db import db
from backend.tools import get_all_tools
from backend.tools.clipboard_tools import clipboard_read, clipboard_write
from backend.tools.screenshot_tools import ocr_image, take_screenshot
from backend.tools.tavily_search_tool import tavily_web_search

EXPECTED_TOOLS = {
    "read_file",
    "write_file",
    "list_dir",
    "open_local_file",
    "clipboard_read",
    "clipboard_write",
    "take_screenshot",
    "ocr_image",
    "tavily_web_search",
    "add_session_memory",
    "delete_session_memory",
    "add_global_memory",
    "delete_global_memory",
    "summarize_context",
    "create_new_session",
    "list_uploaded_files",
    "read_uploaded_file",
}


async def case_clipboard() -> None:
    original = ""
    try:
        original = pyperclip.paste()
    except Exception:
        original = ""
    try:
        written = await clipboard_write.ainvoke({"content": "NovaSecretary 剪贴板测试 2026"})
        assert "已写入剪贴板" in written, written
        read_back = await clipboard_read.ainvoke({})
        assert "NovaSecretary 剪贴板测试 2026" in read_back, read_back
        print("[PASS] 1. 剪贴板写入 + 读取")
    finally:
        try:
            pyperclip.copy(original)
        except Exception:
            pass


async def case_screenshot_and_ocr(workdir: Path, outside: Path) -> None:
    shot = await take_screenshot.ainvoke({})
    assert "截图已保存" in shot, shot
    path = Path(shot.split("截图已保存：", 1)[1].split("\n", 1)[0].strip())
    assert path.is_file() and path.stat().st_size > 0, shot
    print(f"[PASS] 2. 截图保存成功：{path}")

    image = Image.new("RGB", (720, 180), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 46)
    draw.text((24, 60), "NovaSecretary OCR 2026", font=font, fill="black")
    sample = workdir / "ocr-sample.png"
    image.save(sample)

    result = await ocr_image.ainvoke({"image_path": str(sample)})
    assert "OCR 结果" in result, result
    assert "NovaSecretary" in result or "OCR" in result, result
    print("[PASS] 3. 本地 OCR 识别测试图片")

    outside_image = outside / "secret.png"
    image.save(outside_image)
    blocked = await ocr_image.ainvoke({"image_path": str(outside_image)})
    assert "图片不在截图目录" in blocked, blocked
    print("[PASS] 4. 非授权目录图片被拒绝 OCR")


async def case_tavily() -> None:
    await save_config({"web_search_enabled": False})
    disabled = await tavily_web_search.ainvoke({"query": "test"})
    assert "已关闭" in disabled, disabled
    print("[PASS] 5. 联网开关关闭时拒绝调用")

    await save_config({"web_search_enabled": True})
    if not (os.getenv("TAVILY_API_KEY") or "").strip():
        print("[SKIP] 6. 未配置 TAVILY_API_KEY，跳过真实搜索")
        return
    raw = await tavily_web_search.ainvoke({"query": "Python 3.14 release notes", "max_results": 3})
    data = json.loads(raw)
    assert data["results"] and data["results"][0]["url"], raw[:300]
    print(f"[PASS] 6. Tavily 真实搜索返回 {len(data['results'])} 条结构化结果")


def case_registry() -> None:
    names = {tool.name for tool in get_all_tools()}
    assert names == EXPECTED_TOOLS, names ^ EXPECTED_TOOLS
    print(f"[PASS] 7. 工具注册表包含 {len(names)} 个工具")


async def main() -> None:
    case_registry()
    await db.init_db()
    original = await get_config()
    workdir = Path(tempfile.mkdtemp(prefix="ns_m6_allowed_"))
    outside = Path(tempfile.mkdtemp(prefix="ns_m6_outside_"))

    await save_config({"allowed_dirs": [str(workdir)], "web_search_enabled": True})
    try:
        await case_clipboard()
        await case_screenshot_and_ocr(workdir, outside)
        await case_tavily()
    finally:
        await save_config(
            {
                "allowed_dirs": list(original.get("allowed_dirs") or []),
                "web_search_enabled": bool(original.get("web_search_enabled", True)),
            }
        )
        await db.close()

    print("\nM6 全部自测通过")


if __name__ == "__main__":
    asyncio.run(main())
