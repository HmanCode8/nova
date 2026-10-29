"""托管模式运行时句柄。

Electron 主进程退出前调用 POST /api/admin/shutdown，本模块负责通知
uvicorn Server 优雅停止；开发态（`python -m backend.server`）没有句柄，
接口会返回提示，避免误杀别的进程。
"""

from __future__ import annotations

from typing import Any

_server: Any = None


def set_server(server: Any) -> None:
    global _server
    _server = server


def clear_server() -> None:
    global _server
    _server = None


def request_shutdown() -> bool:
    if _server is None:
        return False
    _server.should_exit = True
    return True
