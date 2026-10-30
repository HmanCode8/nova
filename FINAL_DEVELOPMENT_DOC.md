# NovaSecretary — 最终完整开发方案主文档（v2 自主执行生产 Agent）
> 版本：v2.0 ｜ 交付给 TRAE SOLO 作为开发基线
> 定位：**跨平台（Windows + Mac）桌面自主执行 AI 生产 Agent**
> 一句话：Agent 可自主操作本机电脑，自由读写/新建/修改/打开文件、执行命令、联网、调 MCP 帮你完成任务；**仅文件删除必须人工确认**；全部动作留轨迹；内置 MCP 商店自由扩展。

---

## 一、项目定位
常驻桌面的自主生产 Agent：
- 帮你开发项目、做 UI 原型、整理文档、查资料、处理文件，Agent 可以连续多轮自主执行直到产出交付物
- 平时当个人助理，需要的时候切到生产模式，让 Agent 在你本机工作目录自由干活
- 数据本地存储，不上传；删除操作强确认

---

## 二、权限模型（核心，最关键）
| 操作 | 权限 | 说明 |
|---|---|---|
| 读取文件 | ✅ 放行 | 白名单目录内自由读取 |
| 新建/编辑/写文件 | ✅ 放行 | 直接执行，不需 Diff 确认 |
| 打开文件 | ✅ 放行 | 调用系统程序打开 |
| 截屏 | ✅ 放行 | 截图送入 OCR/VL |
| 执行命令 | ✅ 放行 | 白名单目录内 PowerShell/Shell |
| 联网搜索 | ✅ 放行 | Tavily，开关可控 |
| 调用 MCP | ✅ 放行 | 已安装 MCP 工具自动调用 |
| 剪贴板 | ✅ 放行 | 读取剪贴板 |
| **删除文件/文件夹** | ⛔ **强制确认** | 流程中断，点击/语音确认后才执行 |

> 兜底防线：**目录白名单**。Agent 只能访问你配置的根目录范围，无法触碰白名单外的系统敏感路径。
> 允许范围：用户可手动配置允许 Agent 访问的文件夹；白名单之外一律拒绝。

---

## 三、界面方案
### 1. 形态双入口
1. **桌面悬浮球**（常驻）：科技粒子 UI、全局快捷键唤醒、全局语音开关，随时唤起主工作台
2. **三栏工作台窗口**（主界面），面板可拖拽缩放、单独收起
   - 左栏：资讯雷达（数据源来自 MCP：RSS/资讯/邮件，分类标签、星标收藏、【放入问题】一键带入对话）
   - 中间主区：对话流 + 后台任务卡片（深度调研/开发任务，实时输出日志，可手动停止）
   - 右栏：自定义数据看板（卡片组件，数据由 MCP 提供，可自由增删组件）

### 2. 轨迹 Trace 面板（重点）
- 独立 Tab，时序时间线（甘特样式），展示全部工具调用
- 每条记录：工具名称、调用参数、返回结果、耗时、执行时间
- 支持搜索、展开详情，完整回放 Agent 每一步动作

### 3. 顶部全局导航
对话 / 轨迹 / 我的关注 / 它对我的了解 / 全局语音开关

### 4. 语音交互
- 全局常驻语音开关，随时语音下达指令，支持连续对话、语音打断
- ASR 语音转文字、TTS 语音播报

---

## 四、后端四层架构
```
Runtime 任务运行时层
│  任务生命周期管理：启动/停止/暂停/超时回收
│  任务上下文隔离、并发控制
│  LangGraph 实例管理、MemorySaver 断点快照
├─ Middleware 中间件层
│  LLM链路中间件：Token统计、提示词注入
│  工具链路中间件：白名单校验、删除动作拦截、Trace埋点、异常捕获
├─ Core Agent 单智能体核心（LangGraph）
│  消息循环、工具路由、interrupt 删除确认断点
│  内置原生工具集 + MCP工具适配
└─ MCP 管理模块
    MCP商店、MCP进程启停、参数配置
    MCP工具转 BaseTool 适配器
（Multi-Agent 多智能体调度层 = V2 扩展，MVP 不做）
```

---

## 五、固定目录结构
```
nova-secretary/
├─ AGENTS.md
├─ FINAL_DEVELOPMENT_DOC.md
├─ ACCEPTANCE_TEST.md
├─ README.md
├─ .trae/rules/
├─ backend/
│  ├─ runtime/          # 任务运行时
│  ├─ middleware/       # 中间件
│  ├─ agent/            # LangGraph 核心
│  ├─ tools/            # 内置工具
│  ├─ mcp_manager/      # MCP 商店与管理
│  ├─ storage/          # SQLite
│  ├─ voice/            # ASR/TTS
│  ├─ server.py
│  ├─ pyproject.toml
│  └─ .env
├─ frontend/            # Tauri + Vue3
│  ├─ src/
│  │  ├─ floating-ball/
│  │  ├─ workbench/
│  │  ├─ trace/
│  │  ├─ mcp-store/
│  │  ├─ settings/
│  │  └─ voice/
│  └─ src-tauri/
└─ docs/
```

---

## 六、Agent 内置工具清单
> 所有工具统一经过 Middleware（Trace 埋点、白名单校验、删除拦截）

### 文件工具
- `file_read`：读取本地文件（txt/md/pdf/docx/xlsx/代码），白名单内
- `file_write` / `file_edit`：新建、增量修改文件，直接执行
- `file_open`：调用系统程序打开文件，直接执行
- `file_delete`：删除文件/文件夹，**唯一强制确认项**

### 图片工具（两条独立链路）
- `image_ocr`：OCR 提取图片文字（截图/附件/扫描件）
- `image_vl`：多模态视觉理解，解析 UI/流程图/草图/画面；独立开关，Agent 自动判断意图路由；VL 关闭时友好提示，不强行走 OCR
- `screen_capture`：截屏，直接执行，截图送入 VL/OCR

### 联网与系统
- `tavily_search`：联网搜索，开关可控
- `clipboard_read`：读取剪贴板，可选开关
- `shell_run`：白名单目录内执行 PowerShell/Shell
- `present`：汇总当前任务产出文件清单，输出交付物列表

---

## 七、MCP 商店
1. MCP 商店页面：浏览、安装、卸载、配置 MCP 服务
2. MCP 能力约定：
   - MCP 只负责拉取原始数据、返回资源路径；**文件解析、图片识别交给内置工具**，MCP 不做解析逻辑
   - 支持配置每个 MCP 的启动参数、环境变量（用户自定义 MCP 服务）
   - 已安装 MCP 自动注册为 Agent 工具，Agent 自主调用
   - 示例：邮件 MCP、日历 MCP、RSS 资讯 MCP、行情 MCP、GitHub MCP
3. MCP 调用权限：放行，Agent 自主调用
4. 技术：官方 Python `mcp` SDK；MCP 工具包装成 LangChain BaseTool 接入 LangGraph

---

## 八、LangGraph Agent 编排
### 两种任务形态自动识别
1. 普通问答：单次工具调用，快速响应
2. 深度任务：识别调研/开发/设计需求，自动创建后台长任务，Agent 自主链式调用工具持续迭代，持续输出日志，可随时停止

### Graph 节点流程
```
START → 思考规划节点 → 路由判断
  ├─ 无工具调用 → 输出回答 → END
  └─ 有工具 → 工具中间件
       ├─ 写入 Trace 开始日志
       ├─ 校验白名单路径
       ├─ 判断是否 file_delete
       │    ├─ 是：interrupt() 中断，返回待确认状态 → 前端弹窗 → 确认后 resume()
       │    └─ 否：放行执行工具
       ├─ 工具执行（内置/MCP）
       └─ 写入 Trace 结束日志 → 回到思考规划节点（循环）
```
- 用 `interrupt()` + `MemorySaver` 实现删除确认断点（LangGraph 原生能力）
- 异步 `astream` 适配 FastAPI 流式输出
- 多轮循环支持自主长任务

### 记忆
- 会话记忆 + 长期摘要记忆，SQLite 存储
- 自动 token 压缩；图片 base64 只在运行时传递，数据库只存摘要文本

### 模型
- OpenAI 兼容协议（ChatOpenAI 统一封装）
- 文本模型 + VL 视觉模型分开配置；支持 Ollama 本地 / DeepSeek / OpenAI

---

## 九、后端技术栈 & LangChain 组件
### 技术栈
| 层次 | 选型 |
|---|---|
| Web | FastAPI + Uvicorn + sse-starlette |
| 编排 | LangGraph（核心） |
| 模型封装 | langchain-openai（ChatOpenAI） |
| 工具 | langchain-core（@tool, BaseTool） |
| MCP | 官方 mcp SDK |
| 存储 | SQLite + aiosqlite |
| 文档解析 | pypdf / python-docx / openpyxl |
| 图片 | pillow |
| 语音 | 前端 ASR/TTS 或后端可选 |
| 配置 | pydantic-settings / python-dotenv |

### 使用的 LangChain 组件
1. `ChatOpenAI`（langchain-openai）：统一模型封装，文本 + VL 两个实例
2. `TavilySearchResults`（langchain-community）：内置联网工具
3. `SystemMessage / HumanMessage / AIMessage / ToolMessage`（langchain_core.messages）：消息结构（LangGraph 原生使用）
4. `@tool`（langchain_core.tools）：把内置函数包装成标准工具，自动生成 JSON schema
5. `BaseTool`：MCP 工具转接基类
6. `ChatPromptTemplate / PromptTemplate`：系统提示词模板
7. `RunnableConfig`：传递会话ID、trace_id、白名单等运行时配置

### 明确不用的 LangChain 内容
- ❌ 旧版 Agent（OpenAIToolsAgent / AgentExecutor）→ 编排交给 LangGraph
- ❌ LangChain RAG 全套（Chroma/FAISS）→ 当前无知识库需求
- ❌ LangSmith → 我们用自研本地 Trace
- ❌ LangChain 记忆类（ConversationBufferMemory 等）→ 记忆自研 SQLite
- ❌ 复杂 Chain → 流程交给 LangGraph

---

## 十、数据存储
### SQLite 表
- sessions：会话
- messages：消息记录
- memory_summary：记忆摘要
- trace_log：工具调用轨迹（Trace 面板数据源）
- mcp_config：MCP 配置
- whitelist_dirs：白名单目录
- app_config：系统配置
- tasks：后台任务状态
### 约束
- 密钥只在 .env，不入 sqlite
- 本地存储，不上传
- 大文件/base64 不入库，只存摘要
- Trace 记录所有工具调用（放行 + 待确认都记录）

---

## 十一、WebSocket 事件协议
前端 → 后端：
- `{"type":"user_message","message":""}`
- `{"type":"confirm_result","confirm_id":"","accepted":true/false}`（删除确认）
- `{"type":"control","action":"stop_task"}`（停止后台任务）

后端 → 前端：
- `{"type":"token","delta":""}`
- `{"type":"tool_status","tool_name":"","status":"running"/"done"}`
- `{"type":"delete_confirm","confirm_id":"","path":""}`（删除确认事件）
- `{"type":"task_log","task_id":"","log":""}`
- `{"type":"message","role":"assistant","content":""}`
- `{"type":"error","message":""}`

---

## 十二、分期开发计划
### 阶段0｜基座搭建
FastAPI + WebSocket、LangGraph 基础 Graph、SQLite 建表、Tauri + Vue 基础界面、基础对话
✅ 验收：前后端连通、流式对话、重启不丢

### 阶段1｜核心权限 + 内置工具
白名单机制、Middleware（Trace 埋点 + 白名单校验）、file_read/write/edit/open、删除确认（interrupt）、tavily、clipboard、shell_run、图片 OCR/VL 两链路 + 意图路由、后台任务 Runtime
✅ 验收：除删除外工具全部自主执行；删除弹确认；轨迹记录；VL/OCR 自动路由

### 阶段2｜MCP 商店 + 界面完善
MCP 管理器 + 商店 UI、MCP 工具接入、三栏工作台、悬浮球、全局语音、轨迹面板、看板、资讯雷达
✅ 验收：MCP 商店可装配置 MCP；Agent 调 MCP 工具；三栏 + 轨迹面板正常；语音

### 阶段3｜稳定性打磨
双平台差异、权限、超时、日志、优雅退出、任务并发控制、性能

### 阶段4（V2）｜Multi-Agent + Agentic RAG 扩展
Multi-Agent：规划师/文件操作员/调研员/审核员分工协作，架构预留接口
Agentic RAG（可选）：文档切片入库 Milvus 向量库，新增 RAG 检索工具，Agent 自主检索知识库，详见第十五章
> 两套扩展相互独立，可按需单独启用，互不依赖。

---

## 十五、Agentic RAG + Milvus（V2 可选扩展能力）
> 状态：**MVP 不做，V2 阶段按需开发**。当前 MVP 方案：Agent 需要文档内容时直接调用 `file_read` 读取本机文件（架构简单、够用）。

### 15.1 什么是 Agentic RAG
普通 RAG：用户提问 → 检索向量库片段 → 交给 LLM 回答。
Agentic RAG：把「检索」本身做成一个 Agent 可自主规划的工具。Agent 自己判断是否要检索、检索哪些文档、多次检索、调整关键词、对比多份资料，再综合回答。搭配 Milvus 向量数据库做持久向量存储。

### 15.2 适合用 RAG 的场景
- 大量私人文档/项目文档/技术笔记，希望 Agent 不用每次 `file_read`，直接在知识库检索
- 历史对话、设计方案、需求文档入库，Agent 自主翻资料再干活
- 上传一批参考资料，Agent 做方案时自主查阅参考库

### 15.3 后端方案（V2 开发）
1. 文档入库工具：扫描指定目录 → 切片 → Embedding 向量化 → 写入 Milvus
2. Embedding 模型配置：独立配置（本地/云端 embedding）
3. Milvus 向量库连接配置
4. 新增 RAG 检索工具：作为普通工具加入工具池，**统一走现有 Middleware 中间件 + Trace 轨迹系统**
5. Agent 系统提示词注入：允许 Agent 自主决定「直接 file_read 读原文件」还是「调 RAG 检索知识库」
6. RAG 检索工具权限：✅自主执行（与现有工具一致）
7. 新增依赖（V2 才加）：`pymilvus`、embedding 相关、`langchain`（如用其 text-splitter）

### 15.4 前端改动清单（V2 开发 RAG 时）
> 前端需要新增一个「知识库」能力入口，规划如下：

1. **新增「知识库」导航 Tab**（顶部导航 或 左栏资讯雷达并列）
   - 知识库列表：展示已建知识库（名称、文档数、向量数、更新时间）
   - 知识库卡片操作：新建、删除（删除需走系统删除确认流程）、编辑
2. **新建/配置知识库页**：
   - 选择来源目录（目录选择器，路径校验）
   - Embedding 模型配置选择
   - 向量库连接状态展示（Milvus 是否连通）
   - 入库触发按钮 + 入库进度条
3. **文档入库状态页**：
   - 待入库/已入库文档列表，切片进度、向量化进度
   - 单个文档的入库状态、失败重试
4. **检索测试面板**（可选）：
   - 输入 query，实时展示 RAG 检索命中的文档片段与相关性分数
   - 帮助验证知识库效果
5. **对话中的 RAG 检索展示**：
   - 当 Agent 调用 RAG 工具时，工具调用面板展示「检索了知识库X，命中N条」折叠信息
   - 命中片段可展开查看来源
6. **设置面板新增「知识库/RAG」配置区块**：
   - Milvus 连接（host/port/collection）、Embedding 模型、默认来源目录
   - RAG 开关（是否允许 Agent 使用 RAG 工具）

### 15.5 前端改动原则
- RAG 相关界面全部 V2 再加，MVP 不占界面
- 新增 Tab/页面沿用三栏工作台 + 深色科技风设计语言
- 前端只负责展示与配置，不直接连 Milvus/做 embedding，一切走后端 HTTP 接口
- 工具调用轨迹面板自动覆盖 RAG 检索调用（无需额外开发）

---

## 十三、给 TRAE 的启动指令
```
读取项目根目录 AGENTS.md、FINAL_DEVELOPMENT_DOC.md 和 .trae/rules/ 下全部SKILL规则。
项目名称NovaSecretary，跨平台桌面自主执行AI生产Agent。
技术栈：Tauri(Vue3) + FastAPI + LangGraph + MCP SDK + SQLite。
LangGraph：本项目MVP核心编排框架（Agent流程/循环/删除确认断点/后台长任务/状态保存全部基于它），已纳入开发范围。
权限规则：除文件删除需人工确认外，文件读写/编辑/打开/截屏/执行命令/联网/调MCP全部自主执行；目录白名单兜底。
后端四层架构：Runtime、Middleware、Core Agent(LangGraph)、MCP管理；Multi-Agent与Agentic RAG(Milvus)均为V2扩展，MVP不做。
从【阶段0：基座搭建】开始，先搭建FastAPI+WebSocket、LangGraph基础Graph、SQLite、Tauri+Vue基础界面，实现基础对话。
先输出阶段0任务清单、目录初始化命令、依赖清单，等待我确认，确认后再写代码。
```

---

## 十四、验收与交付规范
- 完整可运行代码 + Windows PowerShell / Mac zsh 双套启动命令 + 依赖安装步骤
- 密钥进 .env，禁止硬编码
- 双平台差异注释标明
- 新增功能先方案评审
- Bug 最小改动修复
- 交付前自测，等待验收
> 功能验证用 `ACCEPTANCE_TEST.md`，逐模块勾选。
