"""M3 自测脚本：WebSocket 事件网关 + 会话持久化（离线假模型，不消耗 API 额度）。

运行：
    cd e:\nova-secretary
    $env:PYTHONPATH = "e:\nova-secretary"
    uv run --project backend python -m backend.server_selftest_gateway

覆盖场景：
1. 普通流式对话 → token + message，消息入库
2. 副作用工具 → human_confirm → 确认 → 工具执行 → 最终 message
3. 确认超时（配置 3 秒）→ 自动取消 + Agent 收尾
4. 会话列表 / 消息查询 / 删除接口
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

_DB_FILE = tempfile.NamedTemporaryFile(prefix="ns_m3_", suffix=".db", delete=False)
_DB_FILE.close()
os.environ["NOVA_DB_PATH"] = _DB_FILE.name
os.environ.setdefault("LLM_API_KEY", "sk-test-placeholder")

from fastapi.testclient import TestClient  # noqa: E402

import backend.server as server  # noqa: E402
from backend.agent.agent_graph import build_agent  # noqa: E402
from backend.agent.selftest_agent_graph import ScriptedChatModel  # noqa: E402
from backend.tools import get_all_tools  # noqa: E402

CURRENT_GRAPH: Any = None


async def _fake_get_agent_graph() -> Any:
    return CURRENT_GRAPH


server.get_agent_graph = _fake_get_agent_graph  # 用脚本化模型替换真实 LLM


def make_graph(script: list[AIMessage]) -> Any:
    return build_agent(ScriptedChatModel(script=script), tools=get_all_tools())


def tool_call_message(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def collect_until(ws: Any, expected_type: str, limit: int = 40) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event.get("type") == expected_type:
            return events
    raise AssertionError(f"未收到 {expected_type} 事件，已收到：{events}")


def new_session(client: TestClient) -> str:
    response = client.post("/api/sessions", json={})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def main() -> None:
    global CURRENT_GRAPH
    workdir = Path(tempfile.mkdtemp(prefix="ns_m3_allowed_"))
    plain_target = workdir / "plain.txt"

    with TestClient(server.app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok" and health["db_path"] == _DB_FILE.name
        print("[PASS] 0. 健康检查正常，数据库已隔离")

        cfg = client.put(
            "/api/config",
            json={
                "allowed_dirs": [str(workdir)],
                "confirm_timeout_seconds": 5,
                "autonomy_mode": False,  # 本测试验证“逐步确认”链路
            },
        )
        assert cfg.status_code == 200 and cfg.json()["confirm_timeout_seconds"] == 5

        # ---- 配置校验（M5） ----
        bad = client.put("/api/config", json={"allowed_dirs": ["relative/path"]})
        assert bad.status_code == 400 and "绝对路径" in bad.json()["detail"], bad.text
        bad = client.put("/api/config", json={"allowed_dirs": [str(workdir / "missing")]})
        assert bad.status_code == 400 and "不存在" in bad.json()["detail"], bad.text
        bad = client.put("/api/config", json={"model": {"temperature": 3}})
        assert bad.status_code == 400, bad.text
        bad = client.put("/api/config", json={"model": {"base_url": "ftp://example.com"}})
        assert bad.status_code == 400, bad.text
        bad = client.put("/api/config", json={"max_file_size_mb": 0})
        assert bad.status_code == 400, bad.text
        saved = client.put(
            "/api/config",
            json={
                "model": {
                    "base_url": "https://api.deepseek.com/v1",
                    "model_name": "deepseek-chat",
                    "temperature": 0.5,
                    "api_key": "should-be-dropped",
                },
                "max_file_size_mb": 12,
                "web_search_enabled": False,
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert "api_key" not in body["model"], body
        assert body["model"]["temperature"] == 0.5 and body["max_file_size_mb"] == 12
        assert body["web_search_enabled"] is False
        client.put(
            "/api/config",
            json={
                "model": {"temperature": 0.7},
                "max_file_size_mb": 10,
                "web_search_enabled": True,
            },
        )
        print("[PASS] M5 配置校验：非法目录/温度/base_url/大小均被拒，api_key 被丢弃")

        # ---- 场景1：普通对话 ----
        CURRENT_GRAPH = make_graph([AIMessage(content="你好，我是 NovaSecretary。")])
        sid = new_session(client)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "user_message", "session_id": sid, "message": "你好"})
            events = collect_until(ws, "message")
        assert any(e["type"] == "token" for e in events), events
        final = events[-1]["content"]
        assert final == "你好，我是 NovaSecretary。", final
        print("[PASS] 1. 普通对话流式返回 token + message")

        messages = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"], messages
        sessions = client.get("/api/sessions").json()["sessions"]
        assert sessions[0]["title"] == "你好", f"标题应自动生成：{sessions[0]}"
        print("[PASS] 2. 消息入库 + 会话标题自动生成")

        # ---- 场景2：人工确认（接受） ----
        CURRENT_GRAPH = make_graph(
            [
                tool_call_message(
                    "write_file",
                    {"file_path": str(plain_target), "content": "gateway"},
                    "call_gw",
                ),
                AIMessage(content="已写入文件。"),
            ]
        )
        sid2 = new_session(client)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "user_message", "session_id": sid2, "message": "帮我写文件"})
            events = collect_until(ws, "human_confirm")
            confirm = events[-1]
            assert confirm["action"] == "write_file" and confirm["confirm_id"], confirm
            assert not plain_target.exists(), "确认前不得写入"
            ws.send_json(
                {
                    "type": "confirm_result",
                    "confirm_id": confirm["confirm_id"],
                    "accepted": True,
                }
            )
            events = collect_until(ws, "message")
        assert plain_target.read_text(encoding="utf-8") == "gateway"
        assert any(e["type"] == "tool_status" and e["status"] == "done" for e in events), events
        roles = [m["role"] for m in client.get(f"/api/sessions/{sid2}/messages").json()["messages"]]
        assert roles == ["user", "tool", "assistant"], roles
        print("[PASS] 3. human_confirm → 确认 → 落盘 → 工具消息入库")

        # ---- 场景3：确认超时自动取消 ----
        timeout_target = workdir / "timeout.txt"
        CURRENT_GRAPH = make_graph(
            [
                tool_call_message(
                    "write_file",
                    {"file_path": str(timeout_target), "content": "x"},
                    "call_timeout",
                ),
                AIMessage(content="操作已取消。"),
            ]
        )
        sid3 = new_session(client)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "user_message", "session_id": sid3, "message": "写文件"})
            collect_until(ws, "human_confirm")
            events = collect_until(ws, "message")
        errors = [e for e in events if e["type"] == "error"]
        assert errors and "超时" in errors[0]["message"], events
        assert not timeout_target.exists(), "超时后不得执行副作用"
        print("[PASS] 4. 确认超时自动取消并让 Agent 收尾")

        # ---- 场景4：会话管理接口 ----
        assert client.delete(f"/api/sessions/{sid3}").json()["ok"] is True
        assert client.get(f"/api/sessions/{sid3}/messages").status_code == 404
        remaining = [s["id"] for s in client.get("/api/sessions").json()["sessions"]]
        assert sid in remaining and sid2 in remaining and sid3 not in remaining
        print("[PASS] 5. 会话列表 / 删除接口正常")

    print("\nM3 全部自测通过")


if __name__ == "__main__":
    main()
