# NovaSecretary — 最终完整开发方案主文档
> 版本：v1.0 终稿 ｜ 交付给 TRAE SOLO 作为开发基线
> 定位：**Mac + Windows 双桌面私人 AI 秘书**，语音/文字双输入、联网搜索、本地文档代码处理、邮件日历查询、悬浮宠物、炫酷科技UI。

---

## 一、项目一句话定位
常驻桌面的私人 AI 助理：随时唤起（悬浮宠/快捷键）、可语音可打字、能读你授权的文档和代码、能帮你查邮件和日程、能联网查资料，像一个贴身工作秘书；数据默认本地留存、敏感操作需你确认。

---

## 二、需求梳理（用户原始诉求 + 我们确认的边界）

### 核心能力（MVP 要做）
1. **对话**：文字对话 + 按住麦克风语音对话（不做后台持续唤醒监听）
2. **LLM**：OpenAI 兼容协议，可切换 Ollama 本地模型 / DeepSeek / 其他支持 Function Call 的模型
3. **联网搜索**：Tavily，设置面板一键开关，关闭后工具不可调用
4. **文档与代码**：读取/写入本地 txt/md/代码文件；辅助写代码、排查报错、解释工程、生成 prompt/skill/开发文档
5. **系统工具**：剪贴板读写、截图+OCR识别截图、调用系统默认程序打开本地文档（人工确认后执行）
6. **邮件日历（MCP）**：查今日邮件摘要、读单封邮件、查今日日程；发送邮件/新建日程属于带副作用操作，人工确认后才执行
7. **记忆**：多会话隔离、会话内上下文、长期偏好记忆（记住编码习惯、文档格式偏好）
8. **UI**：科技深色对话面板（粒子背景、音频波形、卡片结果）+ 桌面悬浮宠物（idle/thinking/done 三套 Lottie 动画）
9. **全局快捷键**：Windows `Alt+Space`；macOS `Option+Space`
10. **托盘后台常驻**，关闭窗口后后台保持运行
11. **人工确认机制**：所有带副作用工具（写文件、打开文档、发邮件、新建日程）执行前暂停 Agent，推送确认卡片，你确认后才执行

### 明确不做（MVP 及任何阶段，防止无限扩展）
- ❌ 账号登录、云端同步、多人协作
- ❌ 自动发送/自动回复邮件（必须人工确认）
- ❌ 无限制 GUI 自动点击自动化（pyautogui）
- ❌ 爬虫工具
- ❌ 复杂 Word/Excel 解析（优先 md/txt/代码文本）
- ❌ OSS 云存储（仅想法，不实现）

### 后续扩展（MVP 稳定后再做）
- 本地知识库 RAG
- 更多 MCP 连接器（飞书、Notion）
- 唤醒词语音监听（后置）
- 语音确认替代鼠标点击确认

---

## 三、技术选型（已敲定）
| 层次 | 选型 | 说明 |
|---|---|---|
| 桌面端 | Electron + Vue3 + Vite | 前端壳，先验证，稳定后可迁移 Tauri2 |
| 后端 | Python FastAPI + Uvicorn | ASGI 异步，WebSocket 流式通信，仅本地 127.0.0.1 |
| Agent编排 | LangGraph 原生 StateGraph + create_react_agent | 手写节点，白盒可控 |
| 模型适配 | 少量 LangChain 组件（ChatOpenAI、@tool、消息对象） | 统一 OpenAI 兼容协议 |
| 存储 | SQLite + aiosqlite | 全异步，本地单文件 |
| 语音 | faster-whisper（ASR）+ piper（TTS） | 本地处理，不上传 |
| 工具协议 | MCP（邮件/日历） | OAuth 授权，高危确认 |

### 明确不引入
- ❌ LangChain `agents.middleware` 高层中间件（改用原生 interrupt，效果一致、控制力更高）
- ❌ LangGraph Store（记忆用自研 SQLite）
- ❌ LangSmith（会上传 trace，MVP 不接入）
- ❌ Redis / MQ / Nginx / Celery 等重型中间件
- ❌ OSS 云存储

---

## 四、架构总览（前后端严格分离）
```
Electron+Vue3(UI/窗口/热键/托盘/麦克风)
        │  WebSocket + HTTP
        ▼
FastAPI 后端 (127.0.0.1:8000)
  ├─ WebSocket事件网关（协议转换/分发/流式推送）
  ├─ Graph前置节点（记忆注入/token检查/摘要）
  ├─ LangGraph ReAct 图
  │     └─ interrupt() 人工确认
  ├─ 统一工具钩子 tool_hook（校验/确认/截断）
  ├─ 各 @tool 工具
  ├─ llm_adapter（模型适配/重试/图片base64）
  ├─ storage（SQLite 持久化适配层）
  └─ mcp_client（MCP stdio 适配器）
```

---

## 五、固定目录结构（严禁擅改）
```
nova-secretary/
├─ AGENTS.md                  # TRAE 全局规则
├─ README.md                  # 使用说明
├─ FINAL_DEVELOPMENT_DOC.md   # 本主文档
├─ .trae/rules/               # TRAE 技能规则
├─ backend/
│  ├─ agent/                  # agent_graph.py、llm_adapter.py、context_compress.py
│  ├─ tools/                  # tool_hook.py + 各工具
│  ├─ storage/                # db.py、session_store.py
│  ├─ voice/                  # asr.py、tts.py
│  ├─ mcp_client/
│  ├─ server.py
│  ├─ pyproject.toml
│  └─ .env
├─ frontend-electron/         # Electron + Vue3
├─ assets/                    # Lottie动画、图标
└─ docs/
```

---

## 六、全部 Agent 工具清单（MVP）
### 文件类
- `read_file`：读授权目录文本/代码文件（只读）
- `write_file`：写入文本文件（人工确认）
- `list_dir`：浏览授权目录
- `open_local_file`：系统默认程序打开本地文档（白名单校验 + 可执行后缀黑名单 + 人工确认）

### 网络
- `tavily_web_search`：联网搜索（受联网开关控制）

### 剪贴板
- `clipboard_read` / `clipboard_write`

### 截图 OCR
- `take_screenshot` / `ocr_image`

### MCP 邮件日历
- `email_list_today` / `email_read_detail` / `calendar_list_today` / `email_send`(确认) / `calendar_create`(确认)

### 记忆
- `add_session_memory` / `delete_session_memory` / `add_global_memory` / `delete_global_memory`

### 上传文件配套
- `read_uploaded_file`（仅会话临时目录）/ `list_uploaded_files`

### 上下文与会话
- `create_new_session` / `summarize_context`

### 扩展工具（MVP 后开发，禁止提前实现）
run_shell、git系列、open_browser、open_local_app、pdf_read、excel_read_simple、local_kb_search、audio_transcribe_local

---

## 七、人工确认交互（Human-in-the-loop）
**技术实现**：LangGraph 原生 `interrupt()` + checkpointer（不用 langchain.agents.middleware）
- 适用：write_file / open_local_file / email_send / calendar_create
- 流程：
  1. Agent 调用带副作用工具
  2. 工具钩子硬校验（白名单、后缀黑名单、参数合法性），不通过直接拒绝，不弹确认
  3. 通过 → `interrupt()` 暂停，推送确认事件到前端（载荷轻量：动作类型+必要参数+预览文本）
  4. 前端渲染确认卡片（鼠标点击【确认执行】/【取消】）
  5. 确认 → 执行真实工具逻辑，结果送回 Agent 循环；取消 → 返回"用户已取消"，Agent 继续对话
  6. 超时：3 分钟未响应自动判定取消，释放 Agent 状态
- MVP 仅鼠标点击确认；语音确认留待语音模块完成后扩展

---

## 八、Content / State / Store 边界（防 token 爆炸核心）
### 概念
- **Content**：消息内文本数据字段（BaseMessage.content），是数据，不是容器
- **State**：LangGraph 图运行时容器（内存级），核心 key 是 messages，跟随图循环传给 LLM
- **Store**：LangGraph 内置 KV 长期存储 → **MVP 不用**，记忆走自研 SQLite

### 流转铁律
1. 长期记忆 ≠ State：需要才加载进 State，用完不长期霸占
2. 原始文件大 content：生命周期 = 单次工具调用 → 本轮 State 临时使用；不绑定会话历史
3. 工具返回长内容写入持久化前自动摘要压缩；summarize_context 定期压缩久远对话
4. 图片 base64：仅在调用多模态模型瞬间临时构造，推理结束即丢弃，只存摘要+file_id
5. 会话重启：State 由 SQLite 精简摘要初始化，不自动回填历史全文/base64
6. 人工确认事件载荷轻量化，不携带大文本

### Runtime 约束
- 文件读取/搜索/邮件返回的长文本，允许临时进入 ToolMessage 供本轮推理，但设单次读取上限
- 入库持久化消息前执行摘要压缩，不还原完整原文
- State 设置全局 token 软上限，接近阈值自动触发上下文压缩

---

## 九、自研轻量中间层（替代第三方中间件）
| 模块 | 位置 | 作用 |
|---|---|---|
| WebSocket事件网关 | server.py ws路由 | 事件协议转换、分发、流式推送 |
| Graph前置节点 | agent/agent_graph.py | 记忆注入、system组装、token检查、摘要 |
| 工具调用钩子 | tools/tool_hook.py | 统一校验、确认识别、返回值截断、异常捕获 |
| 消息持久化适配层 | storage/session_store.py | State 结构 ↔ SQLite 结构互转，写入瘦身 |
| LLM 模型适配层 | agent/llm_adapter.py | OpenAI兼容封装、重试、图片base64 |
| MCP 协议适配器 | mcp_client/ | 工具参数 ↔ MCP JSON-RPC stdio 互转 |

> 原则：内联同步、职责单一、只做转换/校验/转发，不承载业务决策。

### 后续扩展：自研 Middleware 规划（对标 LangChain 官方 Middleware）
> MVP 阶段不引入 middleware 机制，能力由独立节点/钩子实现。
> 项目稳定后可抽象一套自研中间件钩子体系，对齐 LangChain `agents.middleware` 标准点位，插拔式启用/关闭。

【对齐的 LangChain 原生钩子点位】
`before_agent → before_model → wrap_model_call → wrap_tool_call → after_model → after_agent`

【计划实现的自研中间件清单】
1. `ToolConfirmMiddleware`（挂 wrap_tool_call）— 对标 HumanInTheLoopMiddleware：副作用识别、触发 interrupt 人工确认
2. `ContextSummarizeMiddleware`（挂 before_agent / after_model）— 对标 SummarizationMiddleware：token 统计、自动摘要压缩
3. `ToolParamValidateMiddleware`（挂 wrap_tool_call）— 对标 ValidationMiddleware：路径白名单、后缀黑名单、参数合法性校验
4. `RetryErrorMiddleware`（挂 wrap_model_call / wrap_tool_call）— 对标 ErrorHandlingMiddleware：LLM 重试、工具异常捕获、错误包装
5. `LoggingMiddleware`（挂全点位）— 对标 LoggingMiddleware：全链路结构化日志

> 可选第三方社区中间件（按需）：TokenCountMiddleware（token 统计）、ReadOnlyGuardMiddleware（只读/副作用工具分级）、CacheMiddleware（LLM 结果缓存，引入 Redis 时才考虑）。

【设计原则】
自研中间件只是对现有逻辑做一层抽象封装，底层仍基于 LangGraph 原生 StateGraph + interrupt，**不会切换回 create_agent 黑盒模式**；每个中间件可单独开关，插拔式组合。

---

## 十、WebSocket 事件协议
前端 → 后端：
- `{"type":"user_message","session_id":"","message":""}`
- `{"type":"confirm_result","confirm_id":"","accepted":true/false}`
- `{"type":"control","action":"stop"/"cancel"}`

后端 → 前端：
- `{"type":"token","delta":""}`
- `{"type":"tool_status","tool_name":"","status":"running"/"done"}`
- `{"type":"human_confirm","confirm_id":"","action":"","preview_text":"","params":{}}`
- `{"type":"message","role":"assistant","content":""}`
- `{"type":"error","message":""}`

---

## 十一、数据存储与记忆
### 存储
- SQLite 单文件，路径：Windows `%APPDATA%/NovaSecretary/nova.db`；macOS `~/Library/Application Support/NovaSecretary/nova.db`
- 表：sessions、messages、session_memory、global_memory、uploaded_file_meta、app_config
- 密钥只在 .env，绝不入 sqlite
- 提供导出会话、清空单会话、清空全部数据

### 记忆（三类）
- 原始对话消息（messages）+ 自动摘要压缩
- 会话级记忆（session_memory）
- 全局记忆（global_memory）
- 自动记忆总开关、前端记忆管理面板（查看/编辑/删除/清空）
- 记忆抽取由 LLM 提炼，不直接存聊天原文

---

## 十二、文件与图片上传处理
- Electron 系统文件选择框 → FastAPI `/upload` 接口 → 会话隔离临时目录 `temp/{session_id}/`
- 消息只存 file_id + 摘要；需要内容时调用 read_uploaded_file 按需读取
- 图片：推理瞬间临时 base64，用完丢弃，只存摘要+file_id
- 清理：后端启动清理 7 天前临时文件；删除会话同步清理；MVP 单文件上限 10MB
- 权限隔离：`read_file` 只读授权白名单目录；`read_uploaded_file` 只读会话临时目录

---

## 十三、MVP 内置开关（设置面板）
1. 联网开关：关闭后 tavily 不可调用
2. 自动记忆开关：关闭后不再自动生成新记忆
3. 目录白名单：配置 Agent 可访问的文件夹
4. 单文件大小上限：默认 10MB
5. 模型配置：base_url、api_key、model、temperature

---

## 十四、分期开发计划（严格顺序，上阶段验收通过再进下一阶段）
### 阶段0｜基座搭建
后端 FastAPI+WebSocket、LangGraph ReAct 骨架、SQLite 建表、Vue 基础聊天页、read/write 文件工具（write 带确认）
✅ 验收：文字对话、文件工具调用、流式返回、重启会话不丢

### 阶段1｜MVP 文字完整版
剪贴板/截图OCR/Tavily工具、SQLite持久化、记忆模块、统一工具钩子、上下文摘要、llm_adapter、WebSocket事件网关、主聊天窗口（含确认卡片）、设置面板、托盘
✅ 验收：文字对话、读代码文档、截图分析、联网搜索、副作用工具弹确认、开关可控、长对话自动摘要

### 阶段2｜悬浮宠物 + 全局快捷键
悬浮窗口（透明/无边框/置顶/拖拽/Alpha穿透）、Alt+Space/Option+Space 唤起、宠物状态联动 Lottie
✅ 验收：双平台常驻宠物、快捷键一键唤起

### 阶段2.5｜语音秘书模块
voice（faster-whisper+piper）、MCP Client、邮件日历工具、语音面板/波形/播报、语音确认（扩展）
✅ 验收：语音提问查邮件日程+联网搜索，自动多工具调用，总结并语音播报

### 阶段3｜稳定性打磨
双平台差异bug、权限、悬浮球拖拽偏移、置顶冲突、日志、优雅退出、开机自启、确认超时优化

### 阶段4（可选）｜迁移 Tauri2
保留 Vue 组件，Rust 重写外壳，Python 后端不动，打包 exe + dmg

---

## 十五、给 TRAE 的启动指令
```
读取项目根目录 AGENTS.md 和 .trae/rules/ 下全部SKILL规则。
项目名称NovaSecretary，Mac+Windows双桌面语音AI秘书，Electron+Vue + Python uv + FastAPI + LangGraph ReAct，手写interrupt做人工确认，支持LangChain联网工具、MCP邮件日历、本地语音ASR/TTS、悬浮宠物。
我们从【阶段0：基座搭建】开始开发，先搭建后端FastAPI+websocket服务 + LangGraph基础ReAct Agent + SQLite存储基座 + Vue基础聊天页面，实现基础对话 + txt读写工具。
先输出阶段0任务清单、目录初始化命令、依赖清单，等待我确认，确认后再写代码。
```

---

## 十六、RAG 与 MCP 扩展预留说明（为后续接入预留，MVP 不实现 RAG）
> 目的：MVP 架构已为 RAG 和 MCP 预留清晰接入点，后续扩展不必重构。

### 1. MCP（已预留，阶段2.5实现邮件/日历）
- **预留位置**：`backend/mcp_client/`（MCP stdio 适配器目录，独立模块）
- **当前状态**：阶段2.5 实现邮件、日历两个 MCP Server 连接
- **后续扩展**：新增飞书、Notion、Google 日历等更多 MCP 服务
- **接入方式**：在 `mcp_client/` 新增对应服务适配器 → 把新工具注册进 `agent_graph.py` 的 tools 列表 → 高危操作走统一人工确认钩子。无需改架构。
- **约束**：MCP 使用 OAuth 授权，密钥不进 sqlite；敏感操作（发邮件/建日程）必须人工确认。

### 2. RAG 本地知识库（已预留，MVP 不实现）
- **预留位置**：扩展工具 `local_kb_search`（已列在扩展工具清单）；后端可新增 `backend/kb/` 模块放向量化与检索逻辑
- **当前状态**：MVP 不做向量库/检索器，仅做本地单文件/会话文件问答
- **后续扩展**：绑定指定文件夹，做本地知识库问答（RAG）
- **接入方式**：新增向量库（如 Chroma / FAISS）→ 实现 `local_kb_search` 工具（从绑定目录检索片段返回）→ 注册进 Agent tools。检索结果同样走「仅本轮 state 使用 + 入库摘要」的 token 控制规范。
- **约束**：检索范围限定用户显式绑定的文件夹，不自动全盘扫描；检索片段入库前摘要瘦身。

### 扩展预留小结
| 能力 | 预留位置 | MVP状态 | 扩展入口 |
|---|---|---|---|
| MCP 更多服务 | backend/mcp_client/ | 已实现邮件/日历 | 新增服务适配器 + 注册工具 |
| RAG 本地知识库 | local_kb_search + backend/kb/ | 不实现 | 加向量库 + 实现检索工具 |

---

## 十七、验收与交付规范
- 每次交付完整可运行代码 + Windows PowerShell / Mac zsh 双套启动命令 + 依赖安装步骤
- 密钥进 .env，禁止硬编码
- 双平台差异在注释标明
- 新增功能先方案评审，我确认后写代码
- Bug 最小改动修复，不随意重构架构
- 交付前自测，等待我验收
