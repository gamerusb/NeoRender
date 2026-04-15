"""Тесты core/database.py — реальная SQLite через aiosqlite (без моков)."""

from __future__ import annotations

import pytest

from core import database as db


@pytest.mark.asyncio
async def test_init_db_creates_file(temp_db_path):
    r = await db.init_db(temp_db_path)
    assert r["status"] == "ok"
    assert "db_path" in r
    assert temp_db_path.exists()


@pytest.mark.asyncio
async def test_profile_crud(temp_db_path):
    await db.init_db(temp_db_path)

    u = await db.upsert_profile("adsp_1", "Имя", "idle", db_path=temp_db_path)
    assert u["status"] == "ok"

    lst = await db.list_profiles(db_path=temp_db_path)
    assert lst["status"] == "ok"
    assert len(lst["profiles"]) == 1
    assert lst["profiles"][0]["adspower_id"] == "adsp_1"

    st = await db.update_profile_status("adsp_1", "busy", db_path=temp_db_path)
    assert st["status"] == "ok"

    lst2 = await db.list_profiles(db_path=temp_db_path)
    assert lst2["profiles"][0]["status"] == "busy"


@pytest.mark.asyncio
async def test_task_lifecycle(temp_db_path):
    await db.init_db(temp_db_path)
    await db.upsert_profile("p1", "P", db_path=temp_db_path)

    c = await db.create_task("/a.mp4", "p1", db_path=temp_db_path)
    assert c["status"] == "ok"
    tid = c["id"]

    pending = await db.get_pending_tasks(db_path=temp_db_path)
    assert pending["status"] == "ok"
    assert len(pending["tasks"]) == 1

    await db.update_task_status(tid, "rendering", unique_video="/out.mp4", db_path=temp_db_path)
    pending2 = await db.get_pending_tasks(db_path=temp_db_path)
    assert len(pending2["tasks"]) == 0

    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["status"] == "rendering"
    assert g["task"]["unique_video"] == "/out.mp4"

    await db.update_task_status(tid, "success", db_path=temp_db_path)
    g2 = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g2["task"]["status"] == "success"


@pytest.mark.asyncio
async def test_task_template_roundtrip(temp_db_path):
    await db.init_db(temp_db_path)
    c = await db.create_task("/v.mp4", "p", template="news", db_path=temp_db_path)
    assert c["status"] == "ok"
    tid = c["id"]
    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["template"] == "news"


@pytest.mark.asyncio
async def test_task_subtitle_roundtrip(temp_db_path):
    await db.init_db(temp_db_path)
    c = await db.create_task("/v.mp4", "p", subtitle="  Привет  ", db_path=temp_db_path)
    assert c["status"] == "ok"
    tid = c["id"]
    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["subtitle"] == "Привет"
    lst = await db.list_tasks(limit=5, db_path=temp_db_path)
    row = next(t for t in lst["tasks"] if t["id"] == tid)
    assert row["subtitle"] == "Привет"


@pytest.mark.asyncio
async def test_task_error_message(temp_db_path):
    await db.init_db(temp_db_path)
    c = await db.create_task("/x.mp4", "prof", db_path=temp_db_path)
    tid = c["id"]
    await db.update_task_status(
        tid, "error", error_message="Сеть недоступна", db_path=temp_db_path
    )
    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["error_message"] == "Сеть недоступна"


@pytest.mark.asyncio
async def test_analytics_row(temp_db_path):
    await db.init_db(temp_db_path)
    r = await db.add_analytics_row(
        "https://youtube.com/watch?v=test",
        views=10,
        likes=1,
        status="active",
        db_path=temp_db_path,
    )
    assert r["status"] == "ok"

    u = await db.upsert_analytics(
        "https://youtube.com/watch?v=test",
        views=20,
        likes=2,
        status="active",
        db_path=temp_db_path,
    )
    assert u["status"] == "ok"

    one = await db.get_analytics_by_url(
        "https://youtube.com/watch?v=test", db_path=temp_db_path
    )
    assert one["status"] == "ok"
    assert one["analytics"]["views"] == 20


@pytest.mark.asyncio
async def test_invalid_task_status_rejected(temp_db_path):
    await db.init_db(temp_db_path)
    c = await db.create_task("/a.mp4", "p", db_path=temp_db_path)
    tid = c["id"]
    bad = await db.update_task_status(tid, "invalid_status", db_path=temp_db_path)
    assert bad["status"] == "error"


@pytest.mark.asyncio
async def test_tenant_isolation_same_adspower_id(temp_db_path):
    """Разные tenant_id — разные строки при одном adspower_id (как у разных клиентов SaaS)."""
    await db.init_db(temp_db_path)
    await db.upsert_profile("same_id", "Имя A", tenant_id="tenant-a", db_path=temp_db_path)
    await db.upsert_profile("same_id", "Имя B", tenant_id="tenant-b", db_path=temp_db_path)
    la = await db.list_profiles(tenant_id="tenant-a", db_path=temp_db_path)
    lb = await db.list_profiles(tenant_id="tenant-b", db_path=temp_db_path)
    assert len(la["profiles"]) == 1 and la["profiles"][0]["name"] == "Имя A"
    assert len(lb["profiles"]) == 1 and lb["profiles"][0]["name"] == "Имя B"


@pytest.mark.asyncio
async def test_recover_interrupted_tasks_moves_rendering_to_pending(temp_db_path):
    await db.init_db(temp_db_path)
    c1 = await db.create_task("/a.mp4", "p", db_path=temp_db_path)
    c2 = await db.create_task("/b.mp4", "p", db_path=temp_db_path)
    await db.update_task_status(c1["id"], "rendering", db_path=temp_db_path)
    await db.update_task_status(c2["id"], "uploading", db_path=temp_db_path)

    rec = await db.recover_interrupted_tasks(db_path=temp_db_path)
    assert rec["status"] == "ok"
    assert rec["recovered"] == 2

    g1 = await db.get_task_by_id(c1["id"], db_path=temp_db_path)
    g2 = await db.get_task_by_id(c2["id"], db_path=temp_db_path)
    assert g1["task"]["status"] == "pending"
    assert g2["task"]["status"] == "pending"


@pytest.mark.asyncio
async def test_task_status_transcribing_is_allowed(temp_db_path):
    await db.init_db(temp_db_path)
    c = await db.create_task("/x.mp4", "p", db_path=temp_db_path)
    tid = c["id"]
    up = await db.update_task_status(tid, "transcribing", db_path=temp_db_path)
    assert up["status"] == "ok"
    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["status"] == "transcribing"


@pytest.mark.asyncio
async def test_recover_interrupted_tasks_includes_transcribing(temp_db_path):
    await db.init_db(temp_db_path)
    c = await db.create_task("/x.mp4", "p", db_path=temp_db_path)
    tid = c["id"]
    await db.update_task_status(tid, "transcribing", db_path=temp_db_path)
    rec = await db.recover_interrupted_tasks(db_path=temp_db_path)
    assert rec["status"] == "ok"
    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["status"] == "pending"


# ─── Новые тесты: улучшения ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_task_has_created_at(temp_db_path):
    """created_at и updated_at должны заполняться при создании задачи."""
    await db.init_db(temp_db_path)
    c = await db.create_task("/v.mp4", "p", db_path=temp_db_path)
    g = await db.get_task_by_id(c["id"], db_path=temp_db_path)
    task = g["task"]
    assert task.get("created_at"), "created_at пустое"
    assert task.get("updated_at"), "updated_at пустое"


@pytest.mark.asyncio
async def test_updated_at_changes_on_status_update(temp_db_path):
    """updated_at должен обновляться при смене статуса."""
    import asyncio as _a
    await db.init_db(temp_db_path)
    c = await db.create_task("/v.mp4", "p", db_path=temp_db_path)
    tid = c["id"]
    g1 = await db.get_task_by_id(tid, db_path=temp_db_path)
    old_upd = g1["task"]["updated_at"]
    await _a.sleep(1.1)  # SQLite datetime('now') — секундная точность
    await db.update_task_status(tid, "rendering", db_path=temp_db_path)
    g2 = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g2["task"]["updated_at"] >= old_upd


@pytest.mark.asyncio
async def test_retry_task_resets_error_to_pending(temp_db_path):
    """retry_task: error → pending, error_message очищается."""
    await db.init_db(temp_db_path)
    c = await db.create_task("/v.mp4", "p", db_path=temp_db_path)
    tid = c["id"]
    await db.update_task_status(tid, "error", error_message="Сеть упала", db_path=temp_db_path)

    r = await db.retry_task(tid, db_path=temp_db_path)
    assert r["status"] == "ok"

    g = await db.get_task_by_id(tid, db_path=temp_db_path)
    assert g["task"]["status"] == "pending"
    assert not g["task"].get("error_message")


@pytest.mark.asyncio
async def test_retry_task_fails_for_non_error_status(temp_db_path):
    """retry_task не должен сбрасывать задачи не в статусе error."""
    await db.init_db(temp_db_path)
    c = await db.create_task("/v.mp4", "p", db_path=temp_db_path)
    tid = c["id"]
    # pending → retry должен вернуть error
    r = await db.retry_task(tid, db_path=temp_db_path)
    assert r["status"] == "error"
    assert "error" in r["message"]


@pytest.mark.asyncio
async def test_retry_task_not_found(temp_db_path):
    """retry_task несуществующей задачи возвращает error."""
    await db.init_db(temp_db_path)
    r = await db.retry_task(99999, db_path=temp_db_path)
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_create_tasks_batch(temp_db_path):
    """create_tasks_batch создаёт все задачи в одной транзакции."""
    await db.init_db(temp_db_path)
    rows = [
        {"original_video": f"/v{i}.mp4", "target_profile": "p", "render_only": True,
         "subtitle": f"sub{i}", "template": "ugc"}
        for i in range(5)
    ]
    r = await db.create_tasks_batch(rows, db_path=temp_db_path)
    assert r["status"] == "ok"
    assert r["created"] == 5
    assert len(r["ids"]) == 5
    # Все в pending
    pending = await db.get_pending_tasks(db_path=temp_db_path)
    assert len(pending["tasks"]) == 5


@pytest.mark.asyncio
async def test_create_tasks_batch_empty(temp_db_path):
    """Пустой batch — ok, 0 задач."""
    await db.init_db(temp_db_path)
    r = await db.create_tasks_batch([], db_path=temp_db_path)
    assert r["status"] == "ok"
    assert r["created"] == 0


@pytest.mark.asyncio
async def test_list_tasks_includes_timestamps(temp_db_path):
    """list_tasks возвращает created_at и updated_at."""
    await db.init_db(temp_db_path)
    await db.create_task("/v.mp4", "p", db_path=temp_db_path)
    lst = await db.list_tasks(db_path=temp_db_path)
    task = lst["tasks"][0]
    assert "created_at" in task
    assert "updated_at" in task


@pytest.mark.asyncio
async def test_claim_profile_job_for_run_atomic(temp_db_path):
    await db.init_db(temp_db_path)
    created = await db.create_profile_job(
        adspower_profile_id="p-claim",
        job_type="warmup",
        tenant_id="default",
        db_path=temp_db_path,
    )
    assert created["status"] == "ok"
    job_id = int(created["id"])

    first = await db.claim_profile_job_for_run(
        job_id,
        tenant_id="default",
        started_at="2026-01-01 00:00:00",
        db_path=temp_db_path,
    )
    second = await db.claim_profile_job_for_run(
        job_id,
        tenant_id="default",
        started_at="2026-01-01 00:00:01",
        db_path=temp_db_path,
    )
    assert first["status"] == "ok" and first["claimed"] is True
    assert second["status"] == "ok" and second["claimed"] is False
