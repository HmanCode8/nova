# AGENTS.md - NovaSecretary 全局开发约束
项目名称：NovaSecretary
定位：Mac + Windows 跨平台私人桌面语音AI秘书
开发主体：TRAE SOLO 负责编写、调试、迭代全部代码
核心一句话：常驻桌面、支持语音/文字双输入，具备联网搜索、本地文档代码处理、邮件日历查询，像智能私人秘书；炫酷科技UI + 悬浮宠物。

## ✅ 项目能力清单
### MVP 能力（优先实现）
1. 对话模式：文字对话 + 按住麦克风语音对话（不做后台持续唤醒监听）
2. LLM：使用 OpenAI 兼容协议，可切换 Ollama本地模型 / DeepSeek / 其他支持Function Call的模型
3. 联网能力：集成 LangChain TavilySearchResults 联网搜索工具，设置面板可一键开关联网
4. 本地文件工具：读取、写入 txt / md；读取代码文件，辅助写代码、排查报错、解释工程、生成prompt/skill/开发文档
5. 系统工具：剪贴板读写、截图+OCR识别截图内容、调用系统默认程序打开本地文档（人工确认后执行）
6. MCP 工具：对接邮箱、日历MCP Server，查看今日邮件、今日日程（仅查看摘要；发送邮件、新建日程属于带副作用操作，强制人工确认弹窗）
7. 记忆：多会话隔离、会话内上下文、长期偏好记忆（记住我的代码风格、文档格式）
8. UI：科技深色对话面板（粒子背景、音频波形、卡片展示结果）；桌面悬浮宠物（idle / thinking / done 三套Lottie动画）
9. 全局快捷键唤起：Windows Alt+Space；macOS Option+Space
10. 托盘后台常驻，关闭窗口后后台保持运行
11. 人工确认机制：所有带副作用的工具（写文件、打开本地文档、发邮件、新建日程）执行前暂停Agent，推送确认卡片到前端，用户确认后才执行。

### 后续扩展（MVP稳定后再做，不提前开发）
1. 本地知识库 RAG：预留扩展工具 local_kb_search + backend/kb/ 模块，绑定文件夹做本地文档问答（MVP不做）
2. 更多 MCP 连接器（飞书、Notion等）：在 backend/mcp_client/ 新增服务适配器 + 注册工具即可，无需改架构
3. 可选唤醒词语音监听（高误触风险，后置）
4. 语音确认替代鼠标点击确认

### ❌ 明确禁止开发（任何阶段都不要主动实现）
1. 账号登录、云端同步、多人协作
2. MVP阶段不做自动发送邮件、自动回复邮件（必须人工确认）
3. 不做无限制GUI自动点击自动化（pyautogui）
4. 不做爬虫工具（除非我单独下发需求）
5. 不支持复杂Word、Excel解析；仅优先支持 md / txt / 代码文本

## ⚙️ Agent 编排与人工确认（最终决策）
1. Agent编排：使用 LangGraph 原生 StateGraph + create_react_agent，手写图节点编排，白盒可控。
2. 人工确认（Human-in-the-loop）：使用 LangGraph 原生 interrupt() + checkpointer 实现，不依赖 langchain.agents.middleware 高层中间件。用户侧体验与官方中间件一致，但事件结构自定义自由、中断时机可控、便于后续扩展语音确认。
3. 工具调用前置校验、权限拦截：自研统一工具钩子 tools/tool_hook.py，收口所有工具的校验与确认逻辑。
4. 上下文摘要压缩、token控制：Graph前置节点 + summarize_context 实现。
5. LLM调用重试、多模态图片base64处理：自研 agent/llm_adapter.py。
6. Runtime/State/Content/Store 边界与自研中间层职责详见 .trae/rules/09-runtime-middleware-spec.md。

## 📐 硬性架构约束（严禁擅自改动）
1. **严格前后端分离**
   - Backend：Python 独立 WebSocket 服务，所有Agent逻辑、工具调用、语音处理、MCP客户端全部放在后端
   - Frontend（Electron+Vue3）：只负责UI渲染、窗口管理、全局快捷键、托盘、麦克风采集、音频波形展示、WebSocket通信；**前端禁止写任何Agent推理、工具调度逻辑**
2. Python包管理器固定使用 uv，禁止直接使用 pip；新增依赖输出 `uv add xxx`
3. 固定目录结构，不要随意新增文件夹
```
nova-secretary/
├─ backend/               # Python Agent后端（独立websocket服务）
│  ├─ agent/              # LangGraph ReAct主逻辑、工具注册、system prompt
│  ├─ tools/              # 文件、剪贴板、截图OCR、tavily联网搜索
│  ├─ voice/              # faster-whisper ASR、piper TTS语音模块
│  ├─ mcp_client/         # MCP stdio客户端，对接邮件、日历MCP Server
│  ├─ server.py
│  ├─ pyproject.toml
│  └─ .env
├─ frontend-electron/     # Electron + Vue3前端
│  ├─ src/
│  │  ├─ floating-pet/    # 悬浮宠物窗口组件（Lottie动画）
│  │  ├─ chat-panel/      # 科技风语音对话面板（音频波形、粒子背景）
│  │  ├─ settings/        # 设置页：模型配置、API、联网开关、热键、语音、悬浮宠
│  │  └─ preload/
│  └─ electron-main/      # 窗口、全局热键、托盘、跨平台权限处理
├─ assets/                # Lottie动画、图标资源
└─ docs/                  # 需求文档、验收清单、补充资料
```
4. 通信协议：前端 ↔ Python后端 使用 WebSocket；流式输出、Agent思考日志、收音状态、TTS播报状态、宠物状态、结构化卡片数据全部走ws推送
5. 模型层规范
   - 使用 `langchain_openai.ChatOpenAI` 统一客户端，OpenAI兼容协议
   - 设置面板可配置：`base_url`、`api_key`、`model_name`、`temperature`
   - 模型必须支持 Function Call / Tool Call，否则Agent无法调用工具
   - 支持 Ollama 本地模型 `http://localhost:11434/v1`
6. 跨平台适配强制要求
   - 快捷键区分：Windows `Alt+Space`；macOS `Option+Space`
   - 兼容Mac沙盒权限：麦克风、屏幕录制、文件访问权限申请弹窗
   - 托盘、窗口置顶、拖拽、文件路径、换行、DPI缩放同时兼容Mac & Windows
   - 打包产物：Windows exe、macOS dmg
7. 版本路线
   - 当前开发路线：Electron + Vue 优先完成全部功能验证
   - Tauri2 仅作为后期迁移选项，**全部功能稳定验收通过后，再进行迁移**；迁移时保留全部Vue前端组件，仅替换外壳，Python后端完全不动
8. 代码交付规范
   - 每次开发交付完整可运行代码，附带 Windows PowerShell / Mac zsh 两套启动命令、依赖安装步骤
   - 密钥、配置全部放入 .env，禁止硬编码密钥
   - 涉及双平台差异，必须在注释中写明Mac、Windows各自坑点
   - 新增任何功能，先输出方案评审（改动文件、新增依赖、风险坑点、分步顺序），等待我确认，确认后再写代码
9. Bug修复原则：优先最小改动修复，不随意整体重构架构
10. Token控制规则：
    - 禁止将完整base64图片、大文件全文长期保存在消息记录中，避免多轮对话token持续膨胀
    - 图片首次识别后入库仅保存摘要+file_id标记，不持久保存base64
    - 大文件超过阈值时，入库仅保存摘要，需要细读时调用工具按需读取磁盘文件

## 📤 交付流程
1. 收到需求 → 方案评审输出
2. 我确认方案 → 编写代码
3. 附带独立测试脚本、启动命令、验收标准
4. 自测通过后交付，等待我验收
5. 验收不通过，针对性修复，不扩需求
