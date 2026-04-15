"""
KST-aware distribution of YouTube upload tasks across accounts.

YouTube's anti-spam is timezone-sensitive — uploads at Korean night hours (23:00–08:00 KST)
look bot-like for Korean accounts. This module:
  1. Enforces active upload window: 09:00–22:00 KST (configurable)
  2. Spreads N tasks across the window with random jitter (no burst posting)
  3. Per-account daily upload limits checked against the DB

KST = UTC+9. All scheduled_at values are returned in UTC ISO 8601 (system-wide convention).
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

KST = timezone(timedelta(hours=9), "KST")

_DEFAULT_START_HOUR: int = 9   # 09:00 KST — Korean morning
_DEFAULT_END_HOUR:   int = 22  # 22:00 KST — Korean evening


# ── Time helpers ─────────────────────────────────────────────────────────────

def get_kst_now() -> datetime:
    """Current time as timezone-aware datetime in KST."""
    return datetime.now(KST)


def is_active_kst_hour(
    dt_kst: datetime | None = None,
    start_hour: int = _DEFAULT_START_HOUR,
    end_hour: int = _DEFAULT_END_HOUR,
) -> bool:
    """True if the given (or current) KST time is within the active upload window."""
    t = dt_kst or get_kst_now()
    return start_hour <= t.hour < end_hour


def _window_for_day(
    day: date,
    start_hour: int,
    end_hour: int,
) -> tuple[datetime, datetime]:
    """Return (window_start, window_end) as KST-aware datetimes for the given calendar day."""
    win_start = datetime(day.year, day.month, day.day, start_hour, 0, 0, tzinfo=KST)
    win_end   = datetime(day.year, day.month, day.day, end_hour,   0, 0, tzinfo=KST)
    return win_start, win_end


def next_active_window_start_utc(
    start_hour: int = _DEFAULT_START_HOUR,
    end_hour: int = _DEFAULT_END_HOUR,
) -> datetime:
    """
    UTC datetime of the next active window opening.
    - Inside window  → returns now (UTC)
    - Before window  → returns today's window start (UTC)
    - After window   → returns tomorrow's window start (UTC)
    """
    now_kst = get_kst_now()
    win_start, win_end = _window_for_day(now_kst.date(), start_hour, end_hour)

    if win_start <= now_kst < win_end:
        return datetime.now(timezone.utc)
    if now_kst < win_start:
        return win_start.astimezone(timezone.utc)
    # Past today's window → tomorrow
    return (win_start + timedelta(days=1)).astimezone(timezone.utc)


def kst_day_boundary_utc(reference_kst: datetime | None = None) -> tuple[str, str]:
    """
    Return (day_start_utc_iso, day_end_utc_iso) for the current (or given) KST calendar day.
    Used for daily upload count queries in SQLite.

    Example: KST 2026-04-14 → UTC ["2026-04-13T15:00:00Z", "2026-04-14T15:00:00Z")
    """
    ref = reference_kst or get_kst_now()
    day = ref.date()
    kst_midnight      = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=KST)
    kst_next_midnight = kst_midnight + timedelta(days=1)
    return (
        kst_midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        kst_next_midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ── Distribution ─────────────────────────────────────────────────────────────

def distribute_uploads_kst(
    profile_ids: list[str],
    *,
    start_hour: int = _DEFAULT_START_HOUR,
    end_hour: int = _DEFAULT_END_HOUR,
    jitter_minutes: int = 8,
    date_kst: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Assign one upload slot per profile across the active KST window.

    Profiles are shuffled randomly so the order of execution is not predictable.
    Each slot gets ± jitter_minutes of random offset (clamped to window bounds).

    If the current KST time is past today's window, slots are scheduled for
    tomorrow's window.

    Returns
    -------
    list of dicts sorted by scheduled_at ascending:
      {
        "profile_id":       str,
        "scheduled_at_utc": "2026-04-14T11:23:00Z",   # store in DB
        "scheduled_at_kst": "2026-04-14 20:23 KST",   # show in UI
      }
    """
    if not profile_ids:
        return []

    ref = date_kst or get_kst_now()
    win_start, win_end = _window_for_day(ref.date(), start_hour, end_hour)

    # If past today's window, move to tomorrow.
    if ref >= win_end:
        win_start += timedelta(days=1)
        win_end   += timedelta(days=1)

    # Earliest slot = max(window_start, now + 2 min) so tasks aren't immediately due.
    now_kst = get_kst_now()
    earliest = max(win_start, now_kst + timedelta(minutes=2))

    if earliest >= win_end:
        # No time left in window → shift to tomorrow.
        win_start += timedelta(days=1)
        win_end   += timedelta(days=1)
        earliest = win_start

    n = len(profile_ids)
    window_sec = (win_end - earliest).total_seconds()
    # Base spacing: spread tasks evenly across the remaining window.
    step_sec   = window_sec / n if n > 0 else window_sec
    jitter_sec = jitter_minutes * 60

    ids = list(profile_ids)
    random.shuffle(ids)

    slots: list[dict[str, Any]] = []
    for i, pid in enumerate(ids):
        base_kst = earliest + timedelta(seconds=i * step_sec)
        delta    = random.uniform(-jitter_sec, jitter_sec)
        slot_kst = base_kst + timedelta(seconds=delta)
        # Clamp: stay within [win_start, win_end).
        slot_kst = max(slot_kst, win_start)
        slot_kst = min(slot_kst, win_end - timedelta(minutes=1))

        slot_utc = slot_kst.astimezone(timezone.utc)
        slots.append({
            "profile_id":       pid,
            "scheduled_at_utc": slot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scheduled_at_kst": slot_kst.strftime("%Y-%m-%d %H:%M KST"),
        })

    slots.sort(key=lambda x: x["scheduled_at_utc"])
    return slots


# ── Status summary (for API) ──────────────────────────────────────────────────

def kst_status_summary(
    start_hour: int = _DEFAULT_START_HOUR,
    end_hour: int = _DEFAULT_END_HOUR,
) -> dict[str, Any]:
    """
    Return a human-readable status dict for the /api/kst/status endpoint.
    """
    now_kst = get_kst_now()
    active  = is_active_kst_hour(now_kst, start_hour, end_hour)
    win_start, win_end = _window_for_day(now_kst.date(), start_hour, end_hour)
    next_open_utc = next_active_window_start_utc(start_hour, end_hour)

    return {
        "kst_now":            now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
        "utc_now":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_window":      f"{start_hour:02d}:00–{end_hour:02d}:00 KST",
        "window_is_active":   active,
        "window_start_kst":   win_start.strftime("%Y-%m-%d %H:%M KST"),
        "window_end_kst":     win_end.strftime("%Y-%m-%d %H:%M KST"),
        "next_open_utc":      next_open_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "minutes_until_open": max(0, int((next_open_utc - datetime.now(timezone.utc)).total_seconds() / 60)),
    }
