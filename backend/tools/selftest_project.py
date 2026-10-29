"""项目模式自测：计划 → 更新步骤 → 批量写文件 → 安全拦截。

    $env:NOVA_DB_PATH = "$env:TEMP\\ns_project\\nova.db"
    uv run --project backend python -m backend.tools.selftest_project
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from backend.storage import project_store, session_store
from backend.storage.config_store import save_config
from backend.storage.db import db
from backend.storage.memory_store import CURRENT_SESSION
from backend.tools.project_tools import plan_project, update_project_step, write_project_files


async def main() -> None:
    if not os.environ.get("NOVA_DB_PATH"):
        print("拒绝执行：请先设置 NOVA_DB_PATH 指向隔离数据库。")
        sys.exit(2)

    base = Path(os.environ.get("TEMP", ".")) / "ns_project_selftest"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    root = base / "demo-app"

    await db.init_db()
    await save_config({"allowed_dirs": [str(base)]})
    session = await session_store.create_session("项目自测")
    sid = session["id"]
    token = CURRENT_SESSION.set(sid)

    try:
        raw = await plan_project.ainvoke(
            {
                "title": "待办清单 CLI",
                "goal": "用 Python 做一个命令行待办工具",
                "root_dir": str(root),
                "steps": ["建目录结构", "写核心逻辑", "补 README", "自测"],
            }
        )
        plan = json.loads(raw)
        assert plan["total"] == 4 and plan["done"] == 0, plan
        assert plan["root_dir"] == str(root.resolve()), plan
        stored = await project_store.get_latest_plan(sid)
        assert stored and stored["plan_id"] == plan["plan_id"], stored
        print("[PASS] 1. plan_project 生成 4 步计划并入库")

        raw = await update_project_step.ainvoke({"step": 1, "status": "done", "note": "todo.py"})
        plan = json.loads(raw)
        assert plan["steps"][1]["status"] == "done" and plan["done"] == 1, plan
        assert plan["steps"][1]["note"] == "todo.py", plan
        print("[PASS] 2. update_project_step 更新步骤状态")

        raw = await write_project_files.ainvoke(
            {
                "root_dir": str(root),
                "files": [
                    {"path": "todo.py", "content": "print('todo')\n"},
                    {"path": "docs/README.md", "content": "# 待办清单\n"},
                ],
            }
        )
        assert "2/2" in raw, raw
        assert (root / "todo.py").read_text(encoding="utf-8") == "print('todo')\n"
        assert (root / "docs" / "README.md").is_file(), "父目录应自动创建"
        print("[PASS] 3. write_project_files 批量写入并自动建父目录")

        raw = await write_project_files.ainvoke(
            {"root_dir": str(root), "files": [{"path": "run.bat", "content": "echo hi"}]}
        )
        assert "安全限制" in raw, raw
        print("[PASS] 4. 可执行后缀被拦截")

        raw = await write_project_files.ainvoke(
            {"root_dir": str(root), "files": [{"path": "../escape.txt", "content": "x"}]}
        )
        assert "项目根目录内" in raw, raw
        print("[PASS] 5. 越出项目根目录被拦截")

        raw = await write_project_files.ainvoke(
            {
                "root_dir": str(root),
                "files": [{"path": f"f{i}.txt", "content": "x"} for i in range(11)],
            }
        )
        assert "单批最多" in raw, raw
        print("[PASS] 6. 超过单批文件数上限被拦截")

        raw = await update_project_step.ainvoke({"step": 9, "status": "done"})
        assert "越界" in raw, raw
        print("[PASS] 7. 步骤序号越界被拒绝")

        raw = await plan_project.ainvoke(
            {
                "title": "越权项目",
                "goal": "白名单外目录",
                "root_dir": str(Path(os.environ.get("TEMP", ".")) / "outside-dir"),
                "steps": ["a"],
            }
        )
        assert "授权目录" in raw, raw
        print("[PASS] 8. 白名单外根目录被拒绝")

        raw = await plan_project.ainvoke(
            {
                "title": "重复计划",
                "goal": "测试防重复建计划",
                "root_dir": str(root),
                "steps": ["a", "b"],
            }
        )
        assert "已有进行中的项目计划" in raw, raw
        stored = await project_store.get_latest_plan(sid)
        assert stored and stored["title"] == "待办清单 CLI" and stored["total"] == 4, stored
        print("[PASS] 9. 进行中的计划不会被重复创建")

        raw = await plan_project.ainvoke(
            {
                "title": "重做计划",
                "goal": "用户明确要求重排",
                "root_dir": str(root),
                "steps": ["a", "b"],
                "reset": True,
            }
        )
        plan = json.loads(raw)
        assert plan["title"] == "重做计划" and plan["total"] == 2, plan
        print("[PASS] 10. reset=true 允许重排计划")
    finally:
        CURRENT_SESSION.reset(token)
        await session_store.delete_session(sid)
        await db.close()
        shutil.rmtree(base, ignore_errors=True)

    print("\n项目模式自测全部通过")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
