"""MCP 工具 → LangChain BaseTool 适配器（FINAL_DEVELOPMENT_DOC 第七章）。

- 每个 MCP 工具包装成一个 StructuredTool，名字加 ``mcp_<服务>_<工具>`` 前缀避免与内置工具冲突
- 工具返回原始文本/资源路径，不做任何解析（文档约定：解析交给内置工具）
- 所有 MCP 工具与内置工具一样经过 Middleware（白名单校验、Trace 埋点、删除拦截）
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field, create_model

_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")

TYPE_MAP = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def safe_name(value: str, limit: int = 40) -> str:
    text = _SAFE.sub("_", value or "").strip("_")
    return text[:limit] or "tool"


def _build_args_schema(tool_name: str, schema: dict[str, Any]) -> Optional[type]:
    """把 MCP 的 inputSchema（JSON Schema）转成 pydantic 模型，供模型正确填参。"""
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return None
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for key, prop in properties.items():
        prop = prop if isinstance(prop, dict) else {}
        py_type = TYPE_MAP.get(str(prop.get("type") or "string"), str)
        description = str(prop.get("description") or "")
        if key in required:
            fields[key] = (py_type, Field(..., description=description))
        else:
            fields[key] = (Optional[py_type], Field(default=None, description=description))
    try:
        return create_model(f"MCPArgs_{safe_name(tool_name)}", **fields)
    except Exception:
        return None


def build_mcp_tool(
    server_id: str,
    server_name: str,
    tool_def: dict[str, Any],
    caller: Callable[[str, dict[str, Any]], Any],
) -> Optional[BaseTool]:
    """把一个 MCP 工具定义包装成 StructuredTool。"""
    raw_name = str(tool_def.get("name") or "").strip()
    if not raw_name:
        return None
    model_name = f"mcp_{safe_name(server_id, 16)}_{safe_name(raw_name)}"
    description = str(tool_def.get("description") or "").strip()
    head = f"[MCP {server_name}] "
    body = description or f"调用 {server_name} 提供的 {raw_name} 工具"
    args_schema = _build_args_schema(model_name, tool_def.get("inputSchema") or {})

    async def _run(**kwargs: Any) -> str:
        arguments = {key: value for key, value in kwargs.items() if value is not None}
        return await caller(raw_name, arguments)

    try:
        return StructuredTool.from_function(
            coroutine=_run,
            name=model_name,
            description=(head + body)[:1000],
            args_schema=args_schema,
        )
    except Exception:
        return None
