"""本地语音模块：faster-whisper ASR + piper / 系统 TTS。

约束（04-security-and-safety.md）：
- 音频只在本机处理，默认不上传任何第三方云端
- 模型缓存在应用数据目录，不放进源码目录

NOVA_MODEL_DIR 仅用于开发/自测隔离模型目录，生产使用应用数据目录。
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.storage.db import APP_DATA_DIR


def models_dir() -> Path:
    root = Path(os.getenv("NOVA_MODEL_DIR") or (APP_DATA_DIR / "models"))
    root.mkdir(parents=True, exist_ok=True)
    return root

