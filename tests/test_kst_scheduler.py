"""
Тесты core/kst_scheduler.py — без внешних зависимостей, без сети.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core import kst_scheduler as ks

KST = ks.KST


# ── Базовые утилиты ──────────────────────────────────────────────────────────

def test_get_kst_now_is_aware():
    """get_kst_now() должен возвращать timezone-aware datetime в KST."""
    now = ks.get_kst_now()
    assert now.tzinfo is not None
    # Смещение KST = +9ч
    assert now.utcoffset() == timedelta(hours=9)


def test_get_kst_now_ahead_of_utc():
    """KST всегда на 9 часов впереди UTC."""
    now_kst = ks.get_kst_now()
    now_utc = datetime.now(timezone.utc)
    diff_hours = (now_kst.replace(tzinfo=None) - now_utc.replace(tzinfo=None)).total_seconds() / 3600
    assert abs(diff_hours - 9.0) < 0.1


def test_is_active_kst_hour_inside():
    """Время внутри окна → True."""
    dt = datetime(2026, 4, 14, 15, 0, 0, tzinfo=KST)  # 15:00 KST
    assert ks.is_active_kst_hour(dt) is True


def test_is_active_kst_hour_before():
    """До 09:00 KST → False."""
    dt = datetime(2026, 4, 14, 8, 59, 59, tzinfo=KST)
    assert ks.is_active_kst_hour(dt) is False


def test_is_active_kst_hour_after():
    """22:00 KST и позже → False (окно [9, 22))."""
    dt = datetime(2026, 4, 14, 22, 0, 0, tzinfo=KST)
    assert ks.is_active_kst_hour(dt) is False


def test_is_active_kst_hour_boundary_open():
    """09:00 KST ровно → входит в окно."""
    dt = datetime(2026, 4, 14, 9, 0, 0, tzinfo=KST)
    assert ks.is_active_kst_hour(dt) is True


def test_is_active_kst_hour_custom_window():
    """Кастомное окно 10–18 работает корректно."""
    dt_in  = datetime(2026, 4, 14, 13, 0, 0, tzinfo=KST)
    dt_out = datetime(2026, 4, 14, 9,  0, 0, tzinfo=KST)
    assert ks.is_active_kst_hour(dt_in,  start_hour=10, end_hour=18) is True
    assert ks.is_active_kst_hour(dt_out, start_hour=10, end_hour=18) is False


# ── kst_day_boundary_utc ─────────────────────────────────────────────────────

def test_kst_day_boundary_format():
    """Возвращает ISO 8601 строки с суффиксом Z."""
    start, end = ks.kst_day_boundary_utc()
    assert start.endswith("Z")
    assert end.endswith("Z")


def test_kst_day_boundary_span_24h():
    """Разница между граница дня ровно 24 часа."""
    start, end = ks.kst_day_boundary_utc()
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    dt_start = datetime.strptime(start, fmt).replace(tzinfo=timezone.utc)
    dt_end   = datetime.strptime(end,   fmt).replace(tzinfo=timezone.utc)
    assert (dt_end - dt_start) == timedelta(hours=24)


def test_kst_day_boundary_kst_midnight():
    """KST полночь = UTC 15:00 предыдущего дня."""
    ref = datetime(2026, 4, 14, 12, 0, 0, tzinfo=KST)  # 12:00 KST 14 апреля
    start, _ = ks.kst_day_boundary_utc(ref)
    # KST midnight 2026-04-14 = UTC 2026-04-13 15:00:00
    assert start == "2026-04-13T15:00:00Z"


def test_kst_day_boundary_contains_now():
    """Текущее время UTC должно быть внутри сегодняшней KST-границы."""
    start, end = ks.kst_day_boundary_utc()
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    dt_start = datetime.strptime(start, fmt).replace(tzinfo=timezone.utc)
    dt_end   = datetime.strptime(end,   fmt).replace(tzinfo=timezone.utc)
    now_utc  = datetime.now(timezone.utc)
    assert dt_start <= now_utc < dt_end


# ── distribute_uploads_kst ───────────────────────────────────────────────────

def test_distribute_empty():
    """Пустой список профилей → пустой результат."""
    assert ks.distribute_uploads_kst([]) == []


def test_distribute_single_profile():
    """Один профиль → один слот."""
    slots = ks.distribute_uploads_kst(["p1"])
    assert len(slots) == 1
    assert slots[0]["profile_id"] == "p1"
    assert "scheduled_at_utc" in slots[0]
    assert "scheduled_at_kst" in slots[0]


def test_distribute_100_profiles():
    """100 профилей → 100 уникальных слотов."""
    ids = [f"acc_{i:03d}" for i in range(100)]
    slots = ks.distribute_uploads_kst(ids, jitter_minutes=8)
    assert len(slots) == 100
    profile_ids_in_result = [s["profile_id"] for s in slots]
    assert sorted(profile_ids_in_result) == sorted(ids)


def test_distribute_all_unique_profiles():
    """Каждый профиль встречается в результате ровно один раз."""
    ids = ["a", "b", "c", "d", "e"]
    slots = ks.distribute_uploads_kst(ids)
    result_ids = [s["profile_id"] for s in slots]
    assert sorted(result_ids) == sorted(ids)


def test_distribute_sorted_by_time():
    """Слоты отсортированы по времени (scheduled_at_utc)."""
    ids = [f"p{i}" for i in range(20)]
    slots = ks.distribute_uploads_kst(ids)
    times = [s["scheduled_at_utc"] for s in slots]
    assert times == sorted(times)


def test_distribute_slots_in_window():
    """
    Все слоты попадают в активное KST-окно (09:00–22:00).
    Тест использует фиксированную дату — 10:00 KST (середина окна).
    """
    ref_kst = datetime(2026, 6, 15, 10, 0, 0, tzinfo=KST)
    ids = [f"p{i}" for i in range(30)]
    slots = ks.distribute_uploads_kst(ids, start_hour=9, end_hour=22, jitter_minutes=3, date_kst=ref_kst)

    fmt = "%Y-%m-%dT%H:%M:%SZ"
    win_start = datetime(2026, 6, 15,  9, 0, 0, tzinfo=KST).astimezone(timezone.utc)
    win_end   = datetime(2026, 6, 15, 22, 0, 0, tzinfo=KST).astimezone(timezone.utc)

    for s in slots:
        t = datetime.strptime(s["scheduled_at_utc"], fmt).replace(tzinfo=timezone.utc)
        assert win_start <= t < win_end, f"Slot out of window: {s['scheduled_at_kst']}"


def test_distribute_tomorrow_if_past_window():
    """Если время после 22:00 KST — слоты назначаются на завтра."""
    ref_kst = datetime(2026, 6, 15, 23, 0, 0, tzinfo=KST)  # 23:00 KST — уже прошло
    slots = ks.distribute_uploads_kst(["p1", "p2"], date_kst=ref_kst)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    tomorrow_kst_start = datetime(2026, 6, 16, 9, 0, 0, tzinfo=KST).astimezone(timezone.utc)
    for s in slots:
        t = datetime.strptime(s["scheduled_at_utc"], fmt).replace(tzinfo=timezone.utc)
        assert t >= tomorrow_kst_start, f"Expected tomorrow slot, got {s['scheduled_at_kst']}"


def test_distribute_utc_format():
    """scheduled_at_utc должен быть в формате ISO 8601 с суффиксом Z."""
    slots = ks.distribute_uploads_kst(["x"])
    assert slots[0]["scheduled_at_utc"].endswith("Z")
    # Должен парситься без ошибок.
    datetime.strptime(slots[0]["scheduled_at_utc"], "%Y-%m-%dT%H:%M:%SZ")


def test_distribute_kst_label_contains_kst():
    """scheduled_at_kst должен содержать 'KST'."""
    slots = ks.distribute_uploads_kst(["x"])
    assert "KST" in slots[0]["scheduled_at_kst"]


# ── kst_status_summary ───────────────────────────────────────────────────────

def test_kst_status_summary_keys():
    """kst_status_summary содержит все ожидаемые ключи."""
    s = ks.kst_status_summary()
    expected = {
        "kst_now", "utc_now", "active_window", "window_is_active",
        "window_start_kst", "window_end_kst", "next_open_utc", "minutes_until_open",
    }
    assert expected.issubset(s.keys())


def test_kst_status_summary_types():
    """Типы полей корректны."""
    s = ks.kst_status_summary()
    assert isinstance(s["window_is_active"], bool)
    assert isinstance(s["minutes_until_open"], int)
    assert s["minutes_until_open"] >= 0


def test_kst_status_summary_active_window_string():
    """active_window содержит 'KST'."""
    s = ks.kst_status_summary()
    assert "KST" in s["active_window"]


# ── next_active_window_start_utc ─────────────────────────────────────────────

def test_next_active_window_start_utc_returns_utc():
    """Возвращает UTC-aware datetime."""
    dt = ks.next_active_window_start_utc()
    assert dt.tzinfo == timezone.utc


def test_next_active_window_start_not_in_past():
    """next_active_window_start_utc никогда не раньше текущего момента (± 5 сек)."""
    dt = ks.next_active_window_start_utc()
    now = datetime.now(timezone.utc)
    assert dt >= now - timedelta(seconds=5)
