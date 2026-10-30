"""v2 地基自测（纯逻辑部分，不依赖数据库）。

覆盖：工具规范命名、旧名别名、Trace 主键确定性、file_edit / present 的参数守卫。
数据库相关链路（trace_log 落库、白名单表）由 live 集成自测覆盖，见交付说明。

运行：uv run python -m backend.tools.selftest_v2_middleware
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.storage import trace_store  # noqa: E402
from backend.tools import get_all_tools, get_tool_map  # noqa: E402
from backend.tools.delivery_tools import present  # noqa: E402
from backend.tools.edit_tools import file_edit  # noqa: E402
from backend.tools.tool_hook import (  # noqa: E402
    ALWAYS_CONFIRM_TOOLS,
    LEGACY_TOOL_NAMES,
    canonical_tool_name,
    needs_confirmation,
)


def case_tool_names() -> None:
    tools = get_all_tools()
    names = {tool.name for tool in tools}
    expected = {
        "file_read",
        "file_write",
        "file_edit",
        "file_open",
        "file_delete",
        "image_ocr",
        "image_vl",
        "screen_capture",
        "tavily_search",
        "clipboard_read",
        "shell_run",
        "present",
    }
    missing = expected - names
    assert not missing, f"缺少文档规定的工具：{missing}"
    assert len(names) == len(tools), f"工具名重复：{[t.name for t in tools]}"
    for legacy in LEGACY_TOOL_NAMES:
        assert legacy not in names, f"旧工具名不应再暴露给模型：{legacy}"

    mapping = get_tool_map()
    for old, new in LEGACY_TOOL_NAMES.items():
        assert old in mapping, f"旧名别名缺失：{old}"
        assert mapping[old].name == new, f"别名 {old} 应指向 {new}"
    print("[PASS] 1. 工具规范命名 + 旧名别名兼容")


def case_canonical_policy() -> None:
    assert canonical_tool_name("delete_file") == "file_delete"
    assert canonical_tool_name("run_shell") == "shell_run"
    assert canonical_tool_name("file_read") == "file_read"
    assert ALWAYS_CONFIRM_TOOLS == {"file_delete"}, ALWAYS_CONFIRM_TOOLS
    print("[PASS] 2. 中间件按规范名判定策略（删除唯一强制确认）")


async def case_confirmation_policy() -> None:
    # 删除：任何模式下都必须确认（新旧名字都要命中）
    assert await needs_confirmation("file_delete", {"path": "D:/x"}) is True
    assert await needs_confirmation("delete_file", {"path": "D:/x"}) is True
    print("[PASS] 3. 删除操作强制人工确认（新旧工具名一致）")


def case_trace_identity() -> None:
    first = trace_store.trace_id_for("s1", "call-1")
    second = trace_store.trace_id_for("s1", "call-1")
    other = trace_store.trace_id_for("s1", "call-2")
    assert first == second, "同一调用必须生成同一个 trace id（gate 重放幂等）"
    assert first != other
    assert trace_store.STATUS_WAITING == "waiting_confirm"
    assert trace_store.STATUS_CONFIRMED == "confirmed"
    assert trace_store.STATUS_CANCELLED == "cancelled"
    print("[PASS] 4. Trace 主键幂等 + 删除确认状态常量")


async def case_argument_guards() -> None:
    out = await file_edit.ainvoke({"file_path": "", "old_text": "", "new_text": "x"})
    assert "old_text 不能为空" in out, out

    out = await present.ainvoke({"paths": []})
    assert "paths 不能为空" in out, out

    out = await present.ainvoke({"paths": [str(Path("x") / f"f{i}.txt") for i in range(60)]})
    assert "最多 50" in out, out
    print("[PASS] 5. file_edit / present 参数守卫")


async def main() -> None:
    case_tool_names()
    case_canonical_policy()
    await case_confirmation_policy()
    case_trace_identity()
    await case_argument_guards()
    print("\nv2 地基自测（纯逻辑）全部通过")


if __name__ == "__main__":
    asyncio.run(main())
