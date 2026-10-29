"""M8 自测：token 估算 / 历史压缩 / 摘要注入（离线，不消耗 API）。

    $env:PYTHONPATH = "e:\\nova-secretary"
    uv run --project backend python -m backend.agent.selftest_context
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage

from backend.agent import context_compress as cc
from backend.agent.prompts import build_system_prompt
from backend.agent.selftest_agent_graph import ScriptedChatModel


def make_rows(count: int, prefix: str = "m") -> list[dict]:
    return [
        {
            "id": f"{prefix}{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"消息内容 {index} " + "这是一段较长的历史文本用于撑大 token" * 5,
        }
        for index in range(count)
    ]


async def main() -> None:
    assert cc.estimate_tokens("你好世界") > 0
    assert cc.estimate_tokens("") == 0
    messages = cc.rows_to_messages(make_rows(4))
    assert cc.estimate_messages_tokens(messages) > 0
    print("[PASS] 1. token 估算可用")

    rows = make_rows(6)
    messages, summary = await cc.prepare_history("case-short", rows, max_tokens=100000)
    assert summary == "" and len(messages) == 6
    print("[PASS] 2. 未超上限时完整回放历史")

    rows = make_rows(30)
    model = ScriptedChatModel(script=[AIMessage(content="这是早期对话摘要")])
    messages, summary = await cc.prepare_history("case-long", rows, max_tokens=100, model=model)
    assert summary == "这是早期对话摘要", summary
    assert len(messages) == cc.KEEP_RECENT_MESSAGES
    assert messages[-1].id == rows[-1]["id"]
    print("[PASS] 3. 超限时保留最近消息并生成摘要")

    # 缓存命中：脚本模型只有一条回复，再调用会抛错
    messages2, summary2 = await cc.prepare_history("case-long", rows, max_tokens=100, model=model)
    assert summary2 == summary and len(messages2) == cc.KEEP_RECENT_MESSAGES
    print("[PASS] 4. 摘要缓存命中，不重复调用 LLM")

    prompt = build_system_prompt([], extra_context="偏好：简洁", history_summary="早期结论：A")
    assert "早期结论：A" in prompt and "偏好：简洁" in prompt
    print("[PASS] 5. 记忆与历史摘要均注入 system prompt")

    rows2 = rows + make_rows(2, prefix="n")
    model2 = ScriptedChatModel(script=[AIMessage(content="更新后的摘要")])
    messages3, summary3 = await cc.prepare_history("case-long", rows2, max_tokens=100, model=model2)
    assert summary3 == "更新后的摘要", summary3
    assert len(messages3) == cc.KEEP_RECENT_MESSAGES
    print("[PASS] 6. 历史推进后重新生成摘要")

    cc.clear_cache()
    print("\nM8 全部自测通过")


if __name__ == "__main__":
    asyncio.run(main())
