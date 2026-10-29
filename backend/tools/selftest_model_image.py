r"""模型参数注入 + 文生图工具自测。

覆盖：
1. build_model_kwargs：思考参数合并、用户 extra_body 优先、非法值丢弃
2. generate_image：未启用 / 缺模型名 / 桩接口 b64_json 落盘
3. 生成文件确实写到应用数据目录 generated/，且返回可展示 URL

运行（PowerShell）：
    $env:NOVA_DB_PATH = "$env:TEMP\ns_imggen\nova.db"
    $env:NOVA_TEMP_DIR = "$env:TEMP\ns_imggen\temp"
    $env:PYTHONPATH = "e:\nova-secretary"
    uv run --project backend python -m backend.tools.selftest_model_image
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend.agent.model_params import build_model_kwargs
from backend.storage.config_store import save_config
from backend.storage.db import db
from backend.tools.image_gen_tool import generate_image, generated_dir

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _StubImageHandler(BaseHTTPRequestHandler):
    paths: list[str] = []

    def do_POST(self) -> None:  # noqa: N802
        type(self).paths.append(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if not body.get("prompt"):
            self.send_error(400, "missing prompt")
            return
        payload = {
            "created": 0,
            "data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}],
        }
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:  # noqa: ANN002
        return


def _check_model_params(errors: list[str]) -> None:
    # 1. 思考开关 + 预算合并进 extra_body
    kwargs = build_model_kwargs(
        {"thinking_enabled": True, "thinking_budget": 1024, "max_tokens": 2048, "top_p": 0.8}
    )
    print("1) 参数注入：", kwargs)
    if kwargs.get("extra_body") != {"enable_thinking": True, "thinking_budget": 1024}:
        errors.append("思考参数没有正确合并到 extra_body")
    if kwargs.get("max_tokens") != 2048 or kwargs.get("top_p") != 0.8:
        errors.append("max_tokens / top_p 注入错误")

    # 2. 用户显式 extra_body 优先，不被开关覆盖
    kwargs = build_model_kwargs(
        {"thinking_enabled": True, "extra_body": {"enable_thinking": False, "custom": 1}}
    )
    print("2) 用户优先：", kwargs.get("extra_body"))
    if kwargs["extra_body"].get("enable_thinking") is not False or kwargs["extra_body"].get("custom") != 1:
        errors.append("用户 extra_body 没有保持优先")

    # 3. 非法值静默丢弃，避免把坏参数发给模型
    kwargs = build_model_kwargs({"top_p": 3, "max_tokens": -1, "reasoning_effort": "ultra"})
    print("3) 非法值丢弃：", kwargs)
    if kwargs:
        errors.append("非法参数没有被丢弃")


async def main() -> int:
    if not os.environ.get("NOVA_DB_PATH") or not os.environ.get("NOVA_TEMP_DIR"):
        print("拒绝执行：请设置 NOVA_DB_PATH 与 NOVA_TEMP_DIR 指向隔离目录。")
        return 2

    errors: list[str] = []
    _check_model_params(errors)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubImageHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["IMAGE_API_KEY"] = "test-key"

    await db.init_db()
    created: list[Path] = []
    try:
        # 4. 未启用
        await save_config({"image_gen_enabled": False})
        disabled = await generate_image.ainvoke({"prompt": "一只猫"})
        print("4) 未启用：", disabled)
        if "未启用" not in disabled:
            errors.append("未启用时没有返回友好提示")

        # 5. 启用但缺模型名
        await save_config(
            {
                "image_gen_enabled": True,
                "image_gen_base_url": f"http://127.0.0.1:{port}/v1",
                "image_gen_model": "",
            }
        )
        missing = await generate_image.ainvoke({"prompt": "一只猫"})
        print("5) 缺模型名：", missing)
        if "模型名称为空" not in missing:
            errors.append("缺模型名时提示不正确")

        # 6. 桩接口出图
        await save_config(
            {
                "image_gen_enabled": True,
                "image_gen_base_url": f"http://127.0.0.1:{port}/v1",
                "image_gen_model": "stub-image",
                "image_gen_size": "512x512",
            }
        )
        raw = await generate_image.ainvoke({"prompt": "一只赛博朋克风格的猫", "count": 1})
        print("6) 生成结果：", raw[:160])
        try:
            result = json.loads(raw)
        except (TypeError, ValueError):
            result = {}
            errors.append("generate_image 没有返回 JSON")
        images = result.get("images") or []
        if not images:
            errors.append("generate_image 没有返回图片记录")
        else:
            path = Path(images[0]["path"])
            created.append(path)
            if not path.is_file() or path.stat().st_size == 0:
                errors.append("生成图片没有落盘")
            if path.parent.resolve() != generated_dir().resolve():
                errors.append("生成图片没有写入 generated 目录")
            if not images[0]["url"].startswith("/api/generated/"):
                errors.append("返回的展示地址格式不正确")
        if not _StubImageHandler.paths or "/v1/images/generations" not in _StubImageHandler.paths[0]:
            errors.append("请求路径不是 /v1/images/generations")
    finally:
        server.shutdown()
        for path in created:
            path.unlink(missing_ok=True)
        await db.close()

    if errors:
        print("\n❌ 自测失败：")
        for item in errors:
            print(" -", item)
        return 1
    print("\n✅ 模型参数 + 文生图自测通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
