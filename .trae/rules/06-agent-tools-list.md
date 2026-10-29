# SKILL：Agent 工具清单与权限规范
技能描述：定义本项目所有可用ReAct工具、优先级、高危标记、MVP边界

## MVP 工具列表（必须实现）
【文件工具】
read_file：读取文本/代码文件（只读，无副作用）
write_file：写入文本文件（人工确认，覆盖前必须等待用户确认）
list_dir：浏览目录文件
open_local_file：使用系统默认程序打开本地文档
  - 前置校验：路径必须在白名单目录内；拦截exe/bat/ps1/cmd/com等可执行后缀
  - 校验通过后暂停Agent执行，推送待确认事件到前端，用户点击确认才执行；用户取消则终止操作
  - Windows使用os.startfile，macOS使用open命令

【网络】
tavily_web_search：联网搜索，受全局联网开关控制，关闭后不可调用

【系统剪贴板】
clipboard_read：读取剪贴板
clipboard_write：写入剪贴板

【截图OCR】
take_screenshot：截图
ocr_image：图片文字识别

【MCP 邮件日历】
email_list_today：查询今日邮件摘要
email_read_detail：读取单封邮件
calendar_list_today：查询今日日程
email_send：发送邮件（人工确认）
calendar_create：新建日程（人工确认）

【记忆工具（Agent自主管理记忆）】
add_session_memory
delete_session_memory
add_global_memory
delete_global_memory

【上传文件配套】
read_uploaded_file：读取本会话上传的临时文件
list_uploaded_files：列出本会话已上传文件

【上下文与会话】
create_new_session
summarize_context：自动压缩历史上下文摘要

## 扩展工具（MVP完成后才开发，现阶段禁止实现）
run_shell、git系列、open_browser、open_local_app、pdf_read、excel_read_simple、local_kb_search、audio_transcribe_local

## 通用强制规则
1. 所有工具使用 @tool 装饰器，LangGraph create_react_agent 加载
2. 带人工确认标记的工具，执行前必须推送待确认事件到前端，等待用户手动选择确认/取消
3. 工具返回结构化文本，方便LLM理解 + 前端渲染卡片
4. 工具之间可以链式调用（Agent自动规划：搜索 → 读文件 → 整理文档）
5. 工具全部在Python后端运行，前端不实现工具逻辑
6. 工具列表会注入System Prompt，Agent知道自己拥有哪些能力
7. 所有带副作用的工具（写文件、发邮件、新建日程、打开文件）强制走人工确认流程
