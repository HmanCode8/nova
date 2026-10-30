"""把本机已有图片展示到对话里（代码绘图产物 / 截图 / 下载图片都适用）。

为什么要这一步：Agent 用 write_file + run_shell 画出的图只落在磁盘上，
前端拿不到展示地址。show_image 负责做白名单校验、复制到 generated/ 并返回
/api/generated/xxx 展示地址，前端据此内联渲染图片卡片。

安全：
- 只能展示授权目录（白名单）内的图片
- 只接受 png/jpg/jpeg/bmp/webp，拒绝其他格式
- 复制而不是移动，原文件保留；超过 20MB 拒绝
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from langchain_core.tools import tool

from backend.tools.image_gen_tool import generated_dir
from backend.tools.tool_hook import IMAGE_SUFFIXES, ensure_path_allowed

MAX_IMAGE_MB = 20


@tool
async def show_image(path: str) -> str:
    """把本机已存在的图片展示给用户（代码绘制、截图、下载的图片都可以）。

    参数:
        path: 图片的绝对路径，必须在已授权目录内
    返回 JSON（含展示地址）；不要复述 JSON 原文，用一句话说明即可，图片由界面展示。
    """
    raw = str(path or "").strip().strip('"').strip("'").strip()
    if not raw:
        return "展示图片失败：路径为空。"

    target = Path(raw).expanduser()
    if target.suffix.lower() not in IMAGE_SUFFIXES:
        return f"展示图片失败：不是支持的图片格式（{target.suffix or '无扩展名'}），只支持 png/jpg/webp/bmp。"

    try:
        resolved = await ensure_path_allowed(str(target), must_exist=True)
    except Exception as exc:  # 白名单 / 不存在等，原样回传原因
        return f"展示图片失败：{exc}"

    if not resolved.is_file():
        return f"展示图片失败：文件不存在 {resolved}"
    size = resolved.stat().st_size
    if size <= 0:
        return f"展示图片失败：文件为空 {resolved}"
    if size > MAX_IMAGE_MB * 1024 * 1024:
        return f"展示图片失败：图片超过 {MAX_IMAGE_MB}MB 上限（{size // 1024 // 1024}MB）。"

    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}{resolved.suffix.lower()}"
    copy_path = generated_dir() / name
    try:
        shutil.copyfile(resolved, copy_path)
    except OSError as exc:
        return f"展示图片失败：复制到展示目录出错（{exc}）"

    record = {
        "source": "code",
        "images": [
            {
                "name": name,
                "path": str(copy_path),
                "origin": str(resolved),
                "url": f"/api/generated/{name}",
            }
        ],
    }
    return json.dumps(record, ensure_ascii=False)
