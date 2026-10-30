"""视觉理解模型适配层（OpenAI 兼容协议，支持远程 API 与本机 Ollama）。

两种来源（设置面板「视觉理解 · 图片来源」）：
- main：直接复用主模型（主模型本身支持图片输入），不再要求单独的 VL 密钥
- separate：使用独立的 VL 服务（vl_base_url / vl_model_name + VL_API_KEY）

安全约束：
- 密钥只从 .env 读取（LLM_API_KEY / VL_API_KEY），不进 sqlite
- 图片仅在本轮调用中临时转 base64，用完即丢弃，不落库
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from backend.agent.llm_adapter import image_content_part, local_http_client
from backend.agent.model_profiles import normalize_base_url, resolve_capable_profile
from backend.storage.config_store import get_config

DEFAULT_QUESTION = "请详细描述这张图片：画面内容、界面布局、关键元素，以及能看出的结构或流程。"

_LOCAL_HOSTS = ("http://127.0.0.1", "http://localhost")


class VLConfigError(RuntimeError):
    """视觉模型未启用或配置不完整。"""


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content or "")


async def vision_settings(config: dict) -> tuple[str, str, str]:
    """返回 (base_url, model_name, api_key)；缺配置时抛 VLConfigError。

    优先使用「勾选了可看图」的模型档案（当前激活档案优先），
    其次回落到旧版 vision_source（main / separate）配置。
    """
    profile = await resolve_capable_profile("vision")
    if profile:
        base_url = normalize_base_url(profile.get("base_url"))
        model_name = str(profile.get("model_name") or "").strip()
        env_name = str(profile.get("api_key_env") or "LLM_API_KEY")
        api_key = (os.getenv(env_name) or os.getenv("LLM_API_KEY") or "").strip()
        if base_url and model_name and (api_key or base_url.startswith(_LOCAL_HOSTS)):
            return base_url, model_name, api_key or "ollama"

    source = str(config.get("vision_source") or "main").strip().lower()

    if source != "separate":
        model_cfg = config.get("model") or {}
        base_url = normalize_base_url(model_cfg.get("base_url") or os.getenv("LLM_BASE_URL") or "")
        model_name = str(model_cfg.get("model_name") or os.getenv("LLM_MODEL_NAME") or "").strip()
        api_key = (os.getenv("LLM_API_KEY") or "").strip()
        if not base_url or not model_name:
            raise VLConfigError(
                "当前视觉理解使用主模型，但主模型未配置完整：请先在设置面板填写模型服务地址与模型名称。"
            )
        if not api_key and not base_url.startswith(_LOCAL_HOSTS):
            raise VLConfigError("主模型缺少密钥：请在 .env 中填写 LLM_API_KEY。")
        return base_url, model_name, api_key or "ollama"

    base_url = normalize_base_url(config.get("vl_base_url") or os.getenv("VL_BASE_URL") or "")
    model_name = str(config.get("vl_model_name") or os.getenv("VL_MODEL_NAME") or "").strip()
    api_key = (os.getenv("VL_API_KEY") or "").strip()
    if not base_url or not model_name:
        raise VLConfigError("视觉理解模型未配置完整：请在设置面板填写 VL 服务地址与模型名称。")
    if not api_key and not base_url.startswith(_LOCAL_HOSTS):
        raise VLConfigError("视觉理解模型缺少密钥：请在 backend/.env 配置 VL_API_KEY。")
    return base_url, model_name, api_key or "ollama"


async def describe_image(path: Path, question: str = "") -> str:
    """调用视觉模型理解图片，返回文本描述；配置缺失时抛 VLConfigError。"""
    config = await get_config()
    if not config.get("vl_enabled"):
        raise VLConfigError("当前已关闭视觉理解，仅支持图片 OCR 文字识别。")

    base_url, model_name, api_key = await vision_settings(config)

    content = [
        {"type": "text", "text": (question or "").strip() or DEFAULT_QUESTION},
        image_content_part(path),
    ]
    http_client = local_http_client(base_url)
    model = ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=0.2,
        max_retries=1,
        timeout=90,
        streaming=False,
        **({"http_async_client": http_client} if http_client else {}),
    )
    response = await model.ainvoke([HumanMessage(content=content)])
    return _text_of(getattr(response, "content", "")).strip()
