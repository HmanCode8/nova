"""MCP 商店与管理模块（FINAL_DEVELOPMENT_DOC 第七章）。

- catalog：商店目录（内置可安装清单）
- store：mcp_config 表读写
- manager：进程启停、工具发现、工具缓存
- adapter：MCP 工具 → LangChain BaseTool
"""

from backend.mcp_manager.manager import McpManager, get_manager

__all__ = ["McpManager", "get_manager"]
