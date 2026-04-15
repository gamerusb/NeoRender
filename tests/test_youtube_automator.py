"""Тесты youtube_automator: без реального YouTube/AdsPower."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import youtube_automator as yt


@pytest.mark.asyncio
async def test_upload_missing_video_file(tmp_path: Path):
    r = await yt.upload_and_publish(
        "ws://127.0.0.1:1",
        tmp_path / "missing.mp4",
        "title",
        "desc",
    )
    assert r["status"] == "error"
    assert "не найден" in r["message"].lower() or "найден" in r["message"].lower()


def test_typing_delay_range():
    for _ in range(20):
        d = yt._typing_delay()
        assert 50 <= d <= 120
