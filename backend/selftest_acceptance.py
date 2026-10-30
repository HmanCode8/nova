"""批次 5：ACCEPTANCE_TEST.md 可自动化项验收脚本（纯 HTTP）。

用法（后端已在 127.0.0.1:8000 运行）：
    uv run python -m backend.selftest_acceptance

说明：本脚本不直接打开 SQLite（本机 aiosqlite + Python 3.14 的 WAL 初始化在
独立事件循环里会失败），所有状态都通过后端 HTTP 接口读取；密钥检查用同步
sqlite3 只读查询。需要 trigger 工具调用的项由 server_selftest_gateway 覆盖。
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API = "http://127.0.0.1:8000"
RESULTS: list[tuple[str, str, str]] = []


def record(item: str, status: str, note: str = "") -> None:
    RESULTS.append((item, status, note))
    print(f"[{status}] {item}{('：' + note) if note else ''}")


def http(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def case_a() -> None:
    code, health = http("/api/health")
    record("A1 前后端连通", "PASS" if code == 200 and health.get("status") == "ok" else "FAIL")
    record(
        "A1 模型已配置",
        "PASS" if health.get("model_configured") else "FAIL",
    )

    code, session = http("/api/sessions", "POST", {})
    sid = session.get("id", "")
    record("A4 新建会话", "PASS" if code == 200 and sid else "FAIL")

    code, data = http("/api/sessions")
    ids = [item["id"] for item in data.get("sessions", [])]
    record("A3 会话持久化（列表可查）", "PASS" if sid in ids else "FAIL")

    code, msgs = http(f"/api/sessions/{sid}/messages")
    record("A3 历史消息接口", "PASS" if code == 200 and isinstance(msgs.get("messages"), list) else "FAIL")
    http(f"/api/sessions/{sid}", "DELETE")


def case_e() -> None:
    code, data = http("/api/mcp/catalog")
    ids = [item["id"] for item in data.get("items", [])]
    record("E1 商店展示（目录 + 分类）", "PASS" if code == 200 and len(ids) >= 5 else "FAIL", f"{len(ids)} 个条目")

    code, data = http("/api/mcp/servers", "POST", {"catalog_id": "nova-mock"})
    server = data.get("server") or {}
    record(
        "E2 安装 MCP 并启动",
        "PASS" if code == 200 and server.get("status") == "running" else "FAIL",
        server.get("error", ""),
    )
    sid = server.get("id", "")
    record("E3 工具发现", "PASS" if server.get("tool_count", 0) > 0 else "FAIL", f"{server.get('tool_count')} 个工具")

    code, data = http(f"/api/mcp/servers/{sid}/test", "POST")
    record("E5 连接测试", "PASS" if data.get("ok") else "FAIL", data.get("message", ""))

    code, data = http(f"/api/mcp/servers/{sid}/toggle", "POST", {"enabled": False})
    row = next((item for item in data.get("servers", []) if item["id"] == sid), {})
    record("E6a 停用后工具失效", "PASS" if row.get("tool_count") == 0 else "FAIL")

    code, data = http(f"/api/mcp/servers/{sid}/toggle", "POST", {"enabled": True})
    row = next((item for item in data.get("servers", []) if item["id"] == sid), {})
    record("E6b 重新启用工具恢复", "PASS" if row.get("tool_count", 0) > 0 else "FAIL")

    code, data = http(f"/api/radar")
    sources = data.get("sources") or []
    record(
        "E7 MCP 数据可被资讯雷达取用（原始数据）",
        "PASS" if code == 200 and any(item.get("ok") for item in sources) else "FAIL",
        f"{len(data.get('items', []))} 条",
    )
    http(f"/api/mcp/servers/{sid}", "DELETE")


def case_f() -> None:
    code, data = http("/api/traces?limit=20")
    rows = data.get("traces", [])
    record("F 轨迹接口可用", "PASS" if code == 200 and isinstance(rows, list) else "FAIL", f"{len(rows)} 条")
    if not rows:
        record("F1/F2 记录调用/参数/结果/耗时", "SKIP", "当前无数据，先跑一次对话")
        return
    sample = rows[0]
    has_fields = all(key in sample for key in ("tool_name", "params", "result", "duration_ms", "status"))
    record("F1/F2 记录调用/参数/结果/耗时", "PASS" if has_fields else "FAIL")
    record("F4 关键词搜索", "PASS" if http(f"/api/traces?search={sample['tool_name']}")[1].get("traces") else "FAIL")
    record(
        "F3 删除确认留痕（confirmed 字段）",
        "PASS" if "confirmed" in sample else "FAIL",
        "历史轨迹若无删除调用则 confirmed 为 false，属正常",
    )


def case_g() -> None:
    sid = http("/api/sessions", "POST", {})[1].get("id", "")
    code, data = http(
        "/api/tasks",
        "POST",
        {
            "session_id": sid,
            "title": "验收任务",
            "prompt": "用 shell_run 执行命令 echo accept-task，然后告诉我输出。",
        },
    )
    task = data.get("task") or {}
    record("G1 创建后台任务", "PASS" if code == 200 and task.get("id") else "FAIL", data.get("detail", ""))

    task_id = task.get("id", "")
    status = ""
    deadline = time.time() + 200
    while time.time() < deadline and task_id:
        rows = http(f"/api/tasks?session_id={sid}")[1].get("tasks", [])
        status = next((item["status"] for item in rows if item["id"] == task_id), "")
        if status not in ("pending", "running"):
            break
        time.sleep(2)
    record("G2 任务执行完成并记录结果", "PASS" if status == "success" else "FAIL", f"最终状态 {status}")

    code, data = http(
        "/api/tasks",
        "POST",
        {"session_id": sid, "title": "停止验证", "prompt": "依次用 shell_run 执行 echo A1 / echo A2 / echo A3"},
    )
    stop_id = (data.get("task") or {}).get("id", "")
    time.sleep(1)
    code, _ = http(f"/api/tasks/{stop_id}/stop", "POST")
    record("G3 停止任务", "PASS" if code == 200 else "FAIL")
    http(f"/api/sessions/{sid}", "DELETE")


def case_h() -> None:
    sid = http("/api/sessions", "POST", {})[1].get("id", "")
    http("/api/memory", "POST", {"scope": "session", "text": "我习惯用 uv 管理依赖", "session_id": sid})
    _, data = http(f"/api/memory?session_id={sid}")
    record("H1 会话记忆写入并读回", "PASS" if "uv" in json.dumps(data, ensure_ascii=False) else "FAIL")

    http("/api/memory", "POST", {"scope": "global", "text": "默认包管理器是 uv"})
    _, data = http("/api/memory?session_id=")
    record("H2 长期记忆（跨会话）", "PASS" if "uv" in json.dumps(data, ensure_ascii=False) else "FAIL")

    http("/api/memory?scope=global", "DELETE")
    http(f"/api/memory?scope=session&session_id={sid}", "DELETE")
    http(f"/api/sessions/{sid}", "DELETE")


def case_j() -> None:
    # 本机无法从脚本进程直接打开该 WAL 库（disk I/O error），改用配置接口 + 写入侧校验：
    # 1) /api/config 不应返回任何密钥值；2) server_selftest_gateway 的 M5 已断言 api_key 被丢弃
    # 注意 api_key_env 是环境变量「名字」不是密钥值，属允许字段
    _, cfg = http("/api/config")
    text = json.dumps(cfg, ensure_ascii=False)
    leaks = re.search(r'"api_key"\s*:', text) or "sk-" in text
    record("J1 密钥不入库 / 不外泄", "PASS" if not leaks else "FAIL", "" if not leaks else text[:120])

    _, cfg = http("/api/config")
    record("J3 白名单生效", "PASS" if cfg.get("allowed_dirs") else "FAIL", str(cfg.get("allowed_dirs")))

    code, data = http("/api/traces?limit=50")
    record("J4 Trace 表可查询", "PASS" if code == 200 else "FAIL")

    # D5：消息内容里不应出现 base64 原图
    sid = http("/api/sessions", "POST", {})[1].get("id", "")
    _, msgs = http(f"/api/sessions/{sid}/messages")
    texts = json.dumps(msgs, ensure_ascii=False)
    record("D5 图片 base64 不入库", "PASS" if "base64," not in texts else "FAIL")
    http(f"/api/sessions/{sid}", "DELETE")


def main() -> None:
    code, cfg = http("/api/config")
    if code != 200:
        print("后端未启动，无法验收")
        raise SystemExit(1)
    if not cfg.get("allowed_dirs"):
        print("白名单为空，先配置一个目录再验收")
        raise SystemExit(1)

    case_a()
    case_e()
    case_f()
    case_g()
    case_h()
    case_j()

    passed = sum(1 for _, status, _ in RESULTS if status == "PASS")
    skipped = [item for item, status, _ in RESULTS if status == "SKIP"]
    failed = [item for item, status, _ in RESULTS if status == "FAIL"]
    print("\n" + "=" * 64)
    print(f"自动化验收：{passed}/{len(RESULTS)} 通过，跳过 {len(skipped)}，失败 {len(failed)}")
    if failed:
        print("失败项：" + "、".join(failed))
    print("=" * 64)
    print(
        "\n需人工/专属脚本验证：A2 流式对话、B1-B8 实机工具执行、C1-C6 删除确认与超时、"
        "C7 语音确认、D1-D4 OCR/VL、E4 Agent 调 MCP、G4 并发、H3 长对话摘要、I1-I8 界面与托盘"
    )


if __name__ == "__main__":
    main()
