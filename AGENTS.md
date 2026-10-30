# AGENTS.md - NovaSecretary 全局开发约束
项目名称：NovaSecretary
定位：跨平台（Windows + Mac）桌面自主执行 AI 生产 Agent
开发主体：TRAE SOLO 负责编写、调试、迭代全部代码
核心一句话：Agent 可以自主操作本机电脑，自由读写、新建、修改、打开文件、执行命令、联网、调用 MCP 来帮你完成任务；**唯独删除文件/文件夹必须人工确认**；全部动作留轨迹；内置 MCP 商店支持自由扩展能力。

## ✅ 项目能力清单
### 核心定位
1. 自主执行：Agent 直接在你本机工作目录执行任务，可连续多轮自主迭代产出交付物（HTML 原型、代码、文档、设计图），不需要每一步人工确认
2. 权限基调：除【文件删除】外，其余操作（读、写、新建、修改、打开文件、截屏、执行命令、联网、调 MCP）全部放行，Agent 自由执行
3. MCP 商店：内置 MCP 商店，可安装、卸载、配置 MCP 服务（邮件、日历、资讯、行情、GitHub 等），自定义配置 MCP 启动参数与环境变量
4. 轨迹面板：所有工具调用全程记录，界面提供 Trace 轨迹时间线，可完整回放 Agent 每一步动作

### MVP 核心功能
1. 对话 + 语音：文字对话、全局语音开关、语音下达指令、流式输出
2. 文件自主操作：读取、新建、编辑、打开本机文件（txt/md/pdf/docx/xlsx/代码），白名单目录内自由操作
3. 文件删除（唯一需确认）：删除文件/文件夹前，流程中断，弹出确认（点击/语音确认后才执行）
4. 图片两条链路：`image_ocr`（提取文字）+ `image_vl`（多模态看图，解析UI/流程图/草图），Agent 自动判断意图路由；VL 可单独开关
5. 联网搜索：Tavily 搜索，开关可控
6. 系统命令：白名单目录内执行 PowerShell/Shell 命令
7. MCP 扩展：MCP 商店 + MCP 工具自动接入 Agent
8. 后台长任务：深度调研/开发/设计任务，Agent 自主链式调用工具持续迭代，实时输出执行日志，可随时手动停止
9. 记忆：会话记忆 + 长期摘要记忆，本地 SQLite 存储，自动 token 压缩
10. 界面：桌面悬浮球 + 三栏工作台（资讯雷达/对话任务/数据看板）+ 轨迹面板

### 后续扩展（MVP 稳定后）
1. Multi-Agent 多智能体调度（规划师/文件操作员/调研员/审核员分工协作）
2. 更多可视化看板组件
3. 资源监控（CPU/磁盘）、任务优先级

### ❌ 明确禁止开发（MVP 及任何阶段）
1. 账号登录、云端同步、多人协作
2. 不受白名单约束的任意路径访问（必须路径白名单管控）
3. 上传用户文件/截图/对话记录到云端（除非用户主动配置第三方 API）
4. 文件删除绕过人工确认（删除是唯一不可绕过的人工确认项）
5. 不做操作系统级虚拟机沙盒（本 Agent 直接操作真实工作目录）

## ⚙️ 后端四层架构（严禁改动）
```
Runtime 任务运行时层       任务生命周期管理、后台长任务、LangGraph实例/断点管理
Middleware 中间件层        工具调用/LLM请求的统一钩子：Trace埋点、白名单校验、删除动作拦截
Core Agent 单智能体核心     LangGraph 编排：消息循环、工具路由、interrupt删除确认断点
MCP 管理模块               MCP商店、MCP进程启停、MCP工具转BaseTool适配
```
> Multi-Agent 多智能体调度层为 V2 扩展，MVP 不做，预留接口。

## 📐 硬性架构约束（严禁擅改）
1. 严格前后端分离：
   - Backend：Python FastAPI，Agent 编排（LangGraph）、工具、MCP、存储全部在后端
   - Frontend：Tauri(Vue3)，只负责 UI、窗口、语音采集、WebSocket 通信，不写 Agent 业务逻辑
2. Python 包管理器固定 uv；新增依赖输出 `uv add xxx`
3. 固定目录结构（见下）
4. 通信协议：前端 ↔ 后端用 WebSocket（流式输出、工具日志、轨迹事件、删除确认事件）+ HTTP（配置、MCP 管理）
5. 模型层：OpenAI 兼容协议（ChatOpenAI 统一封装），文本模型 + VL 视觉模型分开配置；支持 Ollama 本地 / DeepSeek / OpenAI
6. 跨平台：路径用 pathlib；Mac 权限（麦克风/屏幕录制）；打包 Windows exe + Mac dmg
7. 版本路线：MVP 用 Tauri + Vue3 直接开发；如需可保留 Electron 备选
8. 代码交付：完整可运行代码 + Windows PowerShell / Mac zsh 双套启动命令；密钥进 .env 禁止硬编码；双平台差异注释标明；新增功能先方案评审，确认后再写
9. Bug 修复：最小改动，不随意重构架构

## 固定目录结构
```
nova-secretary/
├─ AGENTS.md
├─ FINAL_DEVELOPMENT_DOC.md
├─ ACCEPTANCE_TEST.md
├─ README.md
├─ .trae/rules/            # TRAE 技能规则
├─ backend/
│  ├─ runtime/             # Runtime 任务运行时：任务启停、生命周期、超时
│  ├─ middleware/          # 中间件：Trace埋点、白名单校验、删除确认识别
│  ├─ agent/               # LangGraph 核心：graph构建、提示词、VL路由
│  ├─ tools/               # 内置原生工具
│  ├─ mcp_manager/         # MCP商店、进程管理、工具适配
│  ├─ storage/             # SQLite：会话、记忆、Trace、MCP配置、白名单
│  ├─ voice/               # ASR / TTS
│  ├─ server.py            # FastAPI 入口
│  ├─ pyproject.toml
│  └─ .env
├─ frontend/               # Tauri + Vue3
│  ├─ src/
│  │  ├─ floating-ball/    # 悬浮球
│  │  ├─ workbench/        # 三栏工作台
│  │  ├─ trace/            # 轨迹面板
│  │  ├─ mcp-store/        # MCP商店
│  │  ├─ settings/
│  │  └─ voice/
│  └─ src-tauri/           # Tauri 配置、窗口、托盘、热键
└─ docs/
```

## 交付流程
1. 收到需求 → 方案评审输出
2. 我确认方案 → 编写代码
3. 附带测试脚本、启动命令、验收标准
4. 自测通过交付，等待我验收
5. 验收不通过针对性修复，不扩需求
