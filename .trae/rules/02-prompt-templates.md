# SKILL：开发提示词模板
技能描述：新增模块、评审方案、修复bug时使用对应模板

### 模板A：新增内置工具
当前阶段：【填入阶段】
需求：开发后端工具：____
作用：____
入参：____
返回：____
约束：
1. 使用 @tool 装饰器，兼容LangChain工具注册体系
2. 必须在 middleware 的 Trace 埋点中记录
3. 如果涉及文件操作，必须做白名单路径校验
4. 如果是删除操作，必须走 interrupt 人工确认流程
5. 提供 uv 新增依赖、注册进 Agent 的代码、独立测试脚本

### 模板B：前端组件开发
当前阶段：____
需求：开发前端功能：____
技术栈 Tauri + Vue3，代码放在 frontend/src
要求：
1. 与科技深色风格统一
2. 对接 websocket 接收 Agent 事件（token/工具状态/删除确认/任务日志）
3. 区分 Mac/Windows 差异
4. 给出 pnpm 依赖、Mac(zsh)/Windows(powershell) 调试启动命令

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
3. 新增依赖
4. Mac、Windows各自风险坑点
5. 分步实现顺序
等待我确认方案，再开始写代码

### 模板E：MCP接入
当前阶段：阶段2
需求：接入____ MCP Server，注册进Agent
要求：
1. 使用官方 mcp SDK，backend/mcp_manager 模块
2. MCP 工具包装成 BaseTool 接入 LangGraph
3. MCP 只返回原始数据/资源路径，解析逻辑交给内置工具
4. MCP 工具统一经过 middleware 校验 + Trace 埋点
5. 提供 MCP 配置、测试脚本

### 模板F：图片OCR/VL路由
当前阶段：阶段1
需求：实现 image_ocr / image_vl 两链路 + 意图路由
要求：
1. image_ocr：OCR文字识别（本地OCR引擎）
2. image_vl：VL多模态看图，独立开关、独立模型配置
3. Agent 系统提示词教它区分：要读文字→OCR；要看图解析→VL
4. VL 未开启时，识别看图意图后友好提示，不强行走 OCR 返回"无文字"
5. 图片 base64 只在运行时传递，不入库，只存摘要文本
