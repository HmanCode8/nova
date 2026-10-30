"""交付物汇总工具 present（FINAL_DEVELOPMENT_DOC 第六章）。

任务收尾时把产出文件列成清单：路径、大小、修改时间，便于用户直接查看/打开。
只做「盘点」，不读取正文，避免把大文件内容塞进上下文。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from backend.tools.tool_hook import ToolValidationError, ensure_path_allowed

MAX_ITEMS = 50


def _describe(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError as exc:
        return f"[无法读取] {path}：{exc}"
    size = stat.st_size
    if size < 1024:
        human = f"{size} B"
    elif size < 1024 * 1024:
        human = f"{size / 1024:.1f} KB"
    else:
        human = f"{size / 1024 / 1024:.1f} MB"
    updated = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    return f"[OK] {path}（{human}，修改于 {updated}）"


@tool
async def present(paths: list[str], summary: str = "") -> str:
    """汇总本次任务的产出文件清单（交付物盘点，直接执行）。

    参数:
        paths: 产出文件的绝对路径列表（必须位于目录白名单内），最多 50 个
        summary: 一句话说明这批产出是什么（可选）

    返回结构化清单：存在性、大小、修改时间；不存在或越权的路径会被单独标出。
    """
    items = [str(item).strip() for item in (paths or []) if str(item).strip()]
    if not items:
        return "汇总失败：paths 不能为空，请提供产出文件的绝对路径列表。"
    if len(items) > MAX_ITEMS:
        return f"汇总失败：单次最多 {MAX_ITEMS} 个文件（当前 {len(items)} 个），请分批汇总。"

    lines: list[str] = []
    if summary.strip():
        lines.append(f"【交付说明】{summary.strip()}")
    lines.append(f"【产出清单】共 {len(items)} 项")

    for item in items:
        try:
            path = await ensure_path_allowed(item, must_exist=True)
        except ToolValidationError as exc:
            lines.append(f"[拒绝] {item}：{exc}")
            continue
        if not path.is_file():
            lines.append(f"[跳过] {path}：不是文件")
            continue
        lines.append(_describe(path))

    return "\n".join(lines)
