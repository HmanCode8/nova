r"""image_vl 工具自测：VL 开关、配置校验、本地桩模型调用、file_id 解析、确认开关。

运行（PowerShell）：
    $env:NOVA_DB_PATH = "$env:TEMP\ns_vl\nova.db"
    $env:NOVA_TEMP_DIR = "$env:TEMP\ns_vl\temp"
    $env:PYTHONPATH = "e:\nova-secretary"
    uv run --project backend python -m backend.tools.selftest_image_vl
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend.storage import file_store
from backend.storage.config_store import save_config
from backend.storage.db import db
from backend.storage.memory_store import CURRENT_SESSION
from backend.tools.image_vl import image_vl
from backend.tools.tool_hook import needs_confirmation

STUB_TEXT = "STUB-VL：左侧为导航栏，右侧为内容区，顶部有搜索框。"


class _StubVLHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        payload = {
            "id": "stub-1",
            "object": "chat.completion",
            "created": 0,
            "model": "stub-vl",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": STUB_TEXT},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # noqa: ANN002
        return


def _make_image(path: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 420), "#f5f7fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 720, 64], fill="#1f2a44")
    draw.rectangle([24, 96, 200, 380], fill="#dce6ff")
    draw.rectangle([232, 96, 690, 200], fill="#e8f0ff")
    draw.rectangle([232, 220, 690, 380], fill="#eef3ff")
    image.save(path)


async def main() -> int:
    if not os.environ.get("NOVA_DB_PATH") or not os.environ.get("NOVA_TEMP_DIR"):
        print("拒绝执行：请设置 NOVA_DB_PATH 与 NOVA_TEMP_DIR 指向隔离目录。")
        return 2

    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubVLHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["VL_API_KEY"] = "test-key"

    await db.init_db()
    errors: list[str] = []
    temp = Path(os.environ["NOVA_TEMP_DIR"])
    temp.mkdir(parents=True, exist_ok=True)
    image_path = temp / "ui_no_text.png"
    _make_image(image_path)

    try:
        # 1. 关闭 VL：友好提示，不触发模型调用
        await save_config({"vl_enabled": False})
        disabled = await image_vl.ainvoke({"image": str(image_path), "question": "描述界面"})
        print("1) VL 关闭：", disabled)
        if "已关闭视觉理解" not in disabled:
            errors.append("VL 关闭时没有返回友好提示")

        # 2. 独立 VL 模式但没配置地址/模型
        await save_config(
            {
                "vl_enabled": True,
                "vision_source": "separate",
                "vl_base_url": "",
                "vl_model_name": "",
            }
        )
        missing = await image_vl.ainvoke({"image": str(image_path)})
        print("2) 配置不全：", missing)
        if "未配置完整" not in missing:
            errors.append("缺少配置时提示不正确")

        # 3. 指向本地桩模型（独立 VL）
        await save_config(
            {
                "vl_enabled": True,
                "vision_source": "separate",
                "vl_base_url": f"http://127.0.0.1:{port}/v1",
                "vl_model_name": "stub-vl",
            }
        )
        result = await image_vl.ainvoke({"image": str(image_path), "question": "描述这个界面的布局"})
        print("3) 桩模型返回：", result[:80])
        if STUB_TEXT not in result:
            errors.append("VL 调用未返回桩模型内容")

        # 3b. 复用主模型：不再需要单独的 VL 地址与密钥
        os.environ["LLM_API_KEY"] = "test-key"
        await save_config(
            {
                "vl_enabled": True,
                "vision_source": "main",
                "model": {
                    "base_url": f"http://127.0.0.1:{port}/v1",
                    "model_name": "stub-main",
                },
            }
        )
        main_result = await image_vl.ainvoke(
            {"image": str(image_path), "question": "描述这个界面的布局"}
        )
        print("3b) 主模型复用：", main_result[:60])
        if STUB_TEXT not in main_result:
            errors.append("vision_source=main 时没有复用主模型")

        # 4. 用 file_id 调用（上传图片）
        from backend.storage import session_store

        session = await session_store.create_session("VL 自测")
        sid = session["id"]
        record = await file_store.save_upload(sid, "ui.png", image_path.read_bytes())
        token = CURRENT_SESSION.set(sid)
        try:
            by_id = await image_vl.ainvoke(
                {"image": record["file_id"], "question": "这是什么界面"}
            )
        finally:
            CURRENT_SESSION.reset(token)
        print("4) file_id 调用：", by_id[:60])
        if STUB_TEXT not in by_id:
            errors.append("file_id 方式调用失败")
        await session_store.delete_session(sid)

        # 5. 人工确认开关
        default_confirm = await needs_confirmation("image_vl")
        await save_config({"vl_require_confirm": True})
        enabled_confirm = await needs_confirmation("image_vl")
        await save_config({"vl_require_confirm": False})
        print(f"5) 确认开关：默认={default_confirm} 开启后={enabled_confirm}")
        if default_confirm or not enabled_confirm:
            errors.append("image_vl 确认开关不生效")
    finally:
        server.shutdown()
        await db.close()

    if errors:
        print("\n❌ 自测失败：")
        for item in errors:
            print(" -", item)
        return 1
    print("\n✅ image_vl 自测通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
