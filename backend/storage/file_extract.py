"""上传文件解析：文本/代码抽取 + 图片 OCR（本地），结果缓存在临时目录。

约定（05-storage-spec.md）：
- 解析结果只用于「当前轮上下文」与前端预览，原始全文不写入 messages 表
- 消息入库仅保留 file_id + 文件名/大小/类型
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_TEXT_CHARS = 20000
PREVIEW_CHARS = 600
CACHE_SUFFIX = ".extract.json"

TEXT_SUFFIXES = frozenset(
    {
        ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".ini", ".cfg", ".conf",
        ".yaml", ".yml", ".toml", ".json", ".xml", ".html", ".htm", ".css", ".scss",
        ".js", ".jsx", ".ts", ".tsx", ".vue", ".py", ".java", ".kt", ".go", ".rs",
        ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rb", ".swift", ".m", ".sql",
        ".sh", ".bash", ".ps1", ".bat", ".cmd", ".dockerfile", ".gitignore", ".env",
    }
)
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"})

KIND_LABELS = {"text": "文本", "image": "图片", "other": "文件"}


def classify(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "other"


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("疑似二进制文件，无法按文本读取")
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(替换非法字节)"


def _cache_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + CACHE_SUFFIX)


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        _cache_path(path).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # 缓存失败不影响主流程


def _load_cache(path: Path) -> dict[str, Any] | None:
    cache = _cache_path(path)
    if not cache.is_file():
        return None
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def extract(path: Path, filename: str) -> dict[str, Any]:
    """解析文件内容（阻塞，调用方用 to_thread），结果写缓存。"""
    cached = _load_cache(path)
    if cached is not None:
        return cached

    kind = classify(filename)
    text = ""
    note = ""
    if kind == "text":
        try:
            text, encoding = _read_text(path)
            note = f"编码 {encoding}"
        except (ValueError, OSError) as exc:
            note = f"读取失败：{exc}"
    elif kind == "image":
        try:
            from backend.tools.screenshot_tools import run_ocr_sync

            lines = run_ocr_sync(path)
            text = "\n".join(lines)
            note = f"OCR 识别 {len(lines)} 行" if lines else "未识别到文字"
        except Exception as exc:
            note = f"OCR 失败：{exc}"
    else:
        note = "暂不支持该格式的自动解析，可先转为 txt/md 或截图后再上传"

    truncated = len(text) > MAX_TEXT_CHARS
    payload = {
        "kind": kind,
        "ext": path.suffix.lower(),
        "chars": len(text),
        "truncated": truncated,
        "text": text[:MAX_TEXT_CHARS],
        "note": note,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_cache(path, payload)
    return payload


def load(path: Path, filename: str) -> dict[str, Any]:
    return extract(path, filename)


def preview_of(extracted: dict[str, Any]) -> str:
    text = " ".join(str(extracted.get("text") or "").split())
    if not text:
        return str(extracted.get("note") or "")
    if len(text) > PREVIEW_CHARS:
        return text[:PREVIEW_CHARS] + "…"
    return text


def context_block(
    filename: str,
    size: int,
    extracted: dict[str, Any],
    file_id: str = "",
    per_file_limit: int = 4000,
    total_limit: int = 8000,
) -> str:
    """构造注入当轮上下文的附件片段（不进 sqlite）。"""
    kind = str(extracted.get("kind") or "other")
    label = KIND_LABELS.get(kind, "文件")
    text = str(extracted.get("text") or "").strip()
    note = str(extracted.get("note") or "").strip()

    header = f"【附件】{filename}（{label}，{size} 字节）"
    if file_id:
        header += f"\n【file_id】{file_id}"
    if not text:
        return f"{header}\n【解析说明】{note or '未能提取内容'}"
    body = text[:per_file_limit]
    if len(text) > per_file_limit:
        body += f"\n...[附件内容已截断，原长 {len(text)} 字符]"
    block = f"{header}\n【解析说明】{note}\n---\n{body}"
    return block[:total_limit]
