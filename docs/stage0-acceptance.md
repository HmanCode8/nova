# README 要点总结

- 该包是给 TRAE 开发 NovaSecretary 的工程模板：将 `nova-secretary` 文件夹作为项目根目录打开，在 TRAE SOLO 粘贴 README 中的启动指令，从【阶段0：基座搭建】开始（后端 WebSocket + LangGraph ReAct Agent + Vue 聊天页 + txt 读写工具），先出任务清单待确认再写代码。
- 技术定位：Mac + Windows 双桌面语音 AI 秘书，Electron + Vue + Python uv + LangChain + LangGraph ReAct，支持联网工具、MCP 邮件日历、本地 ASR/TTS、悬浮宠物与人工确认交互。
- 目录分工：`AGENTS.md` 与 `.trae/rules/`（01~09 号规则：分期计划、提示词模板、UI 规范、安全隐私、SQLite 存储、工具清单、人工确认、运行时中间层）为开发规则；`FINAL_DEVELOPMENT_DOC.md` 为主方案文档；`backend/` 为 Python 参考代码，`frontend-electron/` 待生成，`assets/` 放 Lottie 与图标，`docs/` 存文档与验收清单。
