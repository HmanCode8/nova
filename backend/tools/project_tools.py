"""项目模式工具：目标 → 计划 → 批量写文件 → 步骤进度。

边界（方案 A）：
- 只做计划编排与文件产出，不执行命令、不跑测试
- 自主模式下批量写文件直接执行；关闭自主模式时由 gate 节点 interrupt 确认
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from backend.storage import project_store
from backend.storage.memory_store import CURRENT_SESSION
from backend.tools.tool_hook import (
    ToolValidationError,
    ensure_path_allowed,
    ensure_project_batch,
)


@tool
async def plan_project(
    title: str, goal: str, root_dir: str, steps: list[str], reset: bool = False
) -> str:
    """创建项目任务计划（项目模式第一步）：把目标拆成可执行步骤并展示进度看板。

    参数:
        title: 项目名称，简短可读
        goal: 用户的目标原话或一句话概括
        root_dir: 项目根目录绝对路径（必须在授权目录内，可尚不存在，写入时自动创建）
        steps: 步骤描述列表，3-8 步，每步一个明确产出
        reset: 仅当用户明确要求重做计划时传 true；默认 false 会复用进行中的计划
    """
    session_id = CURRENT_SESSION.get()
    if not session_id:
        return "创建项目计划失败：缺少会话上下文，请重试。"

    try:
        root = await ensure_path_allowed(root_dir)
        if root.is_file():
            raise ToolValidationError(f"项目根目录不能是文件：{root}")
    except ToolValidationError as exc:
        return f"创建项目计划失败：{exc}"

    clean_steps = [str(item).strip() for item in steps if str(item).strip()]
    if not clean_steps:
        return "创建项目计划失败：steps 不能为空。"

    # 已有进行中的计划时默认复用，避免每轮重复建计划、旧进度被归档
    if not reset:
        existing = await project_store.get_latest_plan(session_id)
        if (
            existing
            and existing.get("status") == "active"
            and existing.get("done", 0) < existing.get("total", 0)
        ):
            return (
                f"当前已有进行中的项目计划《{existing.get('title')}》"
                f"（{existing.get('done')}/{existing.get('total')} 步完成），未重复创建。"
                "请直接用 update_project_step 继续推进；只有用户明确要求重做计划时才传 reset=true。"
            )

    snapshot = await project_store.create_plan(
        session_id=session_id,
        title=title.strip() or "未命名项目",
        goal=goal.strip(),
        root_dir=str(root),
        steps=clean_steps,
    )
    return json.dumps(snapshot, ensure_ascii=False)


@tool
async def update_project_step(step: int, status: str, note: str = "") -> str:
    """更新项目步骤状态，让看板显示进度。

    参数:
        step: 步骤序号（从 0 开始，与 plan_project 的 steps 顺序一致）
        status: pending / done / failed / skipped
        note: 可选备注（失败原因、产出文件等，200 字以内）
    """
    session_id = CURRENT_SESSION.get()
    if not session_id:
        return "更新步骤失败：缺少会话上下文，请重试。"

    snapshot, error = await project_store.update_step(session_id, step, status, note)
    if snapshot is None:
        return f"更新步骤失败：{error}"
    return json.dumps(snapshot, ensure_ascii=False)


@tool
async def write_project_files(root_dir: str, files: list[dict[str, str]]) -> str:
    """批量写入项目文件（自主模式直接写入；关闭自主模式需确认后整批写入；自动创建父目录）。

    参数:
        root_dir: 项目根目录绝对路径（必须在授权目录内）
        files: 文件列表，每项 {"path": 相对或绝对路径, "content": 完整文本}
               相对路径按 root_dir 拼接；单批最多 10 个文件 / 20 万字符
    """
    try:
        root, items = await ensure_project_batch(root_dir, files)
    except ToolValidationError as exc:
        return f"写入失败：{exc}"

    lines: list[str] = [f"【项目目录】{root}"]
    written = 0
    for target, content in items:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        except OSError as exc:
            lines.append(f"[失败] {target}：{exc}")
            continue
        written += 1
        lines.append(f"[写入] {target}（{len(content)} 字符）")
    lines.append(f"共 {written}/{len(items)} 个文件写入成功")
    return "\n".join(lines)
