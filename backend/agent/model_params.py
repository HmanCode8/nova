"""模型请求参数中间层。

职责（对齐 09-runtime-middleware-spec.md 的自研轻量中间层）：
- 把设置面板里的模型参数统一翻译成 ChatOpenAI 可接受的 kwargs
- 思考模式：enable_thinking / thinking_budget 合并进 extra_body
  不同服务商字段不一样（DashScope、硅基流动、vLLM 多为 enable_thinking；
  OpenAI 推理模型用 reasoning_effort），这里只做透传，不做服务商猜测
- 参数非法时静默丢弃该项，绝不把坏参数发给模型导致整轮 400

为什么不使用 langchain.agents.middleware：项目需要自定义流式事件与中断时机，
用一层纯函数完成参数注入，控制权最高、调试最直观。
"""

from __future__ import annotations

import json
from typing import Any

REASONING_EFFORTS: tuple[str, ...] = ("", "low", "medium", "high")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_extra_body(value: Any) -> dict[str, Any]:
    """extra_body 允许对象或 JSON 字符串；非法内容一律视为空对象。"""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_model_kwargs(model_cfg: dict[str, Any]) -> dict[str, Any]:
    """根据 model 配置生成 ChatOpenAI 可选参数（不含 model/base_url/api_key/temperature）。"""
    cfg = model_cfg if isinstance(model_cfg, dict) else {}
    kwargs: dict[str, Any] = {}

    max_tokens = _as_int(cfg.get("max_tokens"))
    if max_tokens > 0:
        kwargs["max_tokens"] = max_tokens

    top_p = _as_float(cfg.get("top_p"))
    if 0 < top_p <= 1:
        kwargs["top_p"] = top_p

    effort = str(cfg.get("reasoning_effort") or "").strip().lower()
    if effort in REASONING_EFFORTS and effort:
        kwargs["reasoning_effort"] = effort

    extra_body = normalize_extra_body(cfg.get("extra_body"))
    if cfg.get("thinking_enabled"):
        # setdefault：用户显式写在 extra_body 里的值优先
        extra_body.setdefault("enable_thinking", True)
    thinking_budget = _as_int(cfg.get("thinking_budget"))
    if thinking_budget > 0:
        extra_body.setdefault("thinking_budget", thinking_budget)
    if extra_body:
        kwargs["extra_body"] = extra_body

    return kwargs
