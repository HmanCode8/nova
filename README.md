# NovaSecretary 项目使用说明

## 怎么用这个包给TRAE开发
1. 把整个 `nova-secretary` 文件夹作为TRAE项目根目录打开
2. 打开TRAE SOLO，直接粘贴下面启动指令（或主文档第十三节）：
```
读取项目根目录 AGENTS.md、FINAL_DEVELOPMENT_DOC.md 和 .trae/rules/ 下全部SKILL规则。
项目名称NovaSecretary，跨平台桌面自主执行AI生产Agent。
技术栈：Tauri(Vue3) + FastAPI + LangGraph + MCP SDK + SQLite。
权限规则：除文件删除需人工确认外，文件读写/编辑/打开/截屏/执行命令/联网/调MCP全部自主执行；目录白名单兜底。
后端四层架构：Runtime、Middleware、Core Agent(LangGraph)、MCP管理；Multi-Agent为V2扩展。
从【阶段0：基座搭建】开始，先搭建FastAPI+WebSocket、LangGraph基础Graph、SQLite、Tauri+Vue基础界面，实现基础对话。
先输出阶段0任务清单、目录初始化命令、依赖清单，等待我确认，确认后再写代码。
```

## 目录说明
- `AGENTS.md`：项目全局开发规则，TRAE自动读取
- `FINAL_DEVELOPMENT_DOC.md`：最终完整开发方案主文档
- `ACCEPTANCE_TEST.md`：功能验收清单
- `.trae/rules/`：TRAE 技能规则（分期计划、提示词、UI、安全、存储、工具、删除确认、Runtime/Middleware）
- `backend/`：Python 后端（FastAPI + LangGraph + MCP + SQLite）
- `frontend/`：Tauri + Vue3 前端（悬浮球、三栏工作台、轨迹面板、MCP商店）
- `docs/`：补充文档

## 核心权限说明（重要）
- 除【文件删除】外，Agent 所有操作（读、写、改、打开、截屏、命令、联网、MCP）自主执行
- 文件删除必须人工确认（点击/语音）
- 目录白名单兜底：Agent 只能访问配置的文件夹
- 所有动作记录到轨迹面板，可回放
