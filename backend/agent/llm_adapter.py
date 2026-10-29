"""LLM 模型适配层。

职责（自研轻量中间层，见 09-runtime-middleware-spec.md）：
- 统一封装 OpenAI 兼容客户端（DeepSeek / Ollama / 其他兼容服务）
- 模型非密钥参数从 sqlite app_config 读取，api_key 只从 .env 读取（密钥不入库）
- 内置重试（max_retries）
- 多模态图片：仅在调用瞬间临时构造 base64，使用后即丢弃，不落库
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from backend.env_loader import load_env
from langchain_openai import ChatOpenAI

from backend.agent.model_params import build_model_kwargs
from backend.storage.config_store import get_config

load_env()

_LOCAL_HOSTS = ("http://127.0.0.1", "http://localhost")


def local_http_client(base_url: str) -> Optional[httpx.AsyncClient]:
    """本机模型服务（Ollama 等）必须绕过系统代理，否则会被代理拦截返回 502。"""
    if base_url.startswith(_LOCAL_HOSTS):
        return httpx.AsyncClient(trust_env=False)
    return None


class LLMConfigError(RuntimeError):
    """模型配置缺失或不合法（前端应展示友好提示）。"""


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


async def build_chat_model(streaming: bool = True) -> ChatOpenAI:
    """根据配置构建 ChatOpenAI 客户端；缺少 api_key 时抛出 LLMConfigError。"""
    config = await get_config()
    model_cfg = config.get("model") or {}

    base_url = _clean(model_cfg.get("base_url")) or _clean(os.getenv("LLM_BASE_URL"))
    model_name = _clean(model_cfg.get("model_name")) or _clean(os.getenv("LLM_MODEL_NAME"))
    api_key = _clean(os.getenv("LLM_API_KEY"))
    temperature = model_cfg.get("temperature", os.getenv("LLM_TEMPERATURE", 0.7))

    if not base_url:
        raise LLMConfigError("未配置 LLM_BASE_URL，请在设置面板或 .env 中填写模型服务地址。")
    if not model_name:
        raise LLMConfigError("未配置模型名称，请在设置面板或 .env 中填写 model_name。")
    if not api_key:
        raise LLMConfigError("未配置 LLM_API_KEY，请在 backend/.env 中填写模型密钥后重启后端。")

    try:
        temperature_value = float(temperature)
    except (TypeError, ValueError):
        temperature_value = 0.7

    http_client = local_http_client(base_url)
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature_value,
        max_retries=2,
        timeout=60,
        streaming=streaming,
        **({"http_async_client": http_client} if http_client else {}),
        **build_model_kwargs(model_cfg),
    )


def has_api_key() -> bool:
    """供设置面板/启动自检展示：只返回是否存在，不暴露密钥。"""
    return bool(_clean(os.getenv("LLM_API_KEY")))


SUPPORTED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def image_content_part(image_path: str | Path, max_size_mb: int = 10) -> dict[str, Any]:
    """把本地图片转成 OpenAI 多模态 content part（临时 base64，调用结束即丢弃）。"""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在：{path}")
    if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError(f"不支持的图片格式：{path.suffix}")
    raw = path.read_bytes()
    if len(raw) > max_size_mb * 1024 * 1024:
        raise ValueError(f"图片超过 {max_size_mb}MB 上限：{path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(raw).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def build_multimodal_content(text: str, image_paths: Optional[list[str | Path]] = None) -> list[dict[str, Any]]:
    """构造多模态消息 content：文本 + 图片 parts（临时使用，不持久化）。"""
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for image_path in image_paths or []:
        parts.append(image_content_part(image_path))
    return parts
