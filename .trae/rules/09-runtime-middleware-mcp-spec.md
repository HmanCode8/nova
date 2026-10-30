# SKILL：Runtime / Middleware / MCP / Multi-Agent 架构规范
技能描述：定义后端四层架构职责，明确每层实现范围与扩展预留

## 一、Runtime 任务运行时层（MVP 实现）
职责：
1. 任务生命周期管理：后台长任务的创建、启动、暂停、终止、超时回收
2. 任务上下文隔离：每个任务独立上下文（trace_id、会话ID、白名单快照、模型配置快照）
3. 并发控制：限制同时运行任务数量，避免资源耗尽
4. LangGraph 实例管理 + MemorySaver 断点快照管理（删除确认中断现场保存）
5. 后台任务接口：创建任务、任务列表、流式任务日志、停止任务

## 二、Middleware 中间件层（MVP 实现）
两类中间件，所有请求统一经过：
1. LLM 链路中间件
   - 系统提示词注入
   - Token 消耗统计、模型调用耗时记录
   - 上下文过滤
2. 工具链路中间件（核心）
   - 前置：Trace 开始日志、白名单路径校验、删除操作识别（触发 interrupt）
   - 后置：Trace 结束日志、工具异常捕获、错误格式化
   - 所有工具（内置 + MCP）统一经过，不单独为每个工具写校验

好处：新增工具、新增 MCP 工具，自动获得校验、轨迹、删除拦截能力，无需额外开发。

## 三、MCP 管理模块（MVP 实现）
1. MCP 商店：浏览、安装、卸载、配置 MCP 服务（命令、参数、环境变量）
2. MCP 进程管理：启动、停止、状态监控（用 psutil）
3. MCP 协议：官方 Python mcp SDK，stdio 通信
4. MCP 工具适配：把 MCP 暴露的工具包装成 LangChain BaseTool，接入 LangGraph
5. MCP 约定：MCP 只返回原始数据/资源路径，文件解析/图片识别交给内置工具
6. 所有 MCP 工具统一经过 Middleware（校验 + Trace + 删除拦截）

## 四、Multi-Agent 多智能体调度层（V2 扩展，MVP 不做）
预留接口，后续支持：
- 角色 Agent 池：规划师 Planner / 文件操作员 FileOperator / 调研员 Researcher / 审核员 Reviewer
- 主调度 Agent 拆解子任务、分发给子 Agent、汇总结果
- 子 Agent 各司其职，互相传递结果
MVP 阶段：单智能体（LangGraph 单 Graph）即可满足核心需求，不做多Agent

## 五、LangGraph 关键能力使用
1. interrupt() + resume()：删除确认断点
2. MemorySaver：Graph 断点状态保存（仅运行时快照，与业务 Trace 分开）
3. astream：异步流式输出，适配 FastAPI
4. 多轮循环：支持自主长任务持续迭代

## 六、四层与 LangChain 组件关系
- LangGraph = 编排核心（Runtime 管理其实例）
- Middleware = 自研拦截钩子，横穿 LLM/工具
- MCP = 官方 SDK 提供能力，转 BaseTool 接入 Graph
- LangChain = 组件库（消息结构、@tool、ChatOpenAI、Tavily），不用于编排

## 分层边界（严禁混用）
- Runtime 只做任务调度，不做业务决策
- Middleware 只做拦截/校验/埋点，不承载 Agent 决策
- 工具逻辑只做执行，不自带权限判断（权限由 Middleware 统一处理）
- Agent Graph 只做流程编排，调用工具时由 Middleware 拦截管控
