# SKILL：人工确认交互规范（Human-in-the-loop）
技能描述：所有带副作用的工具，执行前暂停Agent，推送待确认事件到前端，用户手动确认后才执行

## 适用工具范围
默认（自主模式 autonomy_mode = true，默认值）：
- delete_file：删除文件/目录（唯一强制确认项，任何模式都不放行）
- run_shell：命令命中破坏性黑名单时降级为确认

自主模式关闭后，以下工具恢复逐一确认：
- write_file / write_project_files：写入/覆盖本地文件
- open_local_file：调用系统软件打开文档
- email_send：发送邮件
- calendar_create：新建日历事件
- run_shell：全部命令

## 交互流程
1. Agent调用带确认标记的工具
2. 工具先做硬校验（路径白名单、后缀黑名单、参数合法性）
3. 硬校验不通过：直接返回错误，不弹确认
4. 硬校验通过：暂停当前Agent执行流，通过WebSocket推送特殊事件到前端：
   ```json
   {
     "event": "human_confirm",
     "confirm_id": "uuid",
     "tool_name": "open_local_file",
     "preview_text": "即将打开文件：D:\\work\\需求文档.md",
     "params": {"file_path": "D:\\work\\需求文档.md"}
   }
   ```
5. 前端弹出确认卡片，展示预览文本 + 【确认执行】【取消】两个按钮
6. 用户点击按钮，前端回传WebSocket消息：
   ```json
   {
     "event": "confirm_result",
     "confirm_id": "uuid",
     "accepted": true/false
   }
   ```
7. 后端接收到结果：
   - 用户确认：执行真实工具逻辑，将返回结果继续送回Agent循环
   - 用户取消：工具返回「用户已取消本次操作」，Agent继续对话
8. 超时规则：3分钟内未收到用户响应，自动判定为取消，释放Agent状态，避免卡死

## 硬校验前置（必须无条件执行）
1. delete_file：禁止删除盘符根目录、系统目录、应用数据目录；目录必须显式 recursive
2. open_local_file / write_file：自主模式关闭时路径必须在目录白名单内；自主模式下忽略白名单
3. open_local_file：禁止打开exe/bat/cmd/ps1/com等可执行后缀
4. email_send：必须校验收件人、正文非空
5. calendar_create：必须校验标题、时间字段合法

## MVP边界
- MVP阶段仅支持鼠标点击按钮确认
- 语音确认功能（语音说「确认/取消」）作为后续扩展，语音模块完成后再接入
- 不实现批量确认、批量执行，单次操作单次确认
