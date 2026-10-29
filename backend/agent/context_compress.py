"""上下文 token 估算与摘要压缩。

策略：
- 每轮从 SQLite 重建 state 时先估算 token
- 未超上限：完整回放最近历史
- 超上限：保留最近 N 条原文，较早内容由 LLM 压缩成摘要（写入 system prompt）
- 摘要按会话缓存（cursor = 被压缩的最后一条消息 id），避免每轮重复调用 LLM
"""

from __future__ import annotations

import json
import threading
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

SUMMARY_MARKER = "【早前对话摘要】"
KEEP_RECENT_MESSAGES = 10
SUMMARY_MAX_CHARS = 1200
DEFAULT_MAX_TOKENS = 6000

_summary_cache: dict[str, dict[str, str]] = {}
_encoding: Any = None
_encoding_lock = threading.Lock()

SUMMARY_PROMPT = """请把以下对话压缩成简洁摘要，保留：
1. 用户的目标、偏好与已确认的约束；
2. 已得出的结论或决定；
3. 关键文件、路径、数据引用；
4. 尚未完成的事项。
不要编造内容，不要寒暄，300 字以内。

对话：
{transcript}
"""


def _get_encoding() -> Any:
    global _encoding
    with _encoding_lock:
        if _encoding is None:
            import tiktoken

            _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def estimate_tokens(text: str) -> int:
    """token 估算：优先 tiktoken，失败时用字符启发式兜底。"""
    if not text:
        return 0
    try:
        return len(_get_encoding().encode(text))
    except Exception:
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        return (len(text) - ascii_chars) + ascii_chars // 4 + 1


def estimate_messages_tokens(messages: list[BaseMessage]) -> int:
    total = 0
    for message in messages:
        content = message.content if isinstance(message.content, str) else str(message.content)
        total += estimate_tokens(content) + 4
        for call in getattr(message, "tool_calls", None) or []:
            total += estimate_tokens(json.dumps(call.get("args", {}), ensure_ascii=False)) + 8
    return total


def rows_to_messages(rows: list[dict[str, Any]]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for row in rows:
        cls = HumanMessage if row.get("role") == "user" else AIMessage
        messages.append(cls(content=row.get("content") or "", id=row.get("id")))
    return messages


def _transcript(messages: list[BaseMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        role = "用户" if isinstance(message, HumanMessage) else "助手"
        content = message.content if isinstance(message.content, str) else str(message.content)
        lines.append(f"{role}：{content[:600]}")
    return "\n".join(lines)[:12000]


async def summarize_messages(model: BaseChatModel, messages: list[BaseMessage]) -> str:
    if not messages:
        return ""
    response = await model.bind(temperature=0).ainvoke(
        [HumanMessage(content=SUMMARY_PROMPT.format(transcript=_transcript(messages)))]
    )
    return str(getattr(response, "content", "") or "").strip()[:SUMMARY_MAX_CHARS]


async def prepare_history(
    session_id: str,
    rows: list[dict[str, Any]],
    max_tokens: Optional[int] = None,
    model: Optional[BaseChatModel] = None,
) -> tuple[list[BaseMessage], str]:
    """返回 (本轮回放的消息, 历史摘要)。摘要为空表示无需压缩。"""
    messages = rows_to_messages(rows)
    limit = int(max_tokens or DEFAULT_MAX_TOKENS)
    if len(messages) <= KEEP_RECENT_MESSAGES:
        return messages, ""
    if estimate_messages_tokens(messages) <= limit:
        return messages, ""

    old_rows = rows[:-KEEP_RECENT_MESSAGES]
    recent_messages = messages[-KEEP_RECENT_MESSAGES:]
    cursor = str(old_rows[-1].get("id") or "")

    cached = _summary_cache.get(session_id)
    if cached and cached.get("cursor") == cursor:
        return recent_messages, cached.get("summary", "")

    if model is None:
        from backend.agent.llm_adapter import build_chat_model

        model = await build_chat_model(streaming=False)

    summary = await summarize_messages(model, messages[:-KEEP_RECENT_MESSAGES])
    _summary_cache[session_id] = {"cursor": cursor, "summary": summary}
    return recent_messages, summary


def clear_cache(session_id: Optional[str] = None) -> None:
    if session_id is None:
        _summary_cache.clear()
    else:
        _summary_cache.pop(session_id, None)
