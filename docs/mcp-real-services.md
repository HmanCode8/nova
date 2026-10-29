# 真实 MCP 服务接入记录（阶段2.5，暂停中）

> 状态：代码已完成并自测通过（Mock 链路回归全绿），**真实凭据未配置，暂停验收**。
> 恢复方式见文末「继续验收」。

## 已实现

| 能力 | 实现 |
| --- | --- |
| 邮件 | `backend/mcp_client/mail_server.py`：飞书邮箱 IMAP/SMTP 包装成 MCP 工具（今日邮件、读全文、发邮件） |
| 日历 | 飞书官方 `@larksuiteoapi/lark-mcp@0.3.1`（stdio），用户身份 `useUAT=true` |
| 授权 | `backend/mcp_client/feishu_auth.py`：本地回调 OAuth、token 存 `%APPDATA%/NovaSecretary/feishu_token.json`、自动续期 |
| 装配 | `backend/mcp_client/servers.py`：按 `.env` 选择 mock / imap / feishu |
| 归一化 | `backend/tools/mcp_tools.py`：飞书/Gmail 兼容的卡片 JSON，前端与 Agent 无感知 |

## 关键决策与坑点

1. **不用 lark-mcp 0.4+**：依赖 `keytar` 原生模块，Windows 无 VS Build Tools 时 npm 安装失败；0.3.1 无原生依赖，支持 `-u` 传用户 token。
2. **飞书身份**：应用身份（tenant_access_token）读不到个人日历，必须用户 OAuth。
3. **飞书 MCP 工具名**：`calendar_v4_calendar_primary`、`calendar_v4_calendarEvent_list/create/get/patch`；列表必须显式 `-t calendar.v4.calendarEvent.list` 才会启用。
4. **Gmail 放弃**：本机网络 `oauth2.googleapis.com` / `gmail.googleapis.com` 全部超时，OAuth 与 API 均不可达。若后续有稳定代理，可按同一 provider 结构增加 `gmail`。
5. **凭据边界**：`.env` 只放 app_id/secret 与邮箱客户端专用密码；token 文件在应用数据目录；sqlite 不存任何密钥。
6. **`npx` 首次拉包**：约 10~30 秒，之后走缓存；子进程 env 继承系统代理。

## 环境变量

```
NOVA_MAIL_PROVIDER=mock|imap
NOVA_CALENDAR_PROVIDER=mock|feishu

MAIL_IMAP_HOST=imap.feishu.cn
MAIL_IMAP_PORT=993
MAIL_SMTP_HOST=smtp.feishu.cn
MAIL_SMTP_PORT=465
MAIL_USERNAME=
MAIL_PASSWORD=      # 客户端专用密码
MAIL_FROM_NAME=

FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_DOMAIN=https://open.feishu.cn
FEISHU_REDIRECT_URI=http://localhost:3000/callback
```

## 继续验收（凭据就绪后）

1. 飞书开放平台：自建应用 → 日历读写权限 → 重定向 URL `http://localhost:3000/callback` → 发布
2. 飞书邮箱：开启 IMAP/SMTP，生成客户端专用密码
3. `.env` 填好后：
   ```powershell
   $env:PYTHONPATH="e:\nova-secretary"
   uv run --project backend python -m backend.mcp_client.feishu_auth login
   uv run --project backend python -m backend.mcp_client.selftest_real_mcp
   ```
4. 把 `NOVA_MAIL_PROVIDER` / `NOVA_CALENDAR_PROVIDER` 改为 `imap` / `feishu`，重启后端

## 后续规划：MCP 商店

- 服务定义外部化：`mcp_servers.json`（命令、参数、env 占位、鉴权方式、工具白名单）
- 前端设置面板：安装/启停/授权状态/工具列表，凭据只写 `.env` 或系统凭据库
- 连接器分类：邮件、日历、IM、文档；每个连接器独立 provider 映射与卡片渲染
- 安全：命令白名单、参数校验、子进程资源限制、安装前告知权限范围
