# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出 backend/dist/nova-backend/nova-backend.exe（onedir）。

构建命令（项目根目录执行）：
    uv run --project backend pyinstaller backend/nova-backend.spec --noconfirm `
        --distpath backend/dist --workpath backend/build

说明：
- 密钥不会打进安装包，打包态从 %APPDATA%/NovaSecretary/.env 读取。
- OCR / 语音 / 原生算子包必须整体 collect_all，否则缺 DLL 或模型文件。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve()  # backend/（SPECPATH 已指向 spec 所在目录）
datas = []
binaries = []
hiddenimports = []

# 带原生库或数据文件的包：整体收集（DLL、onnx 模型、espeak 数据等）
for package in (
    "rapidocr_onnxruntime",
    "onnxruntime",
    "faster_whisper",
    "ctranslate2",
    "av",
    "sounddevice",
    "piper",
    "uvicorn",
    "mcp",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# LangChain / LangGraph 大量运行时动态导入，静态分析抓不到
for package in ("langgraph", "langchain_core", "langchain_openai", "langchain_tavily"):
    hiddenimports += collect_submodules(package)

hiddenimports += [
    "aiosqlite",
    "anyio",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "websockets.asyncio",
    "httptools",
    "multipart",
    "python_multipart",
    "uvloop",
    "backend.env_loader",
    "backend.server_runtime",
    "backend.run_server",
]

a = Analysis(
    [str(ROOT / "run_server.py")],
    pathex=[str(ROOT.parent)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nova-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="nova-backend",
)
