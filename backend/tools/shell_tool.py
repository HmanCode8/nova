"""命令执行工具：run_shell。

定位：本地智能体的“手”，用于安装依赖、跑脚本、编译、验证生成的项目。
安全策略（见 tool_hook）：
- 自主模式（autonomy_mode）下默认不弹确认，可直接执行
- 命中破坏性命令（rm -rf / format / del /s / shutdown 等）自动降级为人工确认
- 输出截断 + 超时强杀，避免把大段日志塞进上下文

跨平台差异：
- Windows 走 PowerShell（powershell.exe -NoProfile -NonInteractive），
  先强制控制台 UTF-8，否则中文输出会是 GBK 乱码
- macOS/Linux 走 /bin/bash -lc，继承用户 shell 环境变量
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from backend.storage.config_store import get_config

MAX_OUTPUT_CHARS = 12000
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n...[输出过长，已省略中间部分]...\n{text[-half:]}"


@tool
async def run_shell(command: str, cwd: str = "", timeout: int = DEFAULT_TIMEOUT) -> str:
    """在本机执行 shell 命令并返回输出（可安装依赖、跑脚本、编译项目、查看系统信息）。

    参数:
        command: 要执行的命令，例如 `npm install`、`python -m pytest -q`
        cwd: 工作目录绝对路径；为空则使用后端进程当前目录
        timeout: 超时秒数（1~600），超时会强制终止
    """
    config = await get_config()
    if not bool(config.get("shell_enabled", True)):
        return "命令执行已被关闭：请在设置面板开启“允许执行命令”。"

    text = str(command or "").strip()
    if not text:
        return "执行失败：命令不能为空。"

    workdir = str(cwd or "").strip()
    if workdir:
        target = Path(workdir).expanduser()
        if not target.is_dir():
            return f"执行失败：工作目录不存在：{target}"
        workdir_path = str(target)
    else:
        workdir_path = str(Path.cwd())

    wait = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))

    if sys.platform == "win32":
        argv = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; {text}",
        ]
        shell = False
    else:
        argv = ["/bin/bash", "-lc", text]
        shell = False

    try:
        completed = subprocess.run(
            argv,
            cwd=workdir_path,
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=wait,
        )
    except subprocess.TimeoutExpired:
        return f"命令执行超时（超过 {wait} 秒已强制终止）：{text}"
    except OSError as exc:
        return f"命令执行失败：{exc}"

    stdout = _truncate(completed.stdout.strip())
    stderr = _truncate(completed.stderr.strip())
    payload = {
        "command": text,
        "cwd": workdir_path,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    return json.dumps(payload, ensure_ascii=False)
