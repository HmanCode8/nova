"""Agent 工具层入口：工具注册表。

命名规范（FINAL_DEVELOPMENT_DOC 第六章）：对外统一使用文档规定的工具名
（file_read / file_write / file_edit / file_open / file_delete / image_ocr / image_vl /
screen_capture / tavily_search / clipboard_read / shell_run / present）。

历史工具名保留在 ``get_tool_map()`` 里作为别名，保证旧会话记录仍可执行；
绑定给模型的只有 ``get_all_tools()`` 里的规范名字，避免同一个能力出现两次。
"""

from __future__ import annotations

from typing import Any

from backend.tools.clipboard_tools import clipboard_read, clipboard_write
from backend.tools.delete_tool import delete_file
from backend.tools.delivery_tools import present
from backend.tools.edit_tools import file_edit
from backend.tools.file_tools import list_dir, open_local_file, read_file, write_file
from backend.tools.image_gen_tool import generate_image
from backend.tools.image_show_tool import show_image
from backend.tools.image_vl import image_vl
from backend.tools.mcp_tools import (
    calendar_create,
    calendar_list_today,
    email_list_today,
    email_read_detail,
    email_send,
)
from backend.tools.memory_tools import (
    add_global_memory,
    add_session_memory,
    delete_global_memory,
    delete_session_memory,
)
from backend.tools.project_tools import plan_project, update_project_step, write_project_files
from backend.tools.runtime_tools import start_background_task
from backend.tools.screenshot_tools import ocr_image, take_screenshot
from backend.tools.session_tools import create_new_session, summarize_context
from backend.tools.shell_tool import run_shell
from backend.tools.tavily_search_tool import tavily_web_search
from backend.tools.tool_hook import LEGACY_TOOL_NAMES
from backend.tools.upload_tools import list_uploaded_files, read_uploaded_file

# 旧实现里的函数名 → 文档规定的工具名
_NAME_MAP: dict[str, str] = {old: new for old, new in LEGACY_TOOL_NAMES.items()}


def _rename(tool: Any, name: str) -> Any:
    """复制一个工具并改名为规范名（保留描述与参数 schema）。"""
    try:
        return tool.model_copy(update={"name": name})
    except Exception:  # 极旧版本 langchain-core 的兜底
        from langchain_core.tools import StructuredTool

        return StructuredTool.from_function(
            coroutine=getattr(tool, "coroutine", None),
            func=getattr(tool, "func", None),
            name=name,
            description=tool.description,
            args_schema=getattr(tool, "args_schema", None),
        )


def _canonical(tool: Any) -> Any:
    target = _NAME_MAP.get(tool.name)
    return _rename(tool, target) if target else tool


_RAW_TOOLS: list[Any] = [
    read_file,
    write_file,
    file_edit,
    list_dir,
    open_local_file,
    delete_file,
    run_shell,
    clipboard_read,
    clipboard_write,
    take_screenshot,
    ocr_image,
    image_vl,
    generate_image,
    show_image,
    tavily_web_search,
    present,
    start_background_task,
    add_session_memory,
    delete_session_memory,
    add_global_memory,
    delete_global_memory,
    summarize_context,
    create_new_session,
    list_uploaded_files,
    read_uploaded_file,
    plan_project,
    update_project_step,
    write_project_files,
    email_list_today,
    email_read_detail,
    calendar_list_today,
    email_send,
    calendar_create,
]


def get_all_tools() -> list[Any]:
    """返回绑定给模型的工具（规范命名）。"""
    return [_canonical(tool) for tool in _RAW_TOOLS]


def get_tool_map() -> dict[str, Any]:
    """执行期工具表：规范名 + 旧名别名，保证历史调用仍可执行。"""
    tools = get_all_tools()
    mapping: dict[str, Any] = {tool.name: tool for tool in tools}
    for tool in tools:
        for old, new in _NAME_MAP.items():
            if new == tool.name:
                mapping.setdefault(old, tool)
    return mapping


async def get_agent_tools() -> list[Any]:
    """绑定给模型的完整能力集：内置工具 + 已激活的 MCP 工具。"""
    tools = get_all_tools()
    try:
        from backend.mcp_manager import get_manager  # 延迟导入避免循环依赖

        tools.extend(await get_manager().build_tools())
    except Exception:  # MCP 不可用不影响内置工具
        pass
    return tools
