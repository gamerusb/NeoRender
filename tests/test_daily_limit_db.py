"""
Тесты новых DB-функций дневного лимита (KST):
  - get_profile_daily_limit
  - set_profile_daily_limit
  - get_profile_daily_upload_count

Используют реальный aiosqlite — без моков.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core import database as db


# ── Вспомогательные ──────────────────────────────────────────────────────────

async def _make_profile(temp_db_path, pid: str = "test_profile") -> None:
    """Создаёт профиль в обеих таблицах: profiles и adspower_profiles."""
    await db.init_db(temp_db_path)
    await db.upsert_profile(pid, "Test", db_path=temp_db_path)
    await db.upsert_adspower_profile(
        adspower_profile_id=pid,
        profile_name="Test AdsPower",
        tenant_id="default",
        db_path=temp_db_path,
    )


async def _add_publish_job(
    temp_db_path,
    pid: str,
    status: str = "success",
    finished_at: str | None = None,
) -> None:
    """Добавляет profile_job типа publish с заданным статусом и finished_at."""
    import aiosqlite

    fin = finished_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with aiosqlite.connect(temp_db_path) as conn:
        await conn.execute(
            """
            INSERT INTO profile_jobs
                (tenant_id, adspower_profile_id, job_type, status, finished_at,
                 created_at, updated_at)
            VALUES ('default', ?, 'publish', ?, ?, datetime('now'), datetime('now'))
            """,
            (pid, status, fin),
        )
        await conn.commit()


# ── Тесты get_profile_daily_limit ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_limit_default_value(temp_db_path):
    """Свежий профиль имеет лимит 3 (DEFAULT в схеме)."""
    await _make_profile(temp_db_path)
    res = await db.get_profile_daily_limit("test_profile", db_path=temp_db_path)
    assert res["status"] == "ok"
    assert res["daily_upload_limit"] == 3


@pytest.mark.asyncio
async def test_daily_limit_profile_not_found(temp_db_path):
    """Несуществующий профиль — функция возвращает дефолтное значение 3."""
    await db.init_db(temp_db_path)
    res = await db.get_profile_daily_limit("ghost", db_path=temp_db_path)
    # row is None → limit = 3 (fallback в коде)
    assert res["status"] == "ok"
    assert res["daily_upload_limit"] == 3


# ── Тесты set_profile_daily_limit ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_daily_limit_ok(temp_db_path):
    """Установка лимита 5 — читается обратно как 5."""
    await _make_profile(temp_db_path)
    r = await db.set_profile_daily_limit("test_profile", 5, db_path=temp_db_path)
    assert r["status"] == "ok"
    assert r["daily_upload_limit"] == 5

    r2 = await db.get_profile_daily_limit("test_profile", db_path=temp_db_path)
    assert r2["daily_upload_limit"] == 5


@pytest.mark.asyncio
async def test_set_daily_limit_boundary_min(temp_db_path):
    """Минимальный допустимый лимит = 1."""
    await _make_profile(temp_db_path)
    r = await db.set_profile_daily_limit("test_profile", 1, db_path=temp_db_path)
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_set_daily_limit_boundary_max(temp_db_path):
    """Максимальный допустимый лимит = 20."""
    await _make_profile(temp_db_path)
    r = await db.set_profile_daily_limit("test_profile", 20, db_path=temp_db_path)
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_set_daily_limit_zero_rejected(temp_db_path):
    """Лимит 0 — ошибка."""
    await _make_profile(temp_db_path)
    r = await db.set_profile_daily_limit("test_profile", 0, db_path=temp_db_path)
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_set_daily_limit_21_rejected(temp_db_path):
    """Лимит 21 — ошибка (выше максимума)."""
    await _make_profile(temp_db_path)
    r = await db.set_profile_daily_limit("test_profile", 21, db_path=temp_db_path)
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_set_daily_limit_not_found(temp_db_path):
    """Профиль не существует в adspower_profiles — ошибка."""
    await db.init_db(temp_db_path)
    r = await db.set_profile_daily_limit("ghost", 5, db_path=temp_db_path)
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_set_daily_limit_overwrites(temp_db_path):
    """Повторная установка перезаписывает предыдущее значение."""
    await _make_profile(temp_db_path)
    await db.set_profile_daily_limit("test_profile", 7, db_path=temp_db_path)
    await db.set_profile_daily_limit("test_profile", 2, db_path=temp_db_path)
    r = await db.get_profile_daily_limit("test_profile", db_path=temp_db_path)
    assert r["daily_upload_limit"] == 2


# ── Тесты get_profile_daily_upload_count ─────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_count_zero_no_jobs(temp_db_path):
    """Нет job'ов → счётчик 0."""
    await _make_profile(temp_db_path)
    r = await db.get_profile_daily_upload_count("test_profile", db_path=temp_db_path)
    assert r["status"] == "ok"
    assert r["count"] == 0


@pytest.mark.asyncio
async def test_daily_count_one_today(temp_db_path):
    """Один успешный publish сегодня → count == 1."""
    await _make_profile(temp_db_path)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await _add_publish_job(temp_db_path, "test_profile", status="success", finished_at=now_utc)
    r = await db.get_profile_daily_upload_count("test_profile", db_path=temp_db_path)
    assert r["count"] == 1


@pytest.mark.asyncio
async def test_daily_count_ignores_error_jobs(temp_db_path):
    """Job'ы со статусом error не считаются."""
    await _make_profile(temp_db_path)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await _add_publish_job(temp_db_path, "test_profile", status="error", finished_at=now_utc)
    r = await db.get_profile_daily_upload_count("test_profile", db_path=temp_db_path)
    assert r["count"] == 0


@pytest.mark.asyncio
async def test_daily_count_ignores_yesterday(temp_db_path):
    """Job завершённый вчера (UTC) не попадает в счётчик текущего KST-дня."""
    await _make_profile(temp_db_path)
    # 36 часов назад — гарантированно за пределами любого KST-дня.
    old = (datetime.now(timezone.utc) - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await _add_publish_job(temp_db_path, "test_profile", status="success", finished_at=old)
    r = await db.get_profile_daily_upload_count("test_profile", db_path=temp_db_path)
    assert r["count"] == 0


@pytest.mark.asyncio
async def test_daily_count_multiple_today(temp_db_path):
    """Несколько успешных publish сегодня считаются все."""
    await _make_profile(temp_db_path)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(4):
        await _add_publish_job(temp_db_path, "test_profile", status="success", finished_at=now_utc)
    r = await db.get_profile_daily_upload_count("test_profile", db_path=temp_db_path)
    assert r["count"] == 4


@pytest.mark.asyncio
async def test_daily_count_ignores_warmup_jobs(temp_db_path):
    """Job'ы типа warmup (не publish) не считаются."""
    import aiosqlite

    await _make_profile(temp_db_path)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with aiosqlite.connect(temp_db_path) as conn:
        await conn.execute(
            """
            INSERT INTO profile_jobs
                (tenant_id, adspower_profile_id, job_type, status, finished_at,
                 created_at, updated_at)
            VALUES ('default', 'test_profile', 'warmup', 'success', ?, datetime('now'), datetime('now'))
            """,
            (now_utc,),
        )
        await conn.commit()
    r = await db.get_profile_daily_upload_count("test_profile", db_path=temp_db_path)
    assert r["count"] == 0


@pytest.mark.asyncio
async def test_daily_count_returns_boundary_dates(temp_db_path):
    """Ответ содержит day_start_utc и day_end_utc."""
    await _make_profile(temp_db_path)
    r = await db.get_profile_daily_upload_count("test_profile", db_path=temp_db_path)
    assert "day_start_utc" in r
    assert "day_end_utc" in r
    assert r["day_start_utc"].endswith("Z")
    assert r["day_end_utc"].endswith("Z")


@pytest.mark.asyncio
async def test_daily_count_isolated_by_profile(temp_db_path):
    """Заливки одного профиля не влияют на счётчик другого."""
    await _make_profile(temp_db_path, "profile_a")
    await _make_profile(temp_db_path, "profile_b")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await _add_publish_job(temp_db_path, "profile_a", status="success", finished_at=now_utc)
    await _add_publish_job(temp_db_path, "profile_a", status="success", finished_at=now_utc)

    r_a = await db.get_profile_daily_upload_count("profile_a", db_path=temp_db_path)
    r_b = await db.get_profile_daily_upload_count("profile_b", db_path=temp_db_path)
    assert r_a["count"] == 2
    assert r_b["count"] == 0


# ── Тест миграции (daily_upload_limit появляется в схеме) ────────────────────

@pytest.mark.asyncio
async def test_migration_adds_daily_upload_limit_column(temp_db_path):
    """После init_db колонка daily_upload_limit существует в adspower_profiles."""
    import aiosqlite

    await db.init_db(temp_db_path)
    async with aiosqlite.connect(temp_db_path) as conn:
        cur = await conn.execute("PRAGMA table_info(adspower_profiles)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "daily_upload_limit" in cols
