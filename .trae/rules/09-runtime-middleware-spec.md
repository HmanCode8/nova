# SKILL：Runtime / State / Content / Store 边界与中间层规范
技能描述：界定LangGraph运行时三大概念边界，以及本项目自研轻量中间层职责

## 一、概念对齐
1. Content：消息内的文本数据字段（BaseMessage.content），是数据，不是存储容器。
   - 工具读取的文件正文、搜索结果、邮件正文属于content
   - write_file待写入大段content仅作为工具参数，不持久存入对话消息
2. State：LangGraph图运行时容器，随Graph执行生命周期，核心key为 messages。
   - state内的messages是送入LLM的上下文，存在token上限控制
   - 长content允许临时进入state供本轮推理；本轮结束后持久化仅保留摘要+file_id
   - 人工确认事件以轻量标记放入state，禁止携带大体积content
   - 会话重启时，state由SQLite精简历史消息初始化，不自动回填历史全文/base64
3. Store：LangGraph内置KV存储
   - ✅ MVP决策：不使用LangGraph Store。记忆由自研SQLite表（session_memory/global_memory）管理
   - ✅ 记忆注入：Graph起始节点主动查询sqlite记忆，组装后注入state.messages
   - ❌ 不依靠Store自动注入上下文，避免隐式上下文膨胀

## 二、流转铁律
- 长期记忆 ≠ state；需要才加载进state，用完不长期霸占state
- 原始文件大content：生命周期 = 单次工具调用 → 本轮state临时使用；不绑定会话历史
- 工具返回长内容写入持久化前自动摘要压缩；summarize_context定期压缩久远对话，控制state总token上限
- human_confirm事件载荷轻量化，只携带动作类型和必要参数，不携带大文本

## 三、LangChain Middleware 选型说明（重要）
本项目MVP不使用 `langchain.agents.middleware` 体系（配套 create_agent 的高层Agent中间件钩子）。
原因：项目需要精细控制LangGraph State、自定义流式事件结构、自由编排节点流程。
对应能力替代方案（效果一致，控制权更高）：
1. 工具调用人工确认（Human-in-the-loop）：使用 LangGraph 原生 interrupt() + checkpointer
2. 工具调用前置校验、权限拦截：自研统一工具钩子 tool_hook.py
3. 上下文摘要压缩、token控制：Graph前置节点 + summarize_context
4. LLM调用重试、多模态图片base64处理：自研 llm_adapter

> 结论：用户侧体验与官方Middleware完全一致，但手写方案事件结构自定义自由、中断时机可控、调试直观、便于后续扩展（如语音确认）。

## 四、自研轻量中间层规划
> MVP不引入第三方中间件服务（Redis、MQ、Nginx、Celery等），全部使用内联轻量中间层。

| 中间层模块 | 位置 | 核心作用 |
| ---- | ---- | ---- |
| WebSocket事件网关 | server.py ws路由 | 前端事件 <-> LangGraph Graph 协议转换、事件分发（对话/人工确认/控制指令）、流式推送 |
| Graph前置上下文节点 | agent/agent_graph.py | 会话启动加载记忆、组装system prompt、token检查、自动摘要 |
| 工具调用拦截钩子 | tools/tool_hook.py | 所有工具统一前置校验、识别是否需要人工确认、返回值后置处理（截断/摘要）、异常捕获 |
| 消息持久化适配层 | storage/session_store.py | Runtime State消息结构 <-> SQLite存储结构转换；写入自动摘要瘦身，加载还原精简消息 |
| LLM模型适配层 | agent/llm_adapter.py | 统一封装OpenAI兼容接口，兼容Ollama本地/云端API，多模态图片临时base64处理 |
| MCP协议适配器 | mcp_client/ | Agent工具参数 <-> MCP JSON-RPC stdio协议互转 |

### 设计原则
1. 所有中间层都是内联同步逻辑，不引入独立服务进程
2. 中间层职责单一：只做转换、校验、转发，不承载Agent业务决策
3. 业务Agent图逻辑与底层通信、存储、协议细节通过中间层解耦
4. 后续需要异步任务时才考虑引入Redis等重型中间件

## 四.5、后续扩展：自研 Middleware 规划（对标 LangChain 官方 Middleware）
> MVP 不引入 middleware 机制，能力由独立节点/钩子实现。稳定后抽象自研中间件体系，插拔式开关。

对齐的 LangChain 原生钩子点位：
`before_agent → before_model → wrap_model_call → wrap_tool_call → after_model → after_agent`

计划实现的自研中间件（对标关系）：
1. ToolConfirmMiddleware（wrap_tool_call）对标 HumanInTheLoopMiddleware：副作用识别、触发interrupt人工确认
2. ContextSummarizeMiddleware（before_agent/after_model）对标 SummarizationMiddleware：token统计、自动摘要
3. ToolParamValidateMiddleware（wrap_tool_call）对标 ValidationMiddleware：白名单/黑名单/参数校验
4. RetryErrorMiddleware（wrap_model_call/wrap_tool_call）对标 ErrorHandlingMiddleware：重试、异常捕获、错误包装
5. LoggingMiddleware（全点位）对标 LoggingMiddleware：全链路结构化日志

> 可选第三方：TokenCountMiddleware、ReadOnlyGuardMiddleware、CacheMiddleware（引入Redis时考虑）

设计原则：中间件仅对现有逻辑抽象封装，底层仍是 LangGraph 原生 StateGraph + interrupt，不切换回 create_agent 黑盒；每个中间件可单独开关，插拔式组合。

## 五、WebSocket事件协议（前端交互依赖）
前端事件 -> 后端：
- {"type":"user_message","session_id":"","message":""}
- {"type":"confirm_result","confirm_id":"","accepted":true/false}
- {"type":"control","action":"stop"/"cancel"}

后端 -> 前端：
- {"type":"token","delta":"流式文本片段"}
- {"type":"tool_status","tool_name":"","status":"running"/"done"}
- {"type":"human_confirm","confirm_id":"","action":"open_local_file","preview_text":"","params":{}}
- {"type":"message","role":"assistant","content":""}
- {"type":"error","message":""}
