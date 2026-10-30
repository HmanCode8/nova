"""自主模式自测：免确认策略 / 命令执行 / 删除 / 模型档案（不落真实数据库）。

运行（PowerShell）：
    cd e:/nova-secretary
    $env:PYTHONPATH = "e:/nova-secretary"
    backend/.venv/Scripts/python.exe -m backend.tools.selftest_autonomy
"""

from __future__ import annotations

import asyncio
import copy
import os
import tempfile
from pathlib import Path
from typing import Any

_ENV_DIR = tempfile.mkdtemp(prefix="ns_env_")
os.environ["NOVA_ENV_FILE"] = str(Path(_ENV_DIR) / ".env")
os.environ.setdefault("LLM_API_KEY", "sk-test-placeholder")

import backend.storage.config_store as config_store  # noqa: E402
from backend.tools.tool_hook import (  # noqa: E402
    ToolValidationError,
    autonomy_enabled,
    ensure_deletable_path,
    ensure_path_allowed,
    is_dangerous_command,
    needs_confirmation,
)

CONFIG: dict[str, Any] = copy.deepcopy(config_store.DEFAULT_CONFIG)


async def fake_get_config() -> dict[str, Any]:
    return copy.deepcopy(CONFIG)


async def fake_save_config(patch: dict[str, Any]) -> dict[str, Any]:
    _merge(CONFIG, patch)
    return copy.deepcopy(CONFIG)


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


config_store.get_config = fake_get_config
config_store.save_config = fake_save_config

from backend.agent import model_profiles  # noqa: E402
from backend.storage.db import APP_DATA_DIR  # noqa: E402
from backend.tools import shell_tool  # noqa: E402
from backend.tools.delete_tool import delete_file  # noqa: E402
from backend.tools.shell_tool import run_shell  # noqa: E402


async def main() -> None:
    # model_profiles / shell_tool 里的 get_config 是模块级引用，需要同样替换
    model_profiles.get_config = fake_get_config
    model_profiles.save_config = fake_save_config
    model_profiles.env_file_path = lambda: Path(os.environ["NOVA_ENV_FILE"])
    shell_tool.get_config = fake_get_config

    # 1. 默认自主模式：写文件 / 发邮件 / 建日程免确认，删除仍确认
    assert await autonomy_enabled() is True
    assert await needs_confirmation("write_file", {"file_path": "x"}) is False
    assert await needs_confirmation("write_project_files", {}) is False
    assert await needs_confirmation("email_send", {}) is False
    assert await needs_confirmation("delete_file", {"path": "x"}) is True
    print("[PASS] 1. 自主模式下除删除外均免确认")

    # 2. 破坏性命令降级确认
    assert is_dangerous_command("rm -rf /tmp/x") is True
    assert is_dangerous_command("Remove-Item -Recurse -Force C:/x") is True
    assert is_dangerous_command("format c:") is True
    assert is_dangerous_command("echo hello") is False
    assert await needs_confirmation("run_shell", {"command": "echo hello"}) is False
    assert await needs_confirmation("run_shell", {"command": "del /s /q C:/x"}) is True
    print("[PASS] 2. 普通命令免确认，破坏性命令转人工确认")

    # 3. 白名单兜底：自主模式开启时仍然必须校验（FINAL_DEVELOPMENT_DOC 第二章）
    allowed_dir = Path(tempfile.mkdtemp(prefix="ns_allowed_"))
    CONFIG["allowed_dirs"] = [str(allowed_dir)]
    outside = Path(tempfile.mkdtemp(prefix="ns_outside_"))
    assert (await ensure_path_allowed(str(allowed_dir), must_exist=True)).exists()
    try:
        await ensure_path_allowed(str(outside), must_exist=True)
        raise AssertionError("白名单外路径应被拒绝")
    except ToolValidationError as exc:
        assert "不在授权目录内" in str(exc), exc
    print("[PASS] 3. 自主模式下白名单依然生效（白名单外拒绝）")

    # 4. run_shell 真实执行
    result = await run_shell.ainvoke({"command": "echo nova-ok"})
    assert "nova-ok" in result and '"exit_code": 0' in result, result
    print("[PASS] 4. run_shell 正常执行并返回结构化输出")

    # 5. delete_file 删除白名单内临时文件；受保护目录只做校验（不真删）
    victim = allowed_dir / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    out = await delete_file.ainvoke({"path": str(victim)})
    assert not victim.exists() and "已删除文件" in out, out
    try:
        await ensure_deletable_path(str(APP_DATA_DIR))
        raise AssertionError("应用数据目录应被禁止删除")
    except ToolValidationError as exc:
        assert "不在授权目录内" in str(exc) or "禁止删除" in str(exc), exc
    print("[PASS] 5. delete_file 正常删除，受保护路径被拒绝")

    # 6. 关闭自主模式 → 恢复逐步确认（白名单行为保持不变）
    CONFIG["autonomy_mode"] = False
    assert await autonomy_enabled() is False
    assert await needs_confirmation("write_file", {"file_path": "x"}) is True
    try:
        await ensure_path_allowed(str(outside), must_exist=True)
        raise AssertionError("白名单外路径始终应被拒绝")
    except ToolValidationError:
        pass
    CONFIG["autonomy_mode"] = True
    print("[PASS] 6. 关闭自主模式后恢复逐步确认")

    # 7. 模型档案：迁移 / 新增 / 激活 / 写密钥 / 删除
    data = await model_profiles.list_profiles()
    assert len(data["profiles"]) == 1 and data["active_id"] == "default", data
    data = await model_profiles.upsert_profile(
        {
            "id": "p2",
            "name": "备用模型",
            "base_url": "https://api.deepseek.com/v1",
            "model_name": "deepseek-chat",
            "api_key_env": "LLM_API_KEY__p2",
        }
    )
    assert len(data["profiles"]) == 2
    data = await model_profiles.activate_profile("p2")
    assert data["active_id"] == "p2" and CONFIG["active_model_id"] == "p2"
    await model_profiles.set_profile_key("p2", "sk-p2")
    assert "LLM_API_KEY__p2=sk-p2" in Path(os.environ["NOVA_ENV_FILE"]).read_text(
        encoding="utf-8"
    )
    data = await model_profiles.list_profiles()
    active = next(p for p in data["profiles"] if p["id"] == "p2")
    assert active["has_key"] is True
    data = await model_profiles.delete_profile("p2")
    assert data["active_id"] == "default" and len(data["profiles"]) == 1
    print("[PASS] 7. 模型档案增删改切换 + 密钥只写 .env")

    print("\n自主模式全部自测通过")


if __name__ == "__main__":
    asyncio.run(main())
