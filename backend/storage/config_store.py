"""app_config 全局配置读写（单行 config_json）。

安全约束（04-security-and-safety.md / 05-storage-spec.md）：
- API Key、Tavily Key 等密钥只存 .env，绝不写入 sqlite
- 这里只持久化非敏感配置：联网开关、自动记忆开关、目录白名单、文件大小上限、模型非密钥参数
"""

from __future__ import annotations

import copy
import json
from typing import Any

from backend.storage.db import db

# 默认配置：新增字段时旧库自动补齐
DEFAULT_CONFIG: dict[str, Any] = {
    # 自主模式：开启后除删除（与破坏性命令）外不再逐步人工确认；用户明确授权
    "autonomy_mode": True,
    # 命令执行开关（run_shell）
    "shell_enabled": True,
    "web_search_enabled": True,
    "auto_memory_enabled": True,
    "tts_enabled": True,
    "vl_enabled": True,
    "vl_base_url": "",
    "vl_model_name": "",
    "vl_require_confirm": False,
    # 视觉理解来源：main = 复用主模型（主模型本身支持图片输入）；separate = 独立 VL 模型
    "vision_source": "main",
    # 文生图（OpenAI 兼容 /images/generations）
    "image_gen_enabled": False,
    "image_gen_base_url": "",
    "image_gen_model": "",
    "image_gen_size": "1024x1024",
    "allowed_dirs": [],
    "max_file_size_mb": 10,
    "confirm_timeout_seconds": 180,
    "max_context_tokens": 6000,
    # 后台任务（Runtime 层）：并发上限与单任务超时回收
    "max_concurrent_tasks": 2,
    "task_timeout_seconds": 900,
    "model": {
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "temperature": 0.7,
        # 以下为可选的模型请求参数（0 / 空表示不发送）
        "max_tokens": 0,
        "top_p": 0,
        "reasoning_effort": "",
        "thinking_enabled": False,
        "thinking_budget": 0,
        "extra_body": {},
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并：保留默认值中的新增字段，字典类型逐层合并。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


async def get_config() -> dict[str, Any]:
    """读取当前配置，与默认值合并后返回。

    allowed_dirs 以白名单表为准（whitelist_dirs），保证「设置面板看到的」与
    「中间件实际校验的」永远一致。
    """
    row = await db.fetch_one("SELECT config_json FROM app_config ORDER BY id LIMIT 1")
    if row is None:
        merged = copy.deepcopy(DEFAULT_CONFIG)
    else:
        try:
            stored = json.loads(row["config_json"])
        except (TypeError, json.JSONDecodeError):
            stored = {}
        merged = _deep_merge(DEFAULT_CONFIG, stored if isinstance(stored, dict) else {})
    try:
        from backend.storage import whitelist_store  # 延迟导入避免循环依赖

        merged["allowed_dirs"] = await whitelist_store.list_dirs()
    except Exception:  # 白名单读取失败时退回 JSON 里的旧值，不影响对话
        pass
    return merged


async def save_config(patch: dict[str, Any]) -> dict[str, Any]:
    """局部更新配置并落库，返回合并后的完整配置。"""
    merged = _deep_merge(await get_config(), patch)
    # extra_body 是「整份参数」而不是可累加的配置：必须整体替换，否则删掉的键会残留
    patch_model = patch.get("model") if isinstance(patch, dict) else None
    if isinstance(patch_model, dict) and "extra_body" in patch_model:
        body = patch_model.get("extra_body")
        merged.setdefault("model", {})["extra_body"] = dict(body) if isinstance(body, dict) else {}
    # 白名单双写：表是权威来源，JSON 里同步一份便于导出/排障
    if isinstance(patch, dict) and isinstance(patch.get("allowed_dirs"), list):
        from backend.storage import whitelist_store  # 延迟导入避免循环依赖

        try:
            merged["allowed_dirs"] = await whitelist_store.replace_all(patch["allowed_dirs"])
        except Exception:
            pass
    payload = json.dumps(merged, ensure_ascii=False)
    row = await db.fetch_one("SELECT id FROM app_config ORDER BY id LIMIT 1")
    if row is None:
        await db.execute("INSERT INTO app_config (config_json) VALUES (?)", (payload,))
    else:
        await db.execute(
            "UPDATE app_config SET config_json = ? WHERE id = ?", (payload, row["id"])
        )
    return merged
