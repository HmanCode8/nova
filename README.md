# NovaSecretary 项目使用说明

## 怎么用这个包给TRAE开发
1. 把整个 `nova-secretary` 文件夹作为TRAE项目根目录打开
2. 打开TRAE SOLO，直接粘贴下面的启动指令：
```
读取项目根目录 AGENTS.md 和 .trae/rules/ 下全部SKILL规则。
项目名称NovaSecretary，Mac + Windows双桌面语音AI秘书，Electron+Vue + Python uv + LangChain + LangGraph ReAct，支持LangChain联网工具、MCP邮件日历、本地语音ASR/TTS、悬浮宠物、人工确认交互。
我们从【阶段0：基座搭建】开始开发，先搭建后端websocket服务 + LangGraph基础ReAct Agent + Vue基础聊天页面，实现基础对话 + txt读写工具。
先输出阶段0任务清单、目录初始化命令、依赖清单，等待我确认，确认后再写代码。
```

## 目录说明
- `AGENTS.md`：项目全局开发规则，TRAE自动读取
- `.trae/rules/`：TRAE专属技能规则：
  - 01-phase-plan.md：分期开发计划
  - 02-prompt-templates.md：开发提示词模板
  - 03-ui-spec.md：UI科技风规范
  - 04-security-and-safety.md：安全隐私规范
  - 05-storage-spec.md：本地SQLite存储与记忆规范
  - 06-agent-tools-list.md：全部Agent工具清单
  - 08-human-confirm.md：人工确认交互规范
  - 09-runtime-middleware-spec.md：Runtime/State/Content/Store边界 + 自研中间层规范
- `FINAL_DEVELOPMENT_DOC.md`：最终版完整开发方案主文档（含需求梳理、技术选型、架构、工具清单、阶段计划、边界）
- `backend/`：Python Agent后端参考代码，包含Tavily搜索工具示例、Agent注册示例、存储模块示例
- `frontend-electron/`：前端空目录，TRAE会自动生成对应Vue+Electron代码
- `assets/`：Lottie动画、图标资源存放位置
- `docs/`：后续开发文档、验收清单存放位置
