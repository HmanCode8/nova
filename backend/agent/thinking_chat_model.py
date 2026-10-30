"""带思考内容的 ChatOpenAI 子类。

背景：langchain_openai 在流式解析时只映射标准字段（role / content / tool_calls /
function_call / audio），服务商下发的 delta.reasoning_content 会被直接丢弃：
- DeepSeek（deepseek-reasoner）
- 阿里百炼（qwen-plus / qwen3 系列，enable_thinking=true）
- 硅基流动 / vLLM（enable_thinking）

结果就是前端只看到回答、看不到「思考过程」。这里在 chunk 转换后把该字段补进
additional_kwargs，后续 server 的 _chunk_reasoning 就能正常透出。
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

# 各家字段名不同，按优先级取第一个非空的
REASONING_FIELDS: tuple[str, ...] = ("reasoning_content", "reasoning", "thinking")


class ReasoningChatOpenAI(ChatOpenAI):
    """保留 reasoning_content 的 ChatOpenAI。"""

    def _convert_chunk_to_generation_chunk(  # type: ignore[override]
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: Optional[dict],
    ) -> Optional[ChatGenerationChunk]:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return generation_chunk
        delta = choices[0].get("delta") or {}
        if not isinstance(delta, dict):
            return generation_chunk

        message = generation_chunk.message
        if not isinstance(message, AIMessageChunk):
            return generation_chunk

        for field in REASONING_FIELDS:
            value = delta.get(field)
            if isinstance(value, str) and value:
                # 逐块累加，保持与 content 一致的增量语义
                message.additional_kwargs[field] = (
                    str(message.additional_kwargs.get(field) or "") + value
                )
                break
        return generation_chunk
