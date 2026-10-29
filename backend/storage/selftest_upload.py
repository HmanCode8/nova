"""M9 自测：上传文件工具 + create_new_session 工具。

    $env:NOVA_DB_PATH = "$env:TEMP\\ns_m9\\nova.db"
    $env:PYTHONPATH = "e:\\nova-secretary"
    uv run --project backend python -m backend.storage.selftest_upload
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from backend.storage import file_extract, file_store, session_store
from backend.storage.db import db
from backend.storage.memory_store import CURRENT_SESSION
from backend.tools.session_tools import create_new_session
from backend.tools.upload_tools import list_uploaded_files, read_uploaded_file


async def main() -> None:
    if not os.environ.get("NOVA_DB_PATH"):
        print("拒绝执行：请先设置 NOVA_DB_PATH 指向隔离数据库。")
        sys.exit(2)

    await db.init_db()
    session_a = await session_store.create_session("上传测试 A")
    session_b = await session_store.create_session("上传测试 B")
    sid_a, sid_b = session_a["id"], session_b["id"]

    try:
        content = "NovaSecretary 上传测试\n第二行内容\n"
        record = await file_store.save_upload(sid_a, "notes.txt", content.encode("utf-8"))
        assert record["file_id"] and record["filename"] == "notes.txt"
        metas = await file_store.list_meta(sid_a)
        assert len(metas) == 1 and Path(metas[0]["stored_path"]).is_file()
        print("[PASS] 1. 上传落盘 + 元信息入库")

        token = CURRENT_SESSION.set(sid_a)
        try:
            listing = await list_uploaded_files.ainvoke({})
            assert "notes.txt" in listing, listing
            text = await read_uploaded_file.ainvoke({"file_id": record["file_id"]})
            assert "第二行内容" in text, text
        finally:
            CURRENT_SESSION.reset(token)
        print("[PASS] 2. list_uploaded_files / read_uploaded_file 正常")

        token = CURRENT_SESSION.set(sid_b)
        try:
            blocked = await read_uploaded_file.ainvoke({"file_id": record["file_id"]})
            assert "不属于当前会话" in blocked, blocked
        finally:
            CURRENT_SESSION.reset(token)
        print("[PASS] 3. 跨会话读取被拒绝")

        raw = await create_new_session.ainvoke({"title": "工具新建会话"})
        data = json.loads(raw)
        created = await session_store.get_session(data["session_id"])
        assert created and created["title"] == "工具新建会话"
        print("[PASS] 4. create_new_session 创建成功并返回 id")

        meta = await file_store.get_meta(record["file_id"], sid_a)
        info = file_extract.extract(Path(meta["stored_path"]), "notes.txt")
        assert info["kind"] == "text" and info["chars"] > 0, info
        assert "NovaSecretary" in file_extract.preview_of(info)
        print("[PASS] 5. 文本文件自动解析出摘要")

        from PIL import Image, ImageDraw, ImageFont

        image_path = Path(os.environ.get("TEMP", ".")) / "ns_upload_ocr.png"
        image = Image.new("RGB", (720, 220), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 64)
        draw.text((40, 70), "HELLO NOVA 2026", fill="black", font=font)
        image.save(image_path)

        image_record = await file_store.save_upload(
            sid_a, "ocr_test.png", image_path.read_bytes()
        )
        image_path.unlink(missing_ok=True)
        image_meta = await file_store.get_meta(image_record["file_id"], sid_a)
        image_info = file_extract.extract(Path(image_meta["stored_path"]), "ocr_test.png")
        assert image_info["kind"] == "image", image_info
        assert "NOVA" in str(image_info.get("text", "")).upper(), image_info
        print("[PASS] 6. 图片上传后自动 OCR")

        token = CURRENT_SESSION.set(sid_a)
        try:
            ocr_text = await read_uploaded_file.ainvoke({"file_id": image_record["file_id"]})
            assert "NOVA" in ocr_text.upper(), ocr_text
        finally:
            CURRENT_SESSION.reset(token)
        print("[PASS] 7. read_uploaded_file 支持图片 OCR")

        await session_store.add_message(
            sid_a,
            "user",
            "看看这张图",
            attachments=[
                {
                    "file_id": image_record["file_id"],
                    "filename": image_record["filename"],
                    "size": image_record["size"],
                    "kind": "image",
                }
            ],
        )
        rows = await session_store.list_messages(sid_a)
        last = rows[-1]
        assert last["attachments"] and last["attachments"][0]["file_id"] == image_record["file_id"], last
        print("[PASS] 8. 消息附件元信息可持久化并回读")

        await file_store.delete_session_files(sid_a)
        assert await file_store.list_meta(sid_a) == []
        assert not file_store.session_dir(sid_a).exists()
        print("[PASS] 9. 删除会话文件同时清理目录")
    finally:
        for sid in (sid_a, sid_b):
            await session_store.delete_session(sid)
        if "created" in locals():
            await session_store.delete_session(data["session_id"])
        await db.close()

    print("\nM9 全部自测通过")


if __name__ == "__main__":
    asyncio.run(main())
