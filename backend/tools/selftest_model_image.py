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
    polls: int = 0

    def _json(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _bytes(self, raw: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        type(self).paths.append(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")

        # 百炼原生：提交异步任务
        if self.path.endswith("/image-synthesis"):
            if not (body.get("input") or {}).get("prompt"):
                self.send_error(400, "missing prompt")
                return
            self._json({"output": {"task_id": "task-1", "task_status": "PENDING"}})
            return

        if not body.get("prompt"):
            self.send_error(400, "missing prompt")
            return
        self._json(
            {"created": 0, "data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}]}
        )

    def do_GET(self) -> None:  # noqa: N802
        type(self).paths.append(self.path)
        host = f"http://127.0.0.1:{self.server.server_address[1]}"
        # 百炼任务查询：第一次 PENDING，第二次 SUCCEEDED
        if self.path.startswith("/api/v1/tasks/"):
            type(self).polls += 1
            if type(self).polls == 1:
                self._json({"output": {"task_id": "task-1", "task_status": "RUNNING"}})
            else:
                self._json(
                    {
                        "output": {
                            "task_id": "task-1",
                            "task_status": "SUCCEEDED",
                            "results": [{"url": f"{host}/generated.png"}],
                        }
                    }
                )
            return
        if self.path == "/generated.png":
            self._bytes(PNG_BYTES, "image/png")
            return
        self.send_error(404, "not found")

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
        if "没有可用的生图模型" not in disabled:
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

        # 7. 能力路由：档案勾选「可生成图片」后优先于全局配置
        _StubImageHandler.paths.clear()
        await save_config(
            {
                "image_gen_enabled": True,
                "image_gen_base_url": f"http://127.0.0.1:{port}/v1",
                "image_gen_model": "stub-image",
                "image_gen_size": "512x512",
                "model_profiles": [
                    {
                        "id": "chat-only",
                        "name": "纯对话",
                        "base_url": f"http://127.0.0.1:{port}/v1",
                        "model_name": "chat-model",
                        "api_key_env": "IMAGE_API_KEY",
                        "capabilities": ["chat"],
                    },
                    {
                        "id": "img-openai",
                        "name": "带出图能力",
                        "base_url": f"http://127.0.0.1:{port}/v1",
                        "model_name": "chat-model",
                        "api_key_env": "IMAGE_API_KEY",
                        "capabilities": ["chat", "image"],
                        "image": {"provider": "openai", "model": "profile-image", "size": "768x768"},
                    },
                ],
                "active_model_id": "chat-only",
            }
        )
        routed = json.loads(await generate_image.ainvoke({"prompt": "一只猫"}))
        print("7) 能力路由：", {k: routed.get(k) for k in ("source", "model", "provider", "size")})
        if routed.get("source") != "带出图能力" or routed.get("model") != "profile-image":
            errors.append("没有按能力路由到声明了 image 的档案")
        if routed.get("size") != "768x768":
            errors.append("没有使用档案里的出图尺寸")

        # 8. 百炼原生异步链路：提交任务 → 轮询 → 下载落盘
        _StubImageHandler.paths.clear()
        _StubImageHandler.polls = 0
        await save_config(
            {
                "model_profiles": [
                    {
                        "id": "img-dashscope",
                        "name": "百炼出图",
                        "base_url": f"http://127.0.0.1:{port}/compatible-mode/v1",
                        "model_name": "qwen-plus",
                        "api_key_env": "IMAGE_API_KEY",
                        "capabilities": ["chat", "image"],
                        "image": {"provider": "dashscope", "model": "wanx2.1-t2i-turbo"},
                    }
                ],
                "active_model_id": "img-dashscope",
            }
        )
        dashscope = json.loads(await generate_image.ainvoke({"prompt": "一只猫"}))
        print("8) 百炼出图：", {k: dashscope.get(k) for k in ("source", "model", "provider")})
        if dashscope.get("provider") != "dashscope":
            errors.append("没有走百炼原生分支")
        if not any(path.endswith("/image-synthesis") for path in _StubImageHandler.paths):
            errors.append("没有调用百炼任务提交接口")
        if not any(path.startswith("/api/v1/tasks/") for path in _StubImageHandler.paths):
            errors.append("没有轮询百炼任务状态")
        if not dashscope.get("images"):
            errors.append("百炼出图没有落盘")
        else:
            created.append(Path(dashscope["images"][0]["path"]))
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
