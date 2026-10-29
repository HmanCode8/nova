"""M2 自测脚本：文件工具 + 路径白名单 / 可执行后缀黑名单 / 人工确认链路。

运行：
    cd e:\nova-secretary
    $env:PYTHONPATH = "e:\nova-secretary"
    uv run --project backend python -m backend.tools.selftest_file_tools

注意：会临时改写 app_config.allowed_dirs，结束时恢复原值。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from backend.agent.agent_graph import build_agent, extract_interrupt, thread_config
from backend.agent.selftest_agent_graph import ScriptedChatModel
from backend.storage.config_store import get_config, save_config
from backend.storage.db import db
from backend.tools import get_all_tools
from backend.tools.file_tools import list_dir, open_local_file, read_file, write_file


async def case_read_and_guard(allowed: Path, outside: Path) -> None:
    sample = allowed / "样例.txt"
    sample.write_text("第一行\n第二行\n", encoding="utf-8")

    text = await read_file.ainvoke({"file_path": str(sample)})
    assert "第一行" in text and "第二行" in text, text
    print("[PASS] 1. 白名单内读取成功")

    blocked = await read_file.ainvoke({"file_path": str(outside / "secret.txt")})
    assert "不在授权目录内" in blocked, blocked
    print("[PASS] 2. 白名单外读取被拒")

    relative = await read_file.ainvoke({"file_path": "backend/server.py"})
    assert "请使用绝对路径" in relative, relative
    print("[PASS] 3. 相对路径被拒")

    gbk_file = allowed / "gbk.txt"
    gbk_file.write_bytes("中文编码测试".encode("gbk"))
    gbk_text = await read_file.ainvoke({"file_path": str(gbk_file)})
    assert "中文编码测试" in gbk_text, gbk_text
    print("[PASS] 4. GBK 文本可读")


async def case_write(allowed: Path) -> None:
    target = allowed / "输出.md"
    result = await write_file.ainvoke({"file_path": str(target), "content": "# 标题\n正文"})
    assert "已写入文件" in result and target.exists()
    assert target.read_text(encoding="utf-8") == "# 标题\n正文"
    print("[PASS] 5. 白名单内写入成功")

    blocked = await write_file.ainvoke(
        {"file_path": str(allowed / "run.ps1"), "content": "echo hack"}
    )
    assert "禁止写入可执行文件后缀" in blocked, blocked
    print("[PASS] 6. 可执行后缀写入被拒")

    missing_dir = await write_file.ainvoke(
        {"file_path": str(allowed / "不存在目录" / "a.md"), "content": "x"}
    )
    assert "目标目录不存在" in missing_dir, missing_dir
    print("[PASS] 7. 父目录不存在被拒")


async def case_list_and_open(allowed: Path) -> None:
    listing = await list_dir.ainvoke({"dir_path": str(allowed)})
    assert "输出.md" in listing and "[FILE]" in listing, listing
    print("[PASS] 8. list_dir 输出正常")

    exe = allowed / "fake.exe"
    exe.write_bytes(b"MZ")
    opened = await open_local_file.ainvoke({"file_path": str(exe)})
    assert "禁止打开可执行文件" in opened, opened
    print("[PASS] 9. open_local_file 拦截可执行后缀")


async def case_empty_whitelist(original_dirs: list[str]) -> None:
    await save_config({"allowed_dirs": []})
    result = await read_file.ainvoke({"file_path": "C:\\Windows\\win.ini"})
    assert "目录白名单为空" in result, result
    await save_config({"allowed_dirs": original_dirs})
    print("[PASS] 10. 空白名单时拒绝访问")


async def case_graph_confirm_flow(allowed: Path) -> None:
    target = allowed / "graph-confirm.txt"
    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"file_path": str(target), "content": "graph"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="已写入。"),
        ]
    )
    graph = build_agent(model, tools=get_all_tools())
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="写个文件")], "session_id": "m2-graph"},
        config=thread_config("m2-graph"),
    )
    payload = extract_interrupt(result)
    assert payload and payload["action"] == "write_file", result
    assert not target.exists(), "确认前不应写入"
    print(f"[PASS] 11. 图内确认载荷：{payload['preview_text']}")

    result = await graph.ainvoke(
        Command(resume={"accepted": True}), config=thread_config("m2-graph")
    )
    assert target.read_text(encoding="utf-8") == "graph"
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages and "已写入文件" in tool_messages[-1].content
    print("[PASS] 12. 确认后工具真实落盘，结果回到 Agent")


async def case_graph_blocked_flow(outside: Path) -> None:
    """硬校验失败必须直接拒绝，不弹人工确认。"""
    target = outside / "blocked.txt"
    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"file_path": str(target), "content": "x"},
                        "id": "call_blocked",
                    }
                ],
            ),
            AIMessage(content="该路径未授权，无法写入。"),
        ]
    )
    graph = build_agent(model, tools=get_all_tools())
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="写到白名单外")], "session_id": "m2-blocked"},
        config=thread_config("m2-blocked"),
    )
    assert extract_interrupt(result) is None, "硬校验失败不应弹确认卡片"
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages and "不在授权目录内" in tool_messages[-1].content, tool_messages
    assert not target.exists()
    print("[PASS] 13. 硬校验失败直接拒绝，不弹确认")


async def main() -> None:
    original = await get_config()
    allowed = Path(tempfile.mkdtemp(prefix="ns_m2_allowed_"))
    outside = Path(tempfile.mkdtemp(prefix="ns_m2_outside_"))
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    await save_config({"allowed_dirs": [str(allowed)]})
    try:
        await case_read_and_guard(allowed, outside)
        await case_write(allowed)
        await case_list_and_open(allowed)
        await case_empty_whitelist(list(original.get("allowed_dirs") or []))
        await save_config({"allowed_dirs": [str(allowed)]})
        await case_graph_confirm_flow(allowed)
        await case_graph_blocked_flow(outside)
    finally:
        await save_config({"allowed_dirs": list(original.get("allowed_dirs") or [])})
        await db.close()

    print("\nM2 全部自测通过")


if __name__ == "__main__":
    asyncio.run(main())
