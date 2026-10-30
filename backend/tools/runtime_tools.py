"""后台长任务工具（FINAL_DEVELOPMENT_DOC 第八章「深度任务」）。

Agent 判断需求属于调研 / 开发 / 设计这类长任务时，调用本工具把任务交给 Runtime 层，
由 Runtime 在独立上下文里继续执行，主对话立刻返回，不阻塞用户。
"""

from __future__ import annotations

from langchain_core.tools import tool

from backend.storage.memory_store import CURRENT_SESSION


@tool
async def start_background_task(prompt: str, title: str = "") -> str:
    """把耗时的深度任务转到后台执行（调研、批量开发、方案设计等）。

    参数:
        prompt: 完整任务描述，要能独立执行（后台看不到当前对话上下文，请把必要背景写全）
        title: 任务标题，简短可读，用于任务卡片展示

    适用场景：多轮工具调用才能完成的任务。简单的单步问题不要用本工具，直接回答即可。
    """
    from backend.runtime.task_runtime import get_runtime

    session_id = CURRENT_SESSION.get()
    if not session_id:
        return "创建任务失败：缺少会话上下文，请重试。"

    runtime = get_runtime()
    if runtime is None:
        return "创建任务失败：任务运行时未就绪，请重启后端。"

    text = (prompt or "").strip()
    if not text:
        return "创建任务失败：任务描述为空。"

    try:
        task = await runtime.submit(session_id, text, (title or "").strip())
    except ValueError as exc:
        return f"创建任务失败：{exc}"

    return (
        f"已在后台启动任务：{task.get('title') or '未命名任务'}\n"
        f"task_id: {task['id']}\n"
        "执行过程会实时输出到任务卡片，用户可以随时停止。"
        "请告诉用户任务已在后台运行，不要在这里等待结果。"
    )
