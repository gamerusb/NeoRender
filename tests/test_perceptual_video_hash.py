from __future__ import annotations

from pathlib import Path

import pytest

from core import perceptual_video_hash as ph


@pytest.mark.asyncio
async def test_compare_videos_phash_skips_when_library_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ph, "perceptual_hash_available", lambda: False)
    out = await ph.compare_videos_phash(
        tmp_path / "orig.mp4",
        tmp_path / "rend.mp4",
        content_duration_sec=10.0,
        output_duration_sec=10.0,
    )
    assert out["perceptual_skipped"] is True
    assert out["perceptual_diff_pct"] is None


@pytest.mark.asyncio
async def test_compare_videos_phash_flags_too_similar(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ph, "perceptual_hash_available", lambda: True)

    async def _fake_frame(_path: Path, *, time_sec: float, timeout_sec: float = 60.0):
        return f"frame-{time_sec}".encode("utf-8")

    diffs = iter([10.0, 20.0, 15.0, 18.0])

    def _fake_pct(_a: bytes, _b: bytes):
        return next(diffs, 12.0)

    monkeypatch.setattr(ph._ff, "extract_video_frame_png_bytes", _fake_frame)
    monkeypatch.setattr(ph, "_phash_distance_pct", _fake_pct)

    out = await ph.compare_videos_phash(
        tmp_path / "orig.mp4",
        tmp_path / "rend.mp4",
        content_duration_sec=12.0,
        output_duration_sec=12.0,
        samples=4,
    )
    assert out["perceptual_skipped"] is False
    assert out["perceptual_too_similar"] is True
    assert isinstance(out["perceptual_warning"], str)
