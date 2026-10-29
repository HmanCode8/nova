"""后端运行入口：开发态与 PyInstaller 打包态共用。

- 以对象方式启动 uvicorn（不走 "backend.server:app" 字符串导入），
  打包后动态导入会失败；同时把 Server 句柄交给 server_runtime，
  供 Electron 通过 /api/admin/shutdown 优雅退出。
- 开发态仍可用 `python -m backend.server` 启动。
"""

from __future__ import annotations

import os

import uvicorn

from backend import server_runtime
from backend.env_loader import load_env
from backend.server import app


def main() -> None:
    load_env()
    config = uvicorn.Config(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)
    server_runtime.set_server(server)
    try:
        server.run()
    finally:
        server_runtime.clear_server()


if __name__ == "__main__":
    main()
