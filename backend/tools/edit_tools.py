"""增量编辑工具 file_edit（FINAL_DEVELOPMENT_DOC 第六章）。

与 file_write 的区别：file_write 是整份覆盖，file_edit 只替换指定片段，
更适合「改几行代码」这类场景，避免模型重写整个文件导致内容漂移。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from backend.tools.tool_hook import ToolValidationError, ensure_writable_file


def _read_text(path: Path) -> str:
    """与 file_tools 保持一致的解码策略：utf-8-sig → gbk → 替换兜底。"""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


@tool
async def file_edit(
    file_path: str, old_text: str, new_text: str, replace_all: bool = False
) -> str:
    """对授权目录内的文本文件做精确片段替换（增量修改，不是整份覆盖）。

    参数:
        file_path: 目标文件绝对路径（必须位于目录白名单内）
        old_text: 要被替换的原文片段，必须与文件内容完全一致（含缩进与换行）
        new_text: 替换后的新片段；留空表示删除该片段
        replace_all: 是否替换全部匹配项，默认只替换第一处

    返回替换位置与行号；old_text 未命中会直接报错，不做模糊匹配。
    """
    if not old_text:
        return "编辑失败：old_text 不能为空，请把要替换的原文片段完整传入。"

    try:
        path = await ensure_writable_file(file_path)
    except ToolValidationError as exc:
        return f"编辑失败：{exc}"

    if not path.exists():
        return f"编辑失败：文件不存在（新建请用 file_write）：{path}"

    try:
        original = _read_text(path)
    except OSError as exc:
        return f"编辑失败：{exc}"

    hits = original.count(old_text)
    if hits == 0:
        return (
            f"编辑失败：文件中未找到指定片段。\n"
            f"请先用 file_read 读取 {path} 确认原文（注意缩进与换行必须完全一致）。"
        )

    replaced = original.replace(old_text, new_text) if replace_all else original.replace(
        old_text, new_text, 1
    )
    target_line = _line_of(original, original.index(old_text))
    try:
        path.write_text(replaced, encoding="utf-8", newline="\n")
    except OSError as exc:
        return f"编辑失败：{exc}"

    applied = hits if replace_all else 1
    delta = len(replaced) - len(original)
    return (
        f"【文件】{path}\n"
        f"【替换】{applied} 处（共命中 {hits} 处），起始行 {target_line}\n"
        f"【变化】{len(original)} → {len(replaced)} 字符（{delta:+d}）"
    )
