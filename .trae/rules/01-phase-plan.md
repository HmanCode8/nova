# SKILL：分期开发计划
技能描述：严格按顺序迭代NovaSecretary，禁止跨阶段开发。

## 阶段0｜基座搭建（第一优先级）
目标：搭建骨架、打通WebSocket、基础ReAct Agent、基础文件工具、存储基座
交付物：
1. uv初始化Python项目，启动WebSocket服务（FastAPI + Uvicorn）
2. LangGraph create_react_agent 基础ReAct Agent，确定图结构
3. SQLite存储基座：建表、init_db、会话/消息CRUD基础接口
4. Vue极简聊天页面，支持流式消息收发
5. 基础工具：read_txt、write_txt（write_txt带人工确认）
✅ 验收：前端发文字指令，Agent调用读写文件工具，流式返回结果；重启软件会话历史不丢失

## 阶段1｜MVP文字完整版（联网搜索 + 持久化存储 + 记忆 + 工具钩子）
目标：文字侧全部能力跑稳；暂不做悬浮宠、语音
后端新增：
- 剪贴板读写、截图OCR工具
- TavilySearchResults 联网搜索工具，设置面板增加联网总开关
- SQLite持久化：会话列表、聊天历史、全局设置读写
- 记忆模块：全局偏好记忆 + 会话记忆 + 前端记忆管理面板
- 自研统一工具钩子 tools/tool_hook.py：白名单校验、后缀黑名单、人工确认识别、返回值截断摘要
- 上下文摘要组件 summarize_context + Graph前置节点（记忆注入、token检查）
- llm_adapter 模型适配层（重试、多模态图片临时base64）
- WebSocket事件网关：事件分发（对话/人工确认/控制指令）、流式推送协议
前端新增：
- 主聊天窗口（会话切换侧边栏、加载历史消息、人工确认卡片渲染）
- 设置面板（模型配置、联网开关、自动记忆开关、目录白名单、文件大小上限）
- 托盘后台常驻（Mac+Windows兼容）
✅ 验收：文字对话，读代码文档、截图分析、联网搜索；带副作用工具弹出确认卡片；开关可控；重启软件设置与会话不丢失；上下文长对话自动摘要不爆token

## 阶段2｜悬浮宠物 + 全局快捷键（对标TRAE宝悬浮球）
Electron主进程新增：
1. 独立悬浮宠物窗口：frameless、transparent、alwaysOnTop、可拖拽、Alpha通道鼠标穿透（透明区域穿透，只有宠物本体点击生效）
2. 全局快捷键：Windows Alt+Space / macOS Option+Space，唤起聊天面板
3. 状态联动：Agent idle / thinking / done 三个状态推送，切换Lottie动画
✅ 验收：双平台桌面常驻悬浮宠物，快捷键一键打开对话面板

## 阶段2.5｜语音秘书模块（网上那种语音交互秘书效果）
后端 voice 模块：faster-whisper本地ASR + piper本地TTS
后端接入MCP Client，注册MCP工具：
- email_list_today：获取今日邮件摘要
- email_read：读取单封邮件全文
- calendar_list_today：获取今日日程、会议
- email_send：发送邮件（人工确认）
- calendar_create：新建日程（人工确认）
前端新增：
- 语音按钮、按住录音交互
- 音频波形可视化组件
- 语音播报状态展示
- 语音确认（后续扩展：语音说「确认/取消」恢复人工确认流程）
交互流程：按住麦克风说话 → ASR转文字 → Agent自动规划工具调用（可链式调用搜索+邮件+日程）→ 整理结果 → TTS朗读，同时面板卡片展示结构化结果
✅ 验收：语音提问：帮我看看今天邮件和日程，顺便搜一下相关新闻，Agent自动多工具调用，总结并语音播报

## 阶段3｜稳定性打磨优化
修复双平台差异化bug：Mac麦克风/录屏权限、沙盒、悬浮球拖拽偏移、置顶冲突、日志系统、优雅退出、开机自启（Mac登录项、Windows开机启动）、人工确认超时优化

## 阶段4（可选，稳定后）迁移 Tauri2
保留全部Vue前端组件；Rust重写窗口、热键、托盘、子进程拉起逻辑；Python后端完全不变，继续WebSocket通信；打包 Windows exe + Mac dmg
