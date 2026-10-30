# SKILL：本地持久化存储规范
技能描述：控制项目数据持久化，Mac+Windows双平台

## 存储选型
使用 aiosqlite + SQLite3，异步非阻塞；单文件数据库。
- Windows: %APPDATA%/NovaSecretary/nova.db
- macOS: ~/Library/Application Support/NovaSecretary/nova.db

## 数据表
1. sessions：会话表（id, title, created_at, updated_at）
2. messages：消息表（id, session_id, role, content, tool_name, tool_result, created_at）
   - 注意：不存大原文/base64，只存摘要/文本
3. memory_summary：记忆摘要表（id, session_id, memory_text, created_at, updated_at）
4. trace_log：工具调用轨迹表（id, task_id, session_id, tool_name, params, result, status, duration_ms, created_at）
   - **所有工具调用（放行/待确认/失败）都记录**，供轨迹面板回放
5. mcp_config：MCP配置表（id, name, command, args, env_json, enabled, risk_level, require_confirm）
6. whitelist_dirs：白名单目录表（id, path, created_at）
7. app_config：系统配置表（id, config_json）
8. tasks：后台任务表（id, session_id, prompt, status, created_at, updated_at, result）

## 记忆规范
1. 会话记忆 + 长期摘要记忆，自动 token 压缩
2. 记忆抽取由 LLM 提炼关键信息，不存全部原文
3. 记忆本地存储，不上传；可导出/清空

## Token / Content 控制
1. 禁止把完整 base64、大文件全文长期存 messages
2. 图片 base64 只在运行时临时传递，入库只存识别后的文本摘要
3. 大文件超过阈值时，入库只存摘要 + 引用标记，需要细读时调用工具按需读取
4. 后台长任务：日志、结果同样遵守摘要规则，不无限堆原文

## 强制规则
1. 密钥（API Key、MCP Secret）严禁写入 sqlite，只能 .env
2. 所有数据库操作只在 Python 后端执行
3. 后端启动自动建表；极简迁移
4. 提供接口：会话CRUD、记忆管理、Trace查询、MCP配置、白名单管理、任务管理、导出/清空数据
5. 并发保护：异步锁，避免多消息并发写损坏数据库

## 禁止行为
❌ 上传数据库/聊天记录到远程服务器
❌ 把密钥/凭证存入数据库
❌ 前端直接访问 sqlite
