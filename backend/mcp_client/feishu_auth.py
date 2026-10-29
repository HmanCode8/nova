"""飞书用户身份 OAuth（不依赖官方 keytar）。

流程：
1. 本地起一个临时回调服务（默认 http://localhost:3000/callback）
2. 浏览器打开飞书授权页，用户同意后回调带 code
3. 用 code 换 access_token + refresh_token，加密前落盘到应用数据目录
4. 之后每次调用前自动检查有效期，快过期时用 refresh_token 续期

密钥只从 backend/.env 读取；token 文件不进入项目目录、不写 sqlite。
命令行：
    python -m backend.mcp_client.feishu_auth login     # 首次授权 / 重新授权
    python -m backend.mcp_client.feishu_auth status    # 查看授权状态
    python -m backend.mcp_client.feishu_auth logout    # 清除本地 token
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

from backend.env_loader import load_env

from backend.mcp_client.client import MCPAuthRequired
from backend.storage.db import APP_DATA_DIR

load_env()

TOKEN_FILE = APP_DATA_DIR / "feishu_token.json"
REFRESH_MARGIN = 180  # 提前 3 分钟续期，避免请求途中过期
_login_lock = threading.Lock()


def _domain() -> str:
    return (os.getenv("FEISHU_DOMAIN") or "https://open.feishu.cn").rstrip("/")


def app_credentials() -> tuple[str, str]:
    app_id = (os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (os.getenv("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise MCPAuthRequired(
            "未配置飞书应用凭据：请在 backend/.env 填写 FEISHU_APP_ID 与 FEISHU_APP_SECRET。"
        )
    return app_id, app_secret


def redirect_uri() -> str:
    return (os.getenv("FEISHU_REDIRECT_URI") or "http://localhost:3000/callback").strip()


def authorization_url() -> str:
    app_id, _ = app_credentials()
    state = os.urandom(8).hex()
    query = urllib.parse.urlencode(
        {
            "app_id": app_id,
            "redirect_uri": redirect_uri(),
            "state": state,
        }
    )
    return f"{_domain()}/open-apis/authen/v1/authorize?{query}"


# ---------------------------------------------------------------------------
# token 存取
# ---------------------------------------------------------------------------

def load_token() -> dict[str, Any]:
    if not TOKEN_FILE.is_file():
        return {}
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_token(data: dict[str, Any]) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = TOKEN_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(TOKEN_FILE)


def clear_token() -> None:
    TOKEN_FILE.unlink(missing_ok=True)


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise MCPAuthRequired(f"飞书认证接口返回 {exc.code}：{detail}") from exc
    except Exception as exc:
        raise MCPAuthRequired(f"无法连接飞书认证接口：{exc}") from exc
    if not isinstance(data, dict):
        raise MCPAuthRequired("飞书认证接口返回格式异常")
    if data.get("code") not in (None, 0) or data.get("error"):
        message = data.get("error_description") or data.get("msg") or data
        raise MCPAuthRequired(f"飞书认证失败：{message}")
    return data


def _normalize_token_response(data: dict[str, Any]) -> dict[str, Any]:
    """v2 接口字段可能在顶层或 data 内，统一成扁平结构。"""
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise MCPAuthRequired(f"飞书未返回 access_token：{payload}")
    now = int(time.time())
    app_id, _ = app_credentials()
    return {
        "app_id": app_id,
        "access_token": access_token,
        "refresh_token": str(payload.get("refresh_token") or ""),
        "expires_at": now + int(payload.get("expires_in") or 7200) - REFRESH_MARGIN,
        "refresh_expires_at": now
        + int(payload.get("refresh_token_expires_in") or 30 * 24 * 3600)
        - REFRESH_MARGIN,
        "scope": payload.get("scope") or "",
        "updated_at": now,
    }


def exchange_code(code: str) -> dict[str, Any]:
    app_id, app_secret = app_credentials()
    data = _post_json(
        f"{_domain()}/open-apis/authen/v2/oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": app_id,
            "client_secret": app_secret,
            "code": code,
            "redirect_uri": redirect_uri(),
        },
    )
    token = _normalize_token_response(data)
    save_token(token)
    return token


def _refresh(token: dict[str, Any]) -> dict[str, Any]:
    app_id, app_secret = app_credentials()
    refresh_token = str(token.get("refresh_token") or "")
    if not refresh_token:
        raise MCPAuthRequired(
            "飞书授权已过期且没有 refresh_token，请重新执行："
            "python -m backend.mcp_client.feishu_auth login"
        )
    data = _post_json(
        f"{_domain()}/open-apis/authen/v2/oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "refresh_token": refresh_token,
        },
    )
    fresh = _normalize_token_response(data)
    if not fresh.get("refresh_token"):
        fresh["refresh_token"] = refresh_token  # 部分场景不轮换 refresh_token
    save_token(fresh)
    print("[feishu-auth] access_token 已自动续期", flush=True)
    return fresh


def _ensure_sync() -> str:
    app_id, _ = app_credentials()
    token = load_token()
    now = int(time.time())
    if token.get("app_id") != app_id:
        token = {}
    if token and int(token.get("expires_at") or 0) > now:
        return str(token["access_token"])
    if token and int(token.get("refresh_expires_at") or 0) > now:
        return str(_refresh(token)["access_token"])
    raise MCPAuthRequired(
        "飞书用户授权缺失或已过期，请先在本机执行："
        "python -m backend.mcp_client.feishu_auth login"
    )


async def ensure_access_token() -> str:
    """返回可用的 user_access_token；失效时自动刷新，无法刷新则抛 MCPAuthRequired。"""
    with _login_lock:
        return await asyncio.to_thread(_ensure_sync)


# ---------------------------------------------------------------------------
# 本地回调登录
# ---------------------------------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}
    done: threading.Event = threading.Event()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        query = urllib.parse.parse_qs(parsed.query)
        self.result = {
            "code": (query.get("code") or [""])[0],
            "state": (query.get("state") or [""])[0],
            "error": (query.get("error") or [""])[0],
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        message = "授权成功，可以关闭此页面回到 NovaSecretary。" if self.result["code"] else "授权失败。"
        self.wfile.write(
            f"<html><body style='font-family:sans-serif;padding:40px'><h2>{message}</h2></body></html>".encode(
                "utf-8"
            )
        )
        _CallbackHandler.done.set()

    def log_message(self, *args: Any) -> None:  # 静默 HTTP 日志
        return


def login(timeout: int = 180) -> dict[str, Any]:
    """启动本地回调服务并在浏览器完成飞书授权。"""
    app_id, _ = app_credentials()
    parsed = urllib.parse.urlparse(redirect_uri())
    port = parsed.port or 3000

    _CallbackHandler.result = {}
    _CallbackHandler.done = threading.Event()
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = authorization_url()
    print(f"应用：{app_id}")
    print(f"回调：{redirect_uri()}")
    print("如果浏览器没有自动打开，请手动访问：\n" + url)
    webbrowser.open(url)

    try:
        if not _CallbackHandler.done.wait(timeout):
            raise MCPAuthRequired(f"等待飞书授权超时（{timeout} 秒），请重试。")
    finally:
        server.shutdown()
        server.server_close()

    result = _CallbackHandler.result
    if result.get("error"):
        raise MCPAuthRequired(f"飞书授权被拒绝：{result['error']}")
    if not result.get("code"):
        raise MCPAuthRequired("回调未携带授权码，请检查飞书应用的重定向地址配置。")
    token = exchange_code(result["code"])
    print(f"授权成功，token 已保存：{TOKEN_FILE}")
    return token


def status() -> None:
    token = load_token()
    if not token:
        print("未授权：请执行 python -m backend.mcp_client.feishu_auth login")
        return
    now = int(time.time())
    access_left = int(token.get("expires_at") or 0) - now
    refresh_left = int(token.get("refresh_expires_at") or 0) - now
    print(f"应用：{token.get('app_id')}")
    print(f"access_token 剩余：{access_left} 秒")
    print(f"refresh_token 剩余：{refresh_left} 秒")
    print("状态：" + ("可用" if access_left > 0 else ("可自动续期" if refresh_left > 0 else "已过期，需重新登录")))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="飞书用户身份授权")
    parser.add_argument("action", choices=["login", "status", "logout"], nargs="?", default="status")
    args = parser.parse_args(argv)
    try:
        if args.action == "login":
            login()
        elif args.action == "logout":
            clear_token()
            print("本地飞书 token 已清除")
        else:
            status()
    except MCPAuthRequired as exc:
        print(f"❌ {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
