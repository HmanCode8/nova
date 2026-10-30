"""删除工具：delete_file。

唯一在自主模式下仍强制人工确认的工具（用户明确要求）。
- 文件：直接 unlink
- 目录：必须显式 recursive=True，否则拒绝（避免误删整棵目录）
- 系统关键目录、盘符根目录、应用数据目录由 tool_hook 拦截
"""

from __future__ import annotations

import shutil

from langchain_core.tools import tool

from backend.tools.tool_hook import ToolValidationError, ensure_deletable_path


@tool
async def delete_file(path: str, recursive: bool = False) -> str:
    """永久删除本地文件或目录（执行前会弹人工确认，删除后无法恢复）。

    参数:
        path: 要删除的绝对路径
        recursive: 删除目录时必须传 true（递归删除目录内全部内容），删文件保持 false
    """
    try:
        target = await ensure_deletable_path(path)
    except ToolValidationError as exc:
        return f"删除失败：{exc}"

    if target.is_dir():
        if not recursive:
            return f"删除失败：{target} 是目录，确认要删除请传 recursive=true"
        try:
            shutil.rmtree(target)
        except OSError as exc:
            return f"删除失败：{exc}"
        return f"已删除目录：{target}"

    try:
        target.unlink()
    except OSError as exc:
        return f"删除失败：{exc}"
    return f"已删除文件：{target}"
