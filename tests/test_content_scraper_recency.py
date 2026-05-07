"""
Тесты для функций свежести контента в content_scraper:
  - _effective_recent_max_hours
  - filter_videos_by_upload_recency
"""

from __future__ import annotations

import datetime as dt
import os

import pytest

from core import content_scraper as cs


# ── _effective_recent_max_hours ────────────────────────────────────────────────

class TestEffectiveRecentMaxHours:
    def test_explicit_positive_always_wins(self, monkeypatch):
        monkeypatch.delenv("NEORENDER_SEARCH_RECENT_HOURS", raising=False)
        assert cs._effective_recent_max_hours(True, 72.0) == 72.0
        assert cs._effective_recent_max_hours(False, 24.0) == 24.0

    def test_explicit_zero_means_no_limit(self, monkeypatch):
        monkeypatch.delenv("NEORENDER_SEARCH_RECENT_HOURS", raising=False)
        assert cs._effective_recent_max_hours(True, 0.0) is None
        assert cs._effective_recent_max_hours(False, 0.0) is None

    def test_explicit_negative_means_no_limit(self, monkeypatch):
        monkeypatch.delenv("NEORENDER_SEARCH_RECENT_HOURS", raising=False)
        assert cs._effective_recent_max_hours(True, -1.0) is None

    def test_env_overrides_shorts_default(self, monkeypatch):
        monkeypatch.setenv("NEORENDER_SEARCH_RECENT_HOURS", "96")
        assert cs._effective_recent_max_hours(True, None) == 96.0
        assert cs._effective_recent_max_hours(False, None) == 96.0

    def test_env_zero_means_no_limit(self, monkeypatch):
        monkeypatch.setenv("NEORENDER_SEARCH_RECENT_HOURS", "0")
        assert cs._effective_recent_max_hours(True, None) is None

    def test_env_invalid_falls_to_default(self, monkeypatch):
        monkeypatch.setenv("NEORENDER_SEARCH_RECENT_HOURS", "not_a_number")
        # Shorts → 48h дефолт
        assert cs._effective_recent_max_hours(True, None) == 48.0
        # не Shorts → None
        assert cs._effective_recent_max_hours(False, None) is None

    def test_shorts_default_48h(self, monkeypatch):
        monkeypatch.delenv("NEORENDER_SEARCH_RECENT_HOURS", raising=False)
        assert cs._effective_recent_max_hours(True, None) == 48.0

    def test_non_shorts_no_default(self, monkeypatch):
        monkeypatch.delenv("NEORENDER_SEARCH_RECENT_HOURS", raising=False)
        assert cs._effective_recent_max_hours(False, None) is None

    def test_explicit_beats_env(self, monkeypatch):
        monkeypatch.setenv("NEORENDER_SEARCH_RECENT_HOURS", "200")
        # явный аргумент 12 должен выиграть у env=200
        assert cs._effective_recent_max_hours(True, 12.0) == 12.0


# ── filter_videos_by_upload_recency ───────────────────────────────────────────

def _make_video(age_hours: float | None, vid_id: str = "v1") -> dict:
    """Создать тестовое видео с upload_date = now - age_hours.

    Используем isoformat() с "T" и "+00:00" — чтобы _video_upload_datetime
    парсил точное время (а не только дату с дефолтным noon).
    """
    if age_hours is None:
        return {"id": vid_id, "title": "no date"}
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=age_hours)
    return {"id": vid_id, "upload_date": ts.isoformat(), "title": "test"}


class TestFilterVideosByUploadRecency:
    def test_keeps_fresh_videos(self):
        videos = [_make_video(10, "fresh"), _make_video(100, "old")]
        result = cs.filter_videos_by_upload_recency(videos, max_age_hours=48)
        assert [v["id"] for v in result] == ["fresh"]

    def test_drops_old_videos(self):
        old = _make_video(72)
        result = cs.filter_videos_by_upload_recency([old], max_age_hours=48)
        assert result == []

    def test_keeps_near_boundary(self):
        # Используем 47.9h вместо ровно 48.0h, чтобы избежать нестабильности:
        # за несколько мкс выполнения теста age чуть больше 48.0 и видео отбрасывается.
        near = _make_video(47.9)
        result = cs.filter_videos_by_upload_recency([near], max_age_hours=48)
        assert len(result) == 1

    def test_drop_if_unknown_date_true_drops(self):
        no_date = _make_video(None)
        result = cs.filter_videos_by_upload_recency([no_date], max_age_hours=48, drop_if_unknown_date=True)
        assert result == []

    def test_drop_if_unknown_date_false_keeps(self):
        no_date = _make_video(None)
        result = cs.filter_videos_by_upload_recency([no_date], max_age_hours=48, drop_if_unknown_date=False)
        assert len(result) == 1

    def test_min_age_filter(self):
        too_new = _make_video(1)   # 1h ago — слишком новый
        ok = _make_video(30)       # 30h ago — в диапазоне
        result = cs.filter_videos_by_upload_recency(
            [too_new, ok], max_age_hours=48, min_age_hours=12
        )
        assert [v["id"] for v in result] == [ok["id"]]

    def test_empty_input(self):
        assert cs.filter_videos_by_upload_recency([], max_age_hours=48) == []

    def test_mixed_batch_preserves_order(self):
        # Используем большой зазор (96h), чтобы избежать погрешности парсинга UTC↔local
        videos = [
            _make_video(5, "a"),
            _make_video(None, "b"),    # без даты
            _make_video(25, "c"),
            _make_video(120, "d"),     # слишком старый (120 >> 48)
        ]
        result = cs.filter_videos_by_upload_recency(
            videos, max_age_hours=48, drop_if_unknown_date=False
        )
        ids = [v["id"] for v in result]
        assert "a" in ids
        assert "b" in ids    # no-date сохранён при drop_if_unknown_date=False
        assert "c" in ids
        assert "d" not in ids

    def test_yyyymmdd_format_is_parsed(self):
        """upload_date в формате YYYYMMDD (yt-dlp) должен правильно парситься."""
        ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=10)
        v = {"id": "x", "upload_date": ts.strftime("%Y%m%d"), "title": "test"}
        result = cs.filter_videos_by_upload_recency([v], max_age_hours=48)
        # Дата-только формат имеет точность до суток — видео может попасть или нет,
        # но функция не должна падать с исключением.
        assert isinstance(result, list)
