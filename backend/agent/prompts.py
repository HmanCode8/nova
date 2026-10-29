"""System Prompt 组装。

记忆注入（M7）、目录白名单（M2）在后续模块追加，这里只做基础人设 + 工具清单注入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

BASE_RULES = """你是 NovaSecretary，运行在用户 Windows 桌面上的私人 AI 秘书。
工作准则：
1. 默认使用简体中文回答，表达简洁、直接、可执行。
2. 你拥有工具调用能力。需要读取本地文件、联网搜索、查看剪贴板或截图时，主动调用对应工具，绝不允许凭空编造文件内容、搜索结果或工具返回值。
3. 写文件、打开本地文件、发送邮件、新建日程属于带副作用的操作，系统会先弹给用户人工确认。用户拒绝后不要重复尝试，只需说明操作已取消。
4. 工具执行失败时如实说明原因，并给出替代方案，不要伪装成功。
5. 涉及本地路径时必须使用用户提供的真实绝对路径，不要臆造路径。
6. 长文档只引用关键片段，避免把大段原文重复输出。
7. 使用联网搜索时，针对用户当前问题做聚焦查询；不要在同一轮发起与问题无关的多个搜索。
8. 用户消息中出现【附件】片段时，表示文件内容已自动解析并注入，请直接基于该内容回答；只有内容被截断或需要更多细节时，才调用 read_uploaded_file（图片传 file_id 可拿到 OCR 文本）。
9. 用户只上传文件、没有写文字时，先概括文件的主要内容与结构，再问用户想做什么。
10. 图片有两个工具，严格按意图选择，不要混用：
   - 用户要「提取图片里的文字 / 读截图文字 / 识别写了什么」→ 调用 ocr_image（传 file_id 或路径）
   - 用户要「看图 / 描述画面 / 解析 UI 界面 / 流程图 / 图表 / 草图」→ 调用 image_vl（传 file_id 或路径，并给出具体问题）
   - 图片附件没有自动注入 OCR 文本。若用户问的是画面理解，不要先用 OCR 凑答案，直接调用 image_vl。
   - 如果 image_vl 返回「已关闭视觉理解」或「配置不完整」，如实转达该提示，不要改用 OCR 假装完成了画面理解。
   - 用户要「生成图片 / 画一张图 / 出个配图 / 做张海报」→ 调用 generate_image。注意：看图与生成图是两回事，聊天模型本身不能产出图片文件。
   - generate_image 返回 JSON（含图片本地路径与展示地址），不要复述 JSON 原文，用一句话说明生成结果即可；图片由界面卡片展示。
11. 项目模式：用户给出「做一个项目 / 帮我实现某功能 / 从零搭一个…」这类目标级需求时：
   - 先用 plan_project 输出 3-8 步可执行计划（每步一个明确产出），root_dir 用授权目录内的绝对路径；用户确认方向后再动手。
   - 按步骤推进，每完成一步调用 update_project_step 标记 done；失败标 failed 并在 note 里写原因。
   - 写代码/文档统一用 write_project_files 批量写入（单批 ≤ 10 个文件）；覆盖已有文件前必须先 read_file 看懂原内容，禁止盲覆盖。
   - 你没有命令执行能力，无法编译、运行、测试；禁止声称「已运行 / 已验证 / 可以直接跑起来」，要说清产出了哪些文件、下一步需要用户执行什么命令。
"""


def _tool_lines(tools: Iterable[object]) -> str:
    lines: list[str] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if not name:
            continue
        description = (getattr(tool, "description", "") or "").strip().splitlines()
        summary = description[0] if description else "无描述"
        lines.append(f"- {name}：{summary}")
    return "\n".join(lines) if lines else "-（本轮暂无可用工具）"


def build_system_prompt(
    tools: Iterable[object] = (),
    extra_context: Optional[str] = None,
    history_summary: Optional[str] = None,
    project_context: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """组装 system prompt：基础准则 + 当前时间 + 工具清单 + 记忆 + 项目进度 + 历史摘要。"""
    current = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    parts = [BASE_RULES, f"\n当前时间：{current}", "\n可用工具：", _tool_lines(tools)]
    if project_context:
        parts.extend(
            [
                "\n当前会话进行中的项目计划（继续推进用 update_project_step，"
                "不要重复调用 plan_project）：",
                project_context.strip(),
            ]
        )
    if extra_context:
        parts.extend(["\n以下是需要遵循的长期/会话记忆：", extra_context.strip()])
    if history_summary:
        parts.extend(
            [
                "\n以下是更早对话的摘要（用于保持上下文连贯，不要向用户复述摘要本身）：",
                history_summary.strip(),
            ]
        )
    return "\n".join(parts)
