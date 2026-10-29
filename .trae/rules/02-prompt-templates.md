# SKILL：开发提示词模板
技能描述：新增模块、评审方案、修复bug时使用对应模板

### 模板A：新增普通后端Agent工具
当前阶段：【填入阶段】
需求：开发后端工具：____
作用：____
入参：____
返回：____
约束：
1. LangGraph @tool 装饰器实现，兼容LangChain工具注册体系
2. 高危操作增加二次确认弹窗逻辑
3. 文件放到 backend/tools/
4. 提供uv新增依赖、注册进Agent的代码、独立测试脚本

### 模板A2：接入LangChain预定义联网工具（Tavily专用）
当前阶段：阶段1
需求：接入TavilySearchResults联网搜索工具
要求：
1. 使用标准封装代码，backend/tools/tavily_search_tool.py
2. 设置面板增加开关，动态控制 WEB_SEARCH_ENABLED
3. 工具返回结构化数据，方便前端渲染卡片（标题、url、摘要）
4. 写入.env读取TAVILY_API_KEY，无key或者关闭联网时友好提示
5. ws向前端推送搜索结果结构化数据
6. 提供uv依赖、测试脚本

### 模板B：Electron前端窗口/UI开发
当前阶段：____
需求：开发前端功能：____
技术栈 Vue3 + Electron，代码放到 frontend-electron
要求：
1. 悬浮窗口必须配置：frameless transparent alwaysOnTop skipTaskbar
2. preload安全隔离，遵循IPC安全规范
3. 对接websocket接收Agent状态、工具结果
4. 区分Mac/Windows快捷键差异
5. 给出pnpm依赖、Mac(zsh)/Windows(powershell)调试启动命令

### 模板C：Bug修复
问题现象：【粘贴报错、现象】
运行平台：Windows / Mac
文件路径：
要求：最小改动修复，解释根因，标注Mac/Windows差异化坑点，不重构整体架构

### 模板D：方案评审（新增功能前必须先使用）
需求：____
请输出：
1. 方案选型
2. 需要改动的文件清单（后端/前端）
3. 新增依赖清单
4. Mac、Windows各自风险坑点
5. 分步实现顺序
等待我确认方案，再开始写代码

### 模板E：MCP工具对接（邮件/日历）
当前阶段：阶段2.5
需求：对接____ MCP Server，注册LangGraph工具
要求：
1. backend/mcp_client 模块，stdio方式连接MCP服务
2. Agent支持链式调用，例如同时查日程、邮件、联网搜索
3. 写邮件、新建日程强制二次确认弹窗
4. ws向前端推送结构化卡片数据

### 模板F：语音链路开发
当前阶段：阶段2.5
需求：本地语音链路 faster-whisper ASR + piper TTS
要求：
1. backend/voice模块，录音、识别、朗读
2. 交互：按住按钮录音，非后台持续唤醒监听
3. ws推送：收音状态、识别文本、播报状态
4. 适配Mac麦克风权限、Windows音频设备
5. uv依赖 + 独立测试脚本
