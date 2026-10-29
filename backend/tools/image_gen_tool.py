"""文生图工具 generate_image：对接 OpenAI 兼容 /images/generations 接口。

说明：
- 聊天模型（即使支持多模态）只能「看懂」图片，不能产出图片文件；生成图片必须单独调用文生图服务
- 密钥只从 .env 读取：优先 IMAGE_API_KEY，未配置时复用 LLM_API_KEY（同服务商中转常见）
- 生成的图片落在应用数据目录 generated/，通过 /api/generated/{name} 提供给前端展示
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from langchain_core.tools import tool

from backend.env_loader import load_env
from backend.storage.config_store import get_config
from backend.storage.db import APP_DATA_DIR

load_env()

MAX_PROMPT_CHARS = 2000
MAX_IMAGES = 2
DEFAULT_SIZE = "1024x1024"


class ImageGenError(RuntimeError):
    """文生图配置缺失或调用失败。"""


def generated_dir() -> Path:
    """生成图片的落盘目录（%APPDATA%/NovaSecretary/generated）。"""
    path = APP_DATA_DIR / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _api_key() -> str:
    return (os.getenv("IMAGE_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()


def _settings(config: dict[str, Any]) -> tuple[str, str, str]:
    """返回 (base_url, model, api_key)；缺配置时抛 ImageGenError。"""
    if not config.get("image_gen_enabled"):
        raise ImageGenError(
            "文生图未启用：请在设置面板「文生图」中开启，并填写服务地址与模型名称。"
        )
    base_url = str(config.get("image_gen_base_url") or "").strip()
    if not base_url:
        base_url = str((config.get("model") or {}).get("base_url") or "").strip()
    model = str(config.get("image_gen_model") or "").strip()
    if not base_url:
        raise ImageGenError("文生图服务地址为空：请在设置面板填写（如 https://api.siliconflow.cn/v1）。")
    if not model:
        raise ImageGenError("文生图模型名称为空：请在设置面板填写（如 Kwai-Kolors/Kolors）。")
    api_key = _api_key()
    local = base_url.startswith(("http://127.0.0.1", "http://localhost"))
    if not api_key and not local:
        raise ImageGenError("文生图缺少密钥：请在 .env 中配置 IMAGE_API_KEY（或复用 LLM_API_KEY）。")
    return base_url.rstrip("/"), model, api_key or "local"


def _file_suffix(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if raw.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def _save_image(raw: bytes) -> dict[str, str]:
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}{_file_suffix(raw)}"
    path = generated_dir() / name
    path.write_bytes(raw)
    return {"name": name, "path": str(path), "url": f"/api/generated/{name}"}


def _payload_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(payload.get("images"), list):  # 少数中转返回 images 字段
        return [item for item in payload["images"] if isinstance(item, dict)]
    return []


async def _request(client: httpx.AsyncClient, url: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
    """优先要 b64_json；部分服务商不认该字段时去掉后重试一次。"""
    response = await client.post(url, json=body, headers=headers)
    if response.status_code == 400 and "response_format" in body:
        retry_body = {k: v for k, v in body.items() if k != "response_format"}
        response = await client.post(url, json=retry_body, headers=headers)
    if response.status_code >= 400:
        detail = response.text[:300].replace("\n", " ")
        raise ImageGenError(f"文生图接口返回 {response.status_code}：{detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise ImageGenError("文生图接口返回的不是 JSON，请确认服务地址是否指向 OpenAI 兼容接口。") from exc


async def _fetch_url(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url)
    if response.status_code >= 400:
        raise ImageGenError(f"下载生成图片失败：HTTP {response.status_code}")
    return response.content


@tool
async def generate_image(prompt: str, size: str = "", count: int = 1) -> str:
    """根据文字描述生成图片（文生图），适用于「画一张图 / 生成一张海报 / 出个配图」等需求。

    参数:
        prompt: 图片描述，越具体越好（主体、风格、构图、配色）
        size: 尺寸，如 1024x1024（留空用设置里的默认值）
        count: 生成数量，1~2，默认 1
    返回图片的本地路径与展示地址；不要把 base64 内容再输出给用户。
    """
    text = (prompt or "").strip()
    if not text:
        return "生成图片失败：图片描述为空。"
    if len(text) > MAX_PROMPT_CHARS:
        return f"生成图片失败：描述超过 {MAX_PROMPT_CHARS} 字符，请精简后重试。"
    try:
        number = max(1, min(MAX_IMAGES, int(count)))
    except (TypeError, ValueError):
        number = 1

    config = await get_config()
    try:
        base_url, model, api_key = _settings(config)
    except ImageGenError as exc:
        return str(exc)

    target_size = (size or "").strip() or str(config.get("image_gen_size") or DEFAULT_SIZE)
    if "x" not in target_size:
        target_size = DEFAULT_SIZE

    body: dict[str, Any] = {
        "model": model,
        "prompt": text,
        "n": number,
        "size": target_size,
        "response_format": "b64_json",
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    # 本机服务（如本地 ComfyUI / 中转）必须绕过系统代理，否则会被代理返回 502
    local = base_url.startswith(("http://127.0.0.1", "http://localhost"))

    try:
        async with httpx.AsyncClient(
            timeout=180, follow_redirects=True, trust_env=not local
        ) as client:
            payload = await _request(client, f"{base_url}/images/generations", body, headers)
            items = _payload_items(payload)
            if not items:
                return f"生成图片失败：接口没有返回图片数据。原始响应：{str(payload)[:300]}"

            saved: list[dict[str, str]] = []
            for item in items[:number]:
                encoded = item.get("b64_json")
                if isinstance(encoded, str) and encoded:
                    raw = base64.b64decode(encoded)
                elif isinstance(item.get("url"), str) and item["url"]:
                    raw = await _fetch_url(client, item["url"])
                else:
                    continue
                record = _save_image(raw)
                if item.get("revised_prompt"):
                    record["revised_prompt"] = str(item["revised_prompt"])
                saved.append(record)
    except ImageGenError as exc:
        return str(exc)
    except Exception as exc:  # 网络异常
        return f"生成图片失败：{exc}"

    if not saved:
        return "生成图片失败：返回数据里没有可用的图片内容。"

    result = {
        "prompt": text,
        "model": model,
        "size": target_size,
        "images": saved,
    }
    return json.dumps(result, ensure_ascii=False)
