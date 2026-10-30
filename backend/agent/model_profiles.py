"""模型档案（profile）：多套模型一键切换。

安全边界（04-security）：
- 档案只存非密钥字段（名称 / base_url / model_name / 密钥所在环境变量名）到 sqlite
- API Key 由后端写入 backend/.env，前端永远拿不到明文，只能看到“已配置/未配置”
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from backend.env_loader import env_file_path
from backend.storage.config_store import get_config, save_config

DEFAULT_ENV_NAME = "LLM_API_KEY"
MAX_PROFILES = 20


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


# LangChain 的 ChatOpenAI 会在 base_url 后自动拼 /chat/completions，
# 用户从服务商文档里复制的往往是完整接口地址，这里统一还原成 base_url。
_CHAT_SUFFIXES = ("/chat/completions", "/completions")


def normalize_base_url(value: Any) -> str:
    """去掉结尾的 /chat/completions、/completions 与多余斜杠。"""
    text = _clean(value).rstrip("/")
    for suffix in _CHAT_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text.rstrip("/")


# 能力声明：chat 恒为真（档案本身就是一套对话连接），vision / image 由用户勾选。
CAPABILITIES = ("chat", "vision", "image")
IMAGE_PROVIDERS = ("openai", "dashscope")
DEFAULT_IMAGE_SIZE = "1024x1024"


def _normalize_capabilities(value: Any) -> list[str]:
    if isinstance(value, str):
        items: list[Any] = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = []
    caps: list[str] = ["chat"]
    for item in items:
        name = _clean(item).lower()
        if name in CAPABILITIES and name not in caps:
            caps.append(name)
    return caps


def _normalize_image(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    provider = _clean(data.get("provider")).lower() or "openai"
    if provider not in IMAGE_PROVIDERS:
        provider = "openai"
    return {
        "provider": provider,
        "model": _clean(data.get("model")),
        "base_url": normalize_base_url(data.get("base_url")),
        "size": _clean(data.get("size")) or DEFAULT_IMAGE_SIZE,
    }


def has_capability(profile: dict[str, Any], capability: str) -> bool:
    return capability in _normalize_capabilities(profile.get("capabilities"))


def _public(profile: dict[str, Any]) -> dict[str, Any]:
    """对外返回的档案字段（不含任何密钥）。"""
    env_name = _clean(profile.get("api_key_env")) or DEFAULT_ENV_NAME
    return {
        "id": _clean(profile.get("id")),
        "name": _clean(profile.get("name")) or "未命名模型",
        "base_url": normalize_base_url(profile.get("base_url")),
        "model_name": _clean(profile.get("model_name")),
        "api_key_env": env_name,
        "has_key": bool(_clean(os.getenv(env_name))),
        "capabilities": _normalize_capabilities(profile.get("capabilities")),
        "image": _normalize_image(profile.get("image")),
    }


async def ensure_profiles() -> tuple[list[dict[str, Any]], str]:
    """读取档案列表；旧配置（只有 model 字段）首次访问时自动迁移为一个默认档案。"""
    config = await get_config()
    profiles = [p for p in (config.get("model_profiles") or []) if isinstance(p, dict)]
    active_id = _clean(config.get("active_model_id"))

    if not profiles:
        model = config.get("model") or {}
        profile = {
            "id": "default",
            "name": "默认模型",
            "base_url": _clean(model.get("base_url")),
            "model_name": _clean(model.get("model_name")),
            "api_key_env": DEFAULT_ENV_NAME,
        }
        profiles = [profile]
        active_id = "default"
        await save_config({"model_profiles": profiles, "active_model_id": active_id})

    if not active_id or not any(p.get("id") == active_id for p in profiles):
        active_id = _clean(profiles[0].get("id"))
        await save_config({"active_model_id": active_id})

    # 旧档案补齐能力字段（只补结构，不改语义）
    changed = False
    for profile in profiles:
        caps = _normalize_capabilities(profile.get("capabilities"))
        image = _normalize_image(profile.get("image"))
        if profile.get("capabilities") != caps or profile.get("image") != image:
            profile["capabilities"] = caps
            profile["image"] = image
            changed = True
    if changed:
        await save_config({"model_profiles": profiles})

    return profiles, active_id


async def list_profiles() -> dict[str, Any]:
    profiles, active_id = await ensure_profiles()
    return {"profiles": [_public(p) for p in profiles], "active_id": active_id}


async def get_active_profile() -> dict[str, Any] | None:
    profiles, active_id = await ensure_profiles()
    for profile in profiles:
        if _clean(profile.get("id")) == active_id:
            return _public(profile)
    return _public(profiles[0]) if profiles else None


async def resolve_capable_profile(capability: str) -> dict[str, Any] | None:
    """按「当前激活档案优先，其次列表顺序」挑出具备该能力的档案（不含密钥）。"""
    profiles, active_id = await ensure_profiles()
    ordered = sorted(profiles, key=lambda item: 0 if _clean(item.get("id")) == active_id else 1)
    for profile in ordered:
        if capability in _normalize_capabilities(profile.get("capabilities")):
            return _public(profile)
    return None


async def upsert_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """新增或更新一个档案（不允许在这里写密钥）。"""
    profiles, active_id = await ensure_profiles()
    profile_id = _clean(payload.get("id")) or _new_id()
    name = _clean(payload.get("name")) or "未命名模型"
    base_url = normalize_base_url(payload.get("base_url"))
    model_name = _clean(payload.get("model_name"))
    env_name = _clean(payload.get("api_key_env")) or DEFAULT_ENV_NAME
    capabilities = _normalize_capabilities(payload.get("capabilities"))
    image = _normalize_image(payload.get("image"))

    if base_url and not base_url.startswith(("http://", "https://")):
        raise ValueError("模型服务地址必须以 http:// 或 https:// 开头")
    if not model_name:
        raise ValueError("模型名称不能为空")
    if "image" in capabilities and not (image["model"] or model_name):
        raise ValueError("勾选「可生成图片」时需要填写生图模型名称")

    entry = {
        "id": profile_id,
        "name": name,
        "base_url": base_url,
        "model_name": model_name,
        "api_key_env": env_name,
        "capabilities": capabilities,
        "image": image,
    }

    existing = next((p for p in profiles if _clean(p.get("id")) == profile_id), None)
    if existing is None:
        if len(profiles) >= MAX_PROFILES:
            raise ValueError(f"模型档案最多 {MAX_PROFILES} 个")
        profiles.append(entry)
    else:
        existing.update(entry)

    await save_config({"model_profiles": profiles})
    if not active_id:
        await save_config({"active_model_id": profile_id})
    return {"profiles": [_public(p) for p in profiles], "active_id": active_id or profile_id}


async def delete_profile(profile_id: str) -> dict[str, Any]:
    profiles, active_id = await ensure_profiles()
    remaining = [p for p in profiles if _clean(p.get("id")) != profile_id]
    if len(remaining) == len(profiles):
        raise ValueError("档案不存在")
    if not remaining:
        raise ValueError("至少保留一个模型档案")
    new_active = active_id if any(p.get("id") == active_id for p in remaining) else _clean(remaining[0].get("id"))
    await save_config({"model_profiles": remaining, "active_model_id": new_active})
    return {"profiles": [_public(p) for p in remaining], "active_id": new_active}


async def activate_profile(profile_id: str) -> dict[str, Any]:
    profiles, _ = await ensure_profiles()
    if not any(_clean(p.get("id")) == profile_id for p in profiles):
        raise ValueError("档案不存在")
    await save_config({"active_model_id": profile_id})
    return {"profiles": [_public(p) for p in profiles], "active_id": profile_id}


def _write_env_value(env_name: str, value: str) -> None:
    """把密钥写入 .env 并同步到当前进程环境变量（立即生效，无需重启）。"""
    path = env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    prefix = f"{env_name}="
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[index] = f"{env_name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{env_name}={value}")

    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    os.environ[env_name] = value


async def set_profile_key(profile_id: str, api_key: str) -> dict[str, Any]:
    profiles, active_id = await ensure_profiles()
    profile = next((p for p in profiles if _clean(p.get("id")) == profile_id), None)
    if profile is None:
        raise ValueError("档案不存在")
    key = _clean(api_key)
    if not key:
        raise ValueError("密钥不能为空")
    env_name = _clean(profile.get("api_key_env")) or DEFAULT_ENV_NAME
    _write_env_value(env_name, key)
    return {"profiles": [_public(p) for p in profiles], "active_id": active_id}
