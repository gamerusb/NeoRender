"""Тесты оркестратора: все внешние шаги замоканы."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core import database as db
from core import main_loop


@pytest.mark.asyncio
async def test_pipeline_processes_task_success(
    monkeypatch, temp_db_path: Path, tmp_path: Path, tiny_png: Path, tiny_mp4: Path
):
    await db.init_db(temp_db_path)
    out_mp4 = tmp_path / "rendered.mp4"
    out_mp4.write_bytes(b"x")

    async def mock_render(inp, ov, outp, **kw):
        Path(outp).parent.mkdir(parents=True, exist_ok=True)
        Path(outp).write_bytes(b"vid")
        return {"status": "ok", "output_path": str(Path(outp).resolve())}

    async def mock_meta(key, niche, **kw):
        return {
            "status": "ok",
            "title": "T",
            "description": "D",
            "comment": "C",
            "used_fallback": False,
        }

    async def mock_start(pid, session=None, **kw):
        return {"status": "ok", "ws_endpoint": "ws://mock/devtools/browser/x"}

    async def mock_stop(pid, session=None, **kw):
        return {"status": "ok"}

    async def mock_upload(ws, path, title, description, comment=None, **kw):
        return {
            "status": "ok",
            "video_url": "https://www.youtube.com/watch?v=testid",
            "comment_pinned": False,
        }

    monkeypatch.setattr(main_loop.luxury_engine, "render_unique_video", mock_render)
    monkeypatch.setattr(main_loop.ai_copywriter, "generate_metadata", mock_meta)
    monkeypatch.setattr(main_loop.adspower_sync, "start_profile", mock_start)
    monkeypatch.setattr(main_loop.adspower_sync, "stop_profile", mock_stop)
    monkeypatch.setattr(main_loop.youtube_automator, "upload_and_publish", mock_upload)

    cr = await db.create_task(
        str(tiny_mp4.resolve()),
        "profile_ads_1",
        db_path=temp_db_path,
    )
    tid = int(cr["id"])

    pipe = main_loop.AutomationPipeline(
        db_path=temp_db_path,
        overlay_png=tiny_png,
        render_dir=tmp_path / "renders",
        groq_api_key="dummy",
    )
    st = await pipe.start()
    assert st["status"] == "ok"
    await pipe.enqueue(tid)

    status = None
    for _ in range(100):
        await asyncio.sleep(0.05)
        g = await db.get_task_by_id(tid, db_path=temp_db_path)
        status = g["task"]["status"]
        if status in ("success", "error"):
            break

    await pipe.stop()
    assert status == "success", f"final status was {status}"


@pytest.mark.asyncio
async def test_pipeline_passes_manual_srt_to_render(
    monkeypatch, temp_db_path: Path, tmp_path: Path, tiny_png: Path, tiny_mp4: Path
):
    await db.init_db(temp_db_path)

    srt = tmp_path / "manual.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nhi\n", encoding="utf-8")

    async def mock_render(inp, ov, outp, **kw):
        Path(outp).parent.mkdir(parents=True, exist_ok=True)
        Path(outp).write_bytes(b"vid")
        assert kw.get("srt_path") == str(srt.resolve())
        return {"status": "ok", "output_path": str(Path(outp).resolve())}

    async def mock_meta(key, niche, **kw):
        return {
            "status": "ok",
            "title": "T",
            "description": "D",
            "comment": "C",
            "overlay_text": "O",
            "used_fallback": False,
        }

    async def mock_start(pid, session=None, **kw):
        return {"status": "ok", "ws_endpoint": "ws://mock/devtools/browser/x"}

    async def mock_stop(pid, session=None, **kw):
        return {"status": "ok"}

    async def mock_upload(ws, path, title, description, comment=None, **kw):
        return {"status": "ok", "video_url": "https://youtu.be/x", "comment_pinned": False}

    monkeypatch.setattr(main_loop.luxury_engine, "render_unique_video", mock_render)
    monkeypatch.setattr(main_loop.ai_copywriter, "generate_metadata", mock_meta)
    monkeypatch.setattr(main_loop.adspower_sync, "start_profile", mock_start)
    monkeypatch.setattr(main_loop.adspower_sync, "stop_profile", mock_stop)
    monkeypatch.setattr(main_loop.youtube_automator, "upload_and_publish", mock_upload)

    cr = await db.create_task(str(tiny_mp4.resolve()), "profile_ads_1", db_path=temp_db_path)
    tid = int(cr["id"])

    pipe = main_loop.AutomationPipeline(
        db_path=temp_db_path,
        overlay_png=tiny_png,
        render_dir=tmp_path / "renders",
        groq_api_key="dummy",
    )
    pipe.subtitle_srt_path = str(srt.resolve())

    assert (await pipe.start())["status"] == "ok"
    await pipe.enqueue(tid)

    status = None
    for _ in range(100):
        await asyncio.sleep(0.05)
        g = await db.get_task_by_id(tid, db_path=temp_db_path)
        status = g["task"]["status"]
        if status in ("success", "error"):
            break

    await pipe.stop()
    assert status == "success"


@pytest.mark.asyncio
async def test_pipeline_overlay_missing_marks_error(
    monkeypatch, temp_db_path: Path, tmp_path: Path, tiny_mp4: Path
):
    await db.init_db(temp_db_path)
    missing_overlay = tmp_path / "no_overlay.png"

    cr = await db.create_task(
        str(tiny_mp4.resolve()),
        "p1",
        db_path=temp_db_path,
    )
    tid = int(cr["id"])

    pipe = main_loop.AutomationPipeline(
        db_path=temp_db_path,
        overlay_png=missing_overlay,
        render_dir=tmp_path / "r",
    )
    await pipe.start()
    await pipe.enqueue(tid)

    for _ in range(80):
        await asyncio.sleep(0.05)
        g = await db.get_task_by_id(tid, db_path=temp_db_path)
        if g["task"]["status"] == "error":
            break

    await pipe.stop()
    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["status"] == "error"
    assert g["task"]["error_message"]


@pytest.mark.asyncio
async def test_enqueue_pending_from_db(temp_db_path: Path, tiny_mp4: Path):
    """Без запуска воркеров — только наполнение очереди из БД."""
    await db.init_db(temp_db_path)
    await db.create_task(str(tiny_mp4), "p1", db_path=temp_db_path)

    pipe = main_loop.AutomationPipeline(db_path=temp_db_path)
    r = await pipe.enqueue_pending_from_db()
    assert r["status"] == "ok"
    assert r["enqueued"] == 1
    assert pipe.queue.qsize() == 1


@pytest.mark.asyncio
async def test_start_enqueues_pending_from_db(temp_db_path: Path, tiny_mp4: Path):
    """При старте pipeline pending-задачи подхватываются в runtime-очередь."""
    await db.init_db(temp_db_path)
    await db.create_task(str(tiny_mp4), "p1", db_path=temp_db_path)

    pipe = main_loop.AutomationPipeline(db_path=temp_db_path)
    st = await pipe.start()
    try:
        assert st["status"] == "ok"
        assert int(st.get("enqueued_pending") or 0) >= 1
    finally:
        await pipe.stop()


@pytest.mark.asyncio
async def test_pipeline_starts_and_stops_hot_folder(
    monkeypatch, temp_db_path: Path, tmp_path: Path
):
    await db.init_db(temp_db_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEORENDER_HOT_FOLDER_INBOX", str(inbox))
    pipe = main_loop.AutomationPipeline(db_path=temp_db_path)
    st = await pipe.start()
    try:
        assert st["status"] == "ok"
        assert pipe.hot_folder.is_running is True
    finally:
        await pipe.stop()
        assert pipe.hot_folder.is_running is False


@pytest.mark.asyncio
async def test_pipeline_render_timeout_marks_error(
    monkeypatch, temp_db_path: Path, tmp_path: Path, tiny_png: Path, tiny_mp4: Path
):
    await db.init_db(temp_db_path)
    monkeypatch.setenv("NEORENDER_RENDER_TASK_TIMEOUT_SEC", "0.1")

    async def mock_render(*args, **kwargs):
        await asyncio.sleep(1.0)
        return {"status": "ok", "output_path": str((tmp_path / "never.mp4").resolve())}

    monkeypatch.setattr(main_loop.luxury_engine, "render_unique_video", mock_render)

    cr = await db.create_task(str(tiny_mp4.resolve()), "p1", render_only=True, db_path=temp_db_path)
    tid = int(cr["id"])
    pipe = main_loop.AutomationPipeline(db_path=temp_db_path, overlay_png=tiny_png, render_dir=tmp_path / "r")
    await pipe.start()
    await pipe.enqueue(tid)

    for _ in range(80):
        await asyncio.sleep(0.05)
        g = await db.get_task_by_id(tid, db_path=temp_db_path)
        if g["task"]["status"] == "error":
            break

    await pipe.stop()
    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["status"] == "error"
    assert "таймаут" in str(g["task"]["error_message"]).lower() or "завис" in str(g["task"]["error_message"]).lower()


@pytest.mark.asyncio
async def test_pipeline_retries_adspower_failure(
    monkeypatch, temp_db_path: Path, tmp_path: Path, tiny_png: Path, tiny_mp4: Path
):
    """При ошибке AdsPower задача уходит на ретрай (pending + scheduled_at), не в error."""
    await db.init_db(temp_db_path)

    async def mock_render(inp, ov, outp, **kw):
        Path(outp).parent.mkdir(parents=True, exist_ok=True)
        Path(outp).write_bytes(b"vid")
        return {"status": "ok", "output_path": str(Path(outp).resolve())}

    async def mock_meta(key, niche, **kw):
        return {"status": "ok", "title": "T", "description": "D", "comment": "C", "used_fallback": False}

    async def mock_start_fail(pid, session=None, **kw):
        return {"status": "error", "message": "AdsPower недоступен"}

    async def mock_stop(pid, session=None, **kw):
        return {"status": "ok"}

    monkeypatch.setattr(main_loop.luxury_engine, "render_unique_video", mock_render)
    monkeypatch.setattr(main_loop.ai_copywriter, "generate_metadata", mock_meta)
    monkeypatch.setattr(main_loop.adspower_sync, "start_profile_with_retry", mock_start_fail)
    monkeypatch.setattr(main_loop.adspower_sync, "stop_profile", mock_stop)
    # Форсируем 1 ретрай чтобы тест был быстрым
    monkeypatch.setattr(main_loop, "_RETRY_DELAYS", [1, 2, 5])

    cr = await db.create_task(str(tiny_mp4.resolve()), "profile_ads_1", db_path=temp_db_path)
    tid = int(cr["id"])

    pipe = main_loop.AutomationPipeline(
        db_path=temp_db_path, overlay_png=tiny_png, render_dir=tmp_path / "r"
    )
    # start() сам ставит pending-задачи в очередь — не вызываем enqueue повторно
    await pipe.start()

    # Ждём первой обработки (worker→fail→reschedule): статус вернётся в pending
    for _ in range(60):
        await asyncio.sleep(0.05)
        g = await db.get_task_by_id(tid, db_path=temp_db_path)
        st = g["task"]["status"]
        rc = g["task"]["retry_count"]
        if st == "pending" and rc >= 1:
            break
        if st == "error":
            break

    await pipe.stop()
    task = (await db.get_task_by_id(tid, db_path=temp_db_path))["task"]

    # Первая попытка → должна уйти на ретрай (pending со scheduled_at в будущем)
    assert task["status"] == "pending", f"expected pending (retry), got {task['status']}"
    assert task["scheduled_at"] is not None, "scheduled_at должен быть выставлен для ретрая"
    assert task["retry_count"] == 1, f"retry_count должен быть 1, got {task['retry_count']}"


@pytest.mark.asyncio
async def test_pipeline_exhausts_retries_to_error(
    monkeypatch, temp_db_path: Path, tmp_path: Path, tiny_png: Path, tiny_mp4: Path
):
    """После исчерпания всех ретраев задача финально уходит в error."""
    await db.init_db(temp_db_path)

    async def mock_render(inp, ov, outp, **kw):
        Path(outp).parent.mkdir(parents=True, exist_ok=True)
        Path(outp).write_bytes(b"vid")
        return {"status": "ok", "output_path": str(Path(outp).resolve())}

    async def mock_meta(key, niche, **kw):
        return {"status": "ok", "title": "T", "description": "D", "comment": "C", "used_fallback": False}

    async def mock_start_fail(pid, session=None, **kw):
        return {"status": "error", "message": "AdsPower недоступен"}

    async def mock_stop(pid, session=None, **kw):
        return {"status": "ok"}

    monkeypatch.setattr(main_loop.luxury_engine, "render_unique_video", mock_render)
    monkeypatch.setattr(main_loop.ai_copywriter, "generate_metadata", mock_meta)
    monkeypatch.setattr(main_loop.adspower_sync, "start_profile_with_retry", mock_start_fail)
    monkeypatch.setattr(main_loop.adspower_sync, "stop_profile", mock_stop)
    monkeypatch.setattr(main_loop, "_RETRY_DELAYS", [0, 0, 0])

    cr = await db.create_task(str(tiny_mp4.resolve()), "profile_ads_1", db_path=temp_db_path)
    tid = int(cr["id"])

    # Симулируем уже исчерпанные ретраи: принудительно ставим retry_count = max
    max_r = main_loop._max_retries()
    async with __import__("aiosqlite").connect(temp_db_path) as conn:
        await conn.execute(
            "UPDATE tasks SET retry_count = ? WHERE id = ?", (max_r, tid)
        )
        await conn.commit()

    pipe = main_loop.AutomationPipeline(
        db_path=temp_db_path, overlay_png=tiny_png, render_dir=tmp_path / "r"
    )
    # start() сам ставит pending-задачи в очередь — не вызываем enqueue повторно
    await pipe.start()

    for _ in range(100):
        await asyncio.sleep(0.05)
        g = await db.get_task_by_id(tid, db_path=temp_db_path)
        if g["task"]["status"] == "error":
            break

    await pipe.stop()
    task = (await db.get_task_by_id(tid, db_path=temp_db_path))["task"]
    assert task["status"] == "error", f"expected error after retries exhausted, got {task['status']}"
    assert task["retry_count"] == max_r, "retry_count не должен расти после исчерпания"
