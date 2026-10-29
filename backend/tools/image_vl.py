"""看图理解工具 image_vl：对接多模态视觉模型（与 OCR 链路完全隔离）。

适用：描述画面、解析 UI 布局、流程图、图表、草图、界面截图。
不适用：纯文字提取 —— 那类请求应调用 ocr_image。

安全：
- 图片准入复用 image_source（仅上传目录 / 截图目录 / 授权目录）
- base64 只在本次调用内构造，不写日志、不入库
"""

from __future__ import annotations

from langchain_core.tools import tool

from backend.agent.vl_adapter import VLConfigError, describe_image
from backend.storage.config_store import get_config
from backend.tools.image_source import resolve_image
from backend.tools.tool_hook import ToolValidationError

MAX_VL_CHARS = 6000


@tool
async def image_vl(image: str, question: str = "") -> str:
    """看图理解（多模态视觉模型）：描述画面、解析 UI/界面布局、流程图、图表、草图。

    参数:
        image: 上传图片的 file_id，或图片绝对路径
        question: 想了解的重点；留空则做整体描述
    纯文字提取请改用 ocr_image，不要用本工具。
    """
    config = await get_config()
    if not config.get("vl_enabled"):
        return "当前已关闭视觉理解，仅支持图片 OCR 文字识别。"

    try:
        path = await resolve_image(image)
    except ToolValidationError as exc:
        return f"看图失败：{exc}"

    try:
        text = await describe_image(path, question)
    except VLConfigError as exc:
        return str(exc)
    except Exception as exc:  # 网络 / 模型异常
        return f"视觉模型调用失败：{exc}"

    if not text:
        return "视觉模型没有返回描述内容。"

    truncated = len(text) > MAX_VL_CHARS
    body = text[:MAX_VL_CHARS]
    header = f"【图片理解】{path.name}"
    if truncated:
        header += f"\n【提示】描述过长，仅保留前 {MAX_VL_CHARS} 字符"
    return f"{header}\n---\n{body}"
