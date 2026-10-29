"""Tavily 联网搜索工具。

- 受设置面板「联网搜索」总开关控制，关闭时直接拒绝调用
- 密钥只读 backend/.env 的 TAVILY_API_KEY
- 返回结构化 JSON（query / answer / results[{title,url,content}]），
  后端网关会解析后向前端推送 search_results 卡片数据
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.env_loader import load_env
from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from backend.storage.config_store import get_config

load_env()

MAX_RESULTS = 8
SNIPPET_CHARS = 800


def _api_key() -> str:
    return (os.getenv("TAVILY_API_KEY") or "").strip()


def _normalize(raw: Any) -> tuple[list[dict[str, str]], str | None]:
    items: list[dict[str, str]] = []
    answer: str | None = None
    if isinstance(raw, dict):
        answer = raw.get("answer") if isinstance(raw.get("answer"), str) else None
        results = raw.get("results") or []
    elif isinstance(raw, list):
        results = raw
    else:
        results = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "title": str(entry.get("title") or "无标题")[:200],
                "url": str(entry.get("url") or ""),
                "content": str(entry.get("content") or "")[:SNIPPET_CHARS],
            }
        )
    return items, answer


@tool
async def tavily_web_search(query: str, max_results: int = 5) -> str:
    """联网搜索互联网实时信息、新闻、最新资料。

    用户询问时效性内容、外部资料、行业资讯时使用。
    参数:
        query: 搜索关键词或问题
        max_results: 返回条数（1~8，默认 5）
    """
    config = await get_config()
    if not config.get("web_search_enabled"):
        return "[联网搜索已关闭] 当前不允许联网查询，请在设置面板打开「联网搜索」开关。"

    api_key = _api_key()
    if not api_key:
        return "[Tavily 未配置] backend/.env 缺少 TAVILY_API_KEY，无法联网搜索。"

    try:
        limit = max(1, min(int(max_results), MAX_RESULTS))
    except (TypeError, ValueError):
        limit = 5

    try:
        searcher = TavilySearch(max_results=limit, search_depth="basic", tavily_api_key=api_key)
        raw = await searcher.ainvoke({"query": query})
    except Exception as exc:
        return f"联网搜索失败：{exc}"

    items, answer = _normalize(raw)
    if not items:
        return "搜索完成，但没有找到相关结果。"

    return json.dumps(
        {"query": query, "answer": answer, "results": items},
        ensure_ascii=False,
    )
