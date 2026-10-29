"""Agent 工具层入口：工具注册表。

新增工具只需在这里注册，agent_graph 通过 get_all_tools() 统一加载。
"""

from __future__ import annotations

from typing import Any

from backend.tools.clipboard_tools import clipboard_read, clipboard_write
from backend.tools.file_tools import list_dir, open_local_file, read_file, write_file
from backend.tools.image_gen_tool import generate_image
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
from backend.tools.screenshot_tools import ocr_image, take_screenshot
from backend.tools.session_tools import create_new_session, summarize_context
from backend.tools.tavily_search_tool import tavily_web_search
from backend.tools.upload_tools import list_uploaded_files, read_uploaded_file


def get_all_tools() -> list[Any]:
    """返回当前阶段全部可用工具。"""
    return [
        read_file,
        write_file,
        list_dir,
        open_local_file,
        clipboard_read,
        clipboard_write,
        take_screenshot,
        ocr_image,
        image_vl,
        generate_image,
        tavily_web_search,
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
