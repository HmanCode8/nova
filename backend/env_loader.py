"""统一 .env 加载：开发态读 backend/.env，打包态读用户数据目录。

打包后 backend/.env 不在安装目录（密钥绝不能打进安装包），Electron 通过
NOVA_ENV_FILE 指向 %APPDATA%/NovaSecretary/.env；未注入时按候选顺序回退。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_loaded: Path | None = None


def env_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = (os.getenv("NOVA_ENV_FILE") or "").strip()
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(__file__).resolve().parent / ".env")  # backend/.env（开发态）
    appdata = os.getenv("APPDATA") or str(Path.home())
    candidates.append(Path(appdata) / "NovaSecretary" / ".env")
    return candidates


def load_env() -> Path | None:
    """加载第一个存在的 .env，已加载过则直接返回（幂等）。"""
    global _loaded
    if _loaded is not None:
        return _loaded
    for path in env_candidates():
        if path.is_file():
            load_dotenv(path, override=False)
            _loaded = path
            return path
    return None


def env_file_path() -> Path:
    """当前使用的 .env 路径（不存在时返回首选路径，供提示/创建用）。"""
    return _loaded or env_candidates()[0]
