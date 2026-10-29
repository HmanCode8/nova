# SKILL：本地持久化存储规范
技能描述：控制项目数据持久化逻辑，Mac+Windows双平台

## 存储选型
使用 aiosqlite + SQLite3，异步非阻塞，适配websocket服务；无需额外数据库服务。
数据库文件位置遵循系统应用数据目录规范，不要直接放在项目源码文件夹。
- Windows: %APPDATA%/NovaSecretary/nova.db
- macOS: ~/Library/Application Support/NovaSecretary/nova.db

## 数据表定义
1. sessions 会话表
   id TEXT PRIMARY KEY (uuid)
   title TEXT
   created_at DATETIME
   updated_at DATETIME

2. messages 消息表（注意：不存储大原文/base64，只存摘要与引用标记）
   id TEXT PRIMARY KEY (uuid)
   session_id TEXT -> sessions.id
   role TEXT (system / user / assistant / tool)
   content TEXT  # 仅存精简摘要或对话文本，禁止存大段文件原文/base64
   tool_name TEXT NULL
   tool_result TEXT NULL  # 仅存截断后的工具结果摘要
   file_id TEXT NULL      # 若关联上传文件，存file_id引用
   created_at DATETIME

3. session_memory 会话记忆表
   id TEXT PRIMARY KEY
   session_id TEXT
   memory_text TEXT
   created_at TEXT
   updated_at TEXT

4. global_memory 全局记忆表
   id TEXT PRIMARY KEY
   memory_text TEXT
   created_at TEXT
   updated_at TEXT

5. uploaded_file_meta 上传文件元信息表
   id TEXT PRIMARY KEY
   session_id TEXT
   file_id TEXT
   filename TEXT
   stored_path TEXT
   created_at TEXT

6. app_config 全局配置表（单行）
   id INTEGER PRIMARY KEY AUTOINCREMENT
   config_json TEXT  # 模型配置、联网开关、自动记忆开关、目录白名单、文件大小上限等

## 记忆管理规范
本项目记忆全部本地存储，分三类：全局偏好记忆、会话记忆、原始对话消息，不上传云端。
1. 原始对话消息：存messages表，作为基础上下文；消息累积过长时自动摘要压缩。
2. 会话级记忆（session_memory）：绑定单个会话，记录本会话内用户约定、偏好；每轮Agent推理结束，由LLM判断是否新增/更新；每次推理前读取并注入system prompt。
3. 全局记忆（global_memory）：跨全部会话生效，记录长期固定偏好。
控制规则：
- 设置面板提供【自动记忆】总开关；关闭后不再自动生成新记忆，已有记忆保留
- 前端提供记忆管理面板：查看、编辑、单条删除、一键清空全部记忆
- 记忆抽取由LLM完成，只提炼关键信息，不直接存储全部聊天原文
- 记忆和密钥隔离；密钥只放.env，绝不入sqlite

## Content / Token 控制规范
1. 禁止将完整base64图片、大文件全文长期保存在messages记录中，避免多轮对话token持续膨胀。
2. 图片处理：首次识别临时转base64送入多模态模型，拿到OCR/理解结果后，入库仅保存 `[图片 file_id:xxx]` + 摘要，丢弃base64；只有用户主动要求重新看图时才重新读取本地图片构造base64。
3. 文本文件处理：小文件（阈值约2000token）可保留原文；超过阈值则首次读取后生成摘要，消息内只保留摘要+file_id引用；需要细读时调用read_uploaded_file按需读取磁盘。
4. 工具调用的返回内容（文件全文等）仅作为本轮LangGraph state临时数据，不直接写入持久化message；入库仅保存摘要。
5. summarize_context组件会合并压缩久远对话，进一步控制token。

## 强制规则
1. API Key、Tavily密钥、MCP授权Secret严禁写入sqlite，只能读取.env
2. 所有数据库操作只在Python后端执行；前端只通过websocket/后端接口读写配置、会话
3. 后端启动自动执行建表逻辑；只做极简迁移，不做复杂ORM
4. 提供接口：新建会话、切换会话、加载历史消息、删除会话、清空全部数据、导出会话为md/json
5. 数据隔离：会话独立隔离；Agent记忆绑定会话 + 全局偏好分开
6. 并发保护：使用异步锁，避免websocket多消息同时写入导致数据库损坏
7. MVP不做加密，后续可按需扩展本地AES加密

## 禁止行为
❌ 自动上传数据库、聊天记录到任何远程服务器
❌ 把密钥、凭证存入数据库
❌ 前端直接访问sqlite文件
❌ 自动同步到云端
