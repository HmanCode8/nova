"""自研中间件层（FINAL_DEVELOPMENT_DOC 第四章）。

当前包含：
- tool_middleware：工具链路中间件，统一做白名单校验、删除确认拦截、Trace 埋点、异常捕获

后续扩展（V2）：LLM 链路中间件（token 统计、提示词注入）在此目录继续增加模块。
"""

from backend.middleware.tool_middleware import ToolMiddleware, build_middleware

__all__ = ["ToolMiddleware", "build_middleware"]
