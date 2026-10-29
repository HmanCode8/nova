"""统一日志：控制台 + 文件轮转（后端服务、MCP 子进程诊断统一落盘）。

日志位置：
- Windows: %APPDATA%/NovaSecretary/logs/backend.log
- macOS:   ~/Library/Application Support/NovaSecretary/logs/backend.log

只保留最近 3 个 5MB 文件，避免无限增长。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.storage.db import APP_DATA_DIR

LOG_DIR = APP_DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "backend.log"
_configured = False


def setup_logging(level: int = logging.INFO) -> Path:
    """初始化根日志（幂等）。返回日志目录。"""
    global _configured
    if _configured:
        return LOG_DIR
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    root = logging.getLogger()
    root.setLevel(level)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    _configured = True
    # 第三方 HTTP 客户端日志过于啰嗦，只保留告警
    for noisy in ("httpx", "httpx2", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("nova").info("日志已启用：%s", LOG_FILE)
    return LOG_DIR
