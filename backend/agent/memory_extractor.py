"""自动记忆抽取：每轮对话结束后，由 LLM 提炼值得长期记住的信息。

只抽取长期偏好/约定，不保存临时任务与敏感信息；重复内容自动跳过。
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel

from backend.storage import memory_store, session_store

MAX_ASSISTANT_CHARS = 1500
MAX_NEW_PER_SCOPE = 3

EXTRACT_PROMPT = """你负责从一轮对话中提炼「值得长期记住」的信息。

抽取规则：
1. 只抽取用户明确表达的长期偏好、身份背景、固定约定（例如"回答尽量简洁"、"我主要用 Python"）。
2. 不抽取临时任务、一次性事实、与用户无关的内容。
3. 绝不抽取密码、密钥、身份证、银行卡等敏感信息。
4. 每条不超过 60 字，独立成句；没有可记忆内容时返回空数组。

已有全局偏好：
{global_items}

已有本会话记忆：
{session_items}

本轮用户消息：
{user_text}

本轮助手回复（节选）：
{assistant_text}

只输出 JSON（不要解释），格式：
{{"session": ["..."], "global": ["..."]}}
"""


def _bullet(items: list[dict[str, Any]]) -> str:
    if not items:
        return "（无）"
    return "\n".join(f"- {item['memory_text']}" for item in items[:10])


def parse_extraction(raw: str) -> dict[str, list[str]]:
    """解析模型输出，兼容 ```json 代码块。解析失败返回空 dict。"""
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}

    result: dict[str, list[str]] = {}
    for scope in ("session", "global"):
        values = data.get(scope)
        if isinstance(values, list):
            cleaned = [str(item).strip()[:120] for item in values if str(item).strip()]
            result[scope] = cleaned[:MAX_NEW_PER_SCOPE]
    return result


async def extract_and_store(
    session_id: str, assistant_text: str, model: BaseChatModel
) -> dict[str, int]:
    """提炼并写入记忆，返回 {"session": n, "global": m} 新增条数。"""
    user_text = (await session_store.get_last_user_message(session_id)).strip()
    if len(user_text) < 4:
        return {"session": 0, "global": 0}

    global_items = await memory_store.list_memories("global")
    session_items = await memory_store.list_memories("session", session_id)
    prompt = EXTRACT_PROMPT.format(
        global_items=_bullet(global_items),
        session_items=_bullet(session_items),
        user_text=user_text[:800],
        assistant_text=(assistant_text or "")[:MAX_ASSISTANT_CHARS],
    )

    response = await model.bind(temperature=0).ainvoke([HumanMessage(content=prompt)])
    parsed = parse_extraction(str(getattr(response, "content", "") or ""))

    added = {"session": 0, "global": 0}
    for text in parsed.get("session", []):
        if await memory_store.add_memory("session", text, session_id):
            added["session"] += 1
    for text in parsed.get("global", []):
        if await memory_store.add_memory("global", text):
            added["global"] += 1
    return added
