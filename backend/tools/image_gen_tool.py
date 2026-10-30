"""文生图工具 generate_image：按「模型能力」路由到不同服务商。

两种 provider（协议不同，不能靠一个开关糊过去）：
- openai   ：OpenAI 兼容 POST {base_url}/images/generations，同步返回 b64/url
- dashscope：阿里百炼原生 POST {root}/api/v1/services/aigc/text2image/image-synthesis，
             异步任务（X-DashScope-Async），再轮询 /api/v1/tasks/{id}

选择顺序（确定性）：
1) 当前激活的模型档案，若勾选了「可生成图片」
2) 档案列表顺序里第一个勾选了「可生成图片」的档案
3) 旧版全局 image_gen_* 配置（兼容兜底）
4) 都没有 → 返回可操作错误，引导去设置里勾选能力

安全：密钥只从 .env 读取（档案的 api_key_env / IMAGE_API_KEY / LLM_API_KEY），不落库。
图片落盘 %APPDATA%/NovaSecretary/generated/，通过 /api/generated/{name} 给前端展示。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool

from backend.agent.model_profiles import resolve_capable_profile
from backend.env_loader import load_env
from backend.storage.config_store import get_config
from backend.storage.db import APP_DATA_DIR

load_env()

MAX_PROMPT_CHARS = 2000
MAX_IMAGES = 2
DEFAULT_SIZE = "1024x1024"

PROVIDER_OPENAI = "openai"
PROVIDER_DASHSCOPE = "dashscope"

DASHSCOPE_DEFAULT_ROOT = "https://dashscope.aliyuncs.com"
DASHSCOPE_SUBMIT_PATH = "/api/v1/services/aigc/text2image/image-synthesis"
DASHSCOPE_POLL_INTERVAL = 2.0
DASHSCOPE_TIMEOUT = 150


class ImageGenError(RuntimeError):
    """文生图配置缺失或调用失败。"""


# 配置类错误统一带上这句，避免模型把它当成临时故障反复重试
_CONFIG_HINT = "（配置问题，重试无效；不要用截图 / OCR 伪造图片，直接告知用户。）"


def generated_dir() -> Path:
    """生成图片的落盘目录（%APPDATA%/NovaSecretary/generated）。"""
    path = APP_DATA_DIR / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_local(base_url: str) -> bool:
    return base_url.startswith(("http://127.0.0.1", "http://localhost"))


def _api_key_from_env(env_name: str) -> str:
    return (
        os.getenv(env_name or "")
        or os.getenv("IMAGE_API_KEY")
        or os.getenv("LLM_API_KEY")
        or ""
    ).strip()


def _dashscope_root(base_url: str) -> str:
    """从兼容模式地址里取出服务根地址（去掉 /compatible-mode/v1 之类的路径）。"""
    parsed = urlparse((base_url or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return DASHSCOPE_DEFAULT_ROOT


def _openai_size(size: str) -> str:
    return (size or DEFAULT_SIZE).replace("*", "x")


def _dashscope_size(size: str) -> str:
    return (size or DEFAULT_SIZE).replace("x", "*")


async def _resolve_target(config: dict[str, Any]) -> dict[str, Any]:
    """解析出真正要调用的生图目标：{provider, base_url, model, api_key, size, source}。"""
    profile = await resolve_capable_profile("image")
    if profile:
        image = profile.get("image") or {}
        base_url = str(image.get("base_url") or profile.get("base_url") or "").strip()
        model = str(image.get("model") or profile.get("model_name") or "").strip()
        env_name = str(profile.get("api_key_env") or "IMAGE_API_KEY")
        api_key = _api_key_from_env(env_name)
        if not base_url:
            raise ImageGenError(
                f"「{profile.get('name')}」勾选了可生成图片，但没有服务地址：" + _CONFIG_HINT
            )
        if not model:
            raise ImageGenError(
                f"「{profile.get('name')}」勾选了生成图片，但出图模型为空："
                "填 wanx2.1-t2i-turbo（百炼）或 gpt-image-1（OpenAI 兼容）。" + _CONFIG_HINT
            )
        if not api_key and not _is_local(base_url):
            raise ImageGenError(
                f"「{profile.get('name')}」缺少密钥：请在 .env 配置 {env_name}。" + _CONFIG_HINT
            )
        return {
            "provider": str(image.get("provider") or PROVIDER_OPENAI),
            "base_url": base_url.rstrip("/"),
            "model": model,
            "api_key": api_key or "local",
            "size": str(image.get("size") or DEFAULT_SIZE),
            "source": str(profile.get("name") or "模型档案"),
        }

    # 兼容旧版全局文生图配置
    if config.get("image_gen_enabled"):
        base_url = str(config.get("image_gen_base_url") or "").strip()
        if not base_url:
            base_url = str((config.get("model") or {}).get("base_url") or "").strip()
        model = str(config.get("image_gen_model") or "").strip()
        api_key = _api_key_from_env("IMAGE_API_KEY")
        if not base_url:
            raise ImageGenError(
                "文生图服务地址为空：请在设置面板填写（如 https://api.siliconflow.cn/v1）。" + _CONFIG_HINT
            )
        if not model:
            raise ImageGenError(
                "文生图模型名称为空：请在设置面板填写（如 Kwai-Kolors/Kolors）。" + _CONFIG_HINT
            )
        if not api_key and not _is_local(base_url):
            raise ImageGenError(
                "文生图缺少密钥：请在 .env 中配置 IMAGE_API_KEY（或复用 LLM_API_KEY）。" + _CONFIG_HINT
            )
        return {
            "provider": PROVIDER_OPENAI,
            "base_url": base_url.rstrip("/"),
            "model": model,
            "api_key": api_key or "local",
            "size": str(config.get("image_gen_size") or DEFAULT_SIZE),
            "source": "全局文生图配置",
        }

    raise ImageGenError(
        "本机没有可用的生图模型。改用代码绘图完成这张图："
        "① write_file 写一个 Python 脚本（numpy + Pillow 已安装，用公式/图层/渐变绘制）"
        "② run_shell 执行脚本，把 PNG 输出到授权目录 "
        "③ image_vl 读回图片检查效果，不满意就改脚本重跑 "
        "④ 完成后调用 show_image 展示给用户。"
        "不要只回复让用户去配置，也不要重复调用本工具。"
    )


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


async def _fetch_url(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url)
    if response.status_code >= 400:
        raise ImageGenError(f"下载生成图片失败：HTTP {response.status_code}")
    return response.content


async def _run_openai(client: httpx.AsyncClient, target: dict[str, Any], prompt: str, size: str, count: int) -> list[dict[str, str]]:
    url = f"{target['base_url']}/images/generations"
    body: dict[str, Any] = {
        "model": target["model"],
        "prompt": prompt,
        "n": count,
        "size": _openai_size(size),
        "response_format": "b64_json",
    }
    headers = {"Authorization": f"Bearer {target['api_key']}"} if target["api_key"] != "local" else {}

    response = await client.post(url, json=body, headers=headers)
    if response.status_code == 400 and "response_format" in body:
        # 部分服务商不认 response_format，去掉后重试一次
        body.pop("response_format", None)
        response = await client.post(url, json=body, headers=headers)
    if response.status_code >= 400:
        detail = response.text[:300].replace("\n", " ")
        raise ImageGenError(f"文生图接口返回 {response.status_code}：{detail}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ImageGenError("文生图接口返回的不是 JSON，请确认服务地址是否指向 OpenAI 兼容接口。") from exc

    items = _payload_items(payload)
    if not items:
        raise ImageGenError(f"接口没有返回图片数据。原始响应：{str(payload)[:300]}")

    saved: list[dict[str, str]] = []
    for item in items[:count]:
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
    return saved


async def _run_dashscope(client: httpx.AsyncClient, target: dict[str, Any], prompt: str, size: str, count: int) -> list[dict[str, str]]:
    """阿里百炼原生文生图：提交异步任务 → 轮询 → 下载结果。"""
    root = _dashscope_root(target["base_url"])
    headers = {
        "Authorization": f"Bearer {target['api_key']}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    body = {
        "model": target["model"],
        "input": {"prompt": prompt},
        "parameters": {"size": _dashscope_size(size), "n": count},
    }
    response = await client.post(f"{root}{DASHSCOPE_SUBMIT_PATH}", json=body, headers=headers)
    if response.status_code >= 400:
        detail = response.text[:300].replace("\n", " ")
        raise ImageGenError(f"百炼生图提交失败（HTTP {response.status_code}）：{detail}")
    try:
        submitted = response.json()
    except ValueError as exc:
        raise ImageGenError("百炼返回的不是 JSON，请确认接口地址。") from exc

    task_id = str(((submitted.get("output") or {}).get("task_id")) or "")
    if not task_id:
        raise ImageGenError(f"百炼没有返回 task_id：{str(submitted)[:300]}")

    poll_headers = {"Authorization": f"Bearer {target['api_key']}"}
    deadline = time.monotonic() + DASHSCOPE_TIMEOUT
    results: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        await asyncio.sleep(DASHSCOPE_POLL_INTERVAL)
        status_resp = await client.get(f"{root}/api/v1/tasks/{task_id}", headers=poll_headers)
        if status_resp.status_code >= 400:
            detail = status_resp.text[:300].replace("\n", " ")
            raise ImageGenError(f"百炼任务查询失败（HTTP {status_resp.status_code}）：{detail}")
        output = (status_resp.json() or {}).get("output") or {}
        state = str(output.get("task_status") or "").upper()
        if state in ("PENDING", "RUNNING"):
            continue
        if state != "SUCCEEDED":
            message = str(output.get("message") or output.get("code") or state or "未知错误")
            raise ImageGenError(f"百炼生图失败：{message}")
        results = [item for item in (output.get("results") or []) if isinstance(item, dict)]
        break
    else:
        raise ImageGenError(f"百炼生图超时（{DASHSCOPE_TIMEOUT}s），任务 {task_id} 仍在执行。")

    if not results:
        raise ImageGenError("百炼任务成功但没有返回图片地址。")

    saved: list[dict[str, str]] = []
    for item in results[:count]:
        url = str(item.get("url") or "")
        if not url:
            continue
        saved.append(_save_image(await _fetch_url(client, url)))
    return saved


@tool
async def generate_image(prompt: str, size: str = "", count: int = 1) -> str:
    """根据文字描述生成图片（文生图），适用于「画一张图 / 生成一张海报 / 出个配图」等需求。

    参数:
        prompt: 图片描述，越具体越好（主体、风格、构图、配色）
        size: 尺寸，如 1024x1024（留空用配置里的默认值）
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
        target = await _resolve_target(config)
    except ImageGenError as exc:
        return str(exc)

    target_size = (size or "").strip() or target["size"] or DEFAULT_SIZE
    if "x" not in target_size.lower() and "*" not in target_size:
        target_size = DEFAULT_SIZE

    # 本机服务（如本地 ComfyUI / 中转）必须绕过系统代理，否则会被代理返回 502
    local = _is_local(target["base_url"])

    try:
        async with httpx.AsyncClient(
            timeout=180, follow_redirects=True, trust_env=not local
        ) as client:
            if target["provider"] == PROVIDER_DASHSCOPE:
                saved = await _run_dashscope(client, target, text, target_size, number)
            else:
                saved = await _run_openai(client, target, text, target_size, number)
    except ImageGenError as exc:
        return str(exc)
    except Exception as exc:  # 网络异常
        return f"生成图片失败：{exc}"

    if not saved:
        return "生成图片失败：返回数据里没有可用的图片内容。"

    result = {
        "prompt": text,
        "model": target["model"],
        "provider": target["provider"],
        "source": target["source"],
        "size": target_size,
        "images": saved,
    }
    return json.dumps(result, ensure_ascii=False)
