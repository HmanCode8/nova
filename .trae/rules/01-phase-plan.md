# SKILL：分期开发计划
技能描述：严格按顺序迭代NovaSecretary自主执行Agent，禁止跨阶段开发。

## 阶段0｜基座搭建（第一优先级）
目标：搭建骨架、打通WebSocket、基础Graph、SQLite、Tauri+Vue基础界面、基础对话
交付物：
1. FastAPI + Uvicorn + WebSocket 服务
2. LangGraph 基础 ReAct Graph
3. SQLite 建表（sessions/messages/app_config）
4. Tauri + Vue3 基础界面 + 流式对话
✅ 验收：前后端连通、流式对话、重启会话不丢

## 阶段1｜核心权限 + 内置工具（最重要）
目标：实现「除删除外全部自主执行」的权限模型 + 完整内置工具 + 轨迹
后端新增：
1. 目录白名单机制 + 路径校验
2. Middleware 中间件层：
   - Trace 埋点（所有工具调用记录开始/结束）
   - 白名单校验
   - file_delete 识别 → interrupt 中断等待确认
3. 内置工具：file_read / file_write / file_edit / file_open / file_delete / tavily_search / clipboard_read / shell_run / present / screen_capture / image_ocr / image_vl
4. 图片两链路 + Agent 意图路由（OCR 读文字 / VL 看图）
5. 后台任务 Runtime：任务启停、超时、上下文隔离
前端新增：
1. 基础对话界面（流式、工具调用展示）
2. 删除确认弹窗
3. Trace 轨迹记录展示（基础）
✅ 验收：除删除外工具全部自主执行无需确认；删除弹确认；轨迹记录所有调用；VL/OCR 自动路由

## 阶段2｜MCP 商店 + 界面完善
后端新增：
1. MCP 管理器：MCP商店、进程启停、参数配置
2. MCP 工具转 BaseTool 接入 LangGraph
前端新增：
1. MCP 商店 UI（浏览/安装/配置）
2. 三栏工作台（资讯雷达/对话任务/数据看板）
3. 悬浮球 + 全局语音
4. 轨迹面板完整版（时序时间线）
5. 看板组件、资讯雷达数据源
✅ 验收：MCP 商店可安装配置 MCP；Agent 调 MCP 工具；三栏工作台正常；悬浮球语音；轨迹面板回放

## 阶段3｜稳定性打磨
双平台差异、权限边界、超时回收、日志、优雅退出、任务并发控制、性能优化

## 阶段4（V2）｜Multi-Agent + Agentic RAG 扩展
Multi-Agent：规划师/文件操作员/调研员/审核员分工协作；架构预留接口，MVP 不做
Agentic RAG（可选）：文档切片入库 Milvus，新增 RAG 检索工具，Agent 自主检索知识库；MVP 用 file_read 读取本地文件，RAG 不作为 MVP 开发项
