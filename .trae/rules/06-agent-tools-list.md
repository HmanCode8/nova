# SKILL：Agent 工具清单与权限规范
技能描述：定义本项目所有工具、权限规则、MCP扩展、轨迹埋点要求

## 内置原生工具（全部经过 Middleware）
【文件工具】
- file_read：读取本地文件（txt/md/pdf/docx/xlsx/代码），白名单内 ✅自主
- file_write：新建/写入文件 ✅自主
- file_edit：增量修改文件 ✅自主
- file_open：系统默认程序打开文件 ✅自主
- file_delete：删除文件/文件夹 ⛔强制人工确认

【图片工具（两套独立链路）】
- image_ocr：OCR提取图片文字（截图/附件/扫描件）✅自主
- image_vl：VL多模态看图，解析UI/流程图/草图/画面 ✅自主（独立开关）
- screen_capture：截屏 ✅自主，结果入VL/OCR

【联网与系统】
- tavily_search：联网搜索 ✅自主（开关可控）
- clipboard_read：读取剪贴板 ✅自主（可选开关）
- shell_run：白名单目录内执行PowerShell/Shell ✅自主
- present：汇总当前任务产出文件清单 ✅自主

## 图片链路路由规则（重点）
- 用户意图【读文字】→ 调 image_ocr
- 用户意图【看图/解析UI/流程图/草图】→ 调 image_vl
- VL 未开启时，识别到看图意图，友好提示「未开启视觉理解模型，仅支持OCR」，不强行走OCR返回"无文字"
- OCR 和 VL 物理隔离，不耦合

## MCP 工具（动态加载，来自 MCP 商店）
- MCP 只返回原始数据/资源路径，文件解析/图片识别交给内置工具
- MCP 工具包装成 BaseTool 接入 LangGraph，统一经过 Middleware + Trace
- MCP 调用权限：✅自主

## 扩展工具（MVP后开发，禁止提前实现）
Multi-Agent 子Agent工具、RAG检索、复杂看板组件

## 通用强制规则
1. 所有工具用 @tool 装饰器，LangGraph 加载
2. 所有工具（内置+MCP）统一经过 Middleware：Trace埋点、白名单校验、删除拦截
3. 除 file_delete 外，其余工具自主执行，不需要人工确认弹窗
4. 工具返回遵循 state/content 规范：长内容入库只存摘要
5. 工具列表注入 System Prompt，Agent 知道自己拥有哪些能力
