"""finalize_downloaded_video_path — расширение по сигнатуре; upload_date Shorts."""

from __future__ import annotations

from pathlib import Path

from core import content_scraper as cs


def test_finalize_adds_mp4_when_no_extension(tmp_path: Path):
    bare = tmp_path / "HHDI"
    # минимальная сигнатура ISO MP4 (ftyp)
    bare.write_bytes(bytes.fromhex("000000206674797069736F6D00000000"))
    out, name = cs.finalize_downloaded_video_path(bare)
    assert out.name == "HHDI.mp4"
    assert name == "HHDI.mp4"
    assert out.is_file()


def test_parse_entry_normalizes_yyyymmdd_upload_date():
    card = cs._parse_entry(
        {
            "id": "abc123",
            "title": "Test",
            "duration": 45,
            "upload_date": "20250410",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
        },
        "youtube",
    )
    assert card is not None
    assert card["upload_date"].startswith("2025-04-10")


def test_filter_youtube_shorts():
    rows = [
        {"id": "1", "duration": 30},
        {"id": "2", "duration": 120},
        {"id": "3", "duration": 0},
    ]
    out = cs._filter_youtube_shorts(rows, max_duration_sec=60)
    assert [r["id"] for r in out] == ["1"]


def test_watchlist_match_by_channel_id_and_score_boost():
    watchlist = ["UCabc123xyz"]
    rows = [{
        "id": "vid1",
        "title": "Aviator x100 big win #shorts",
        "duration": 35,
        "view_count": 120_000,
        "channel": "Some Channel",
        "channel_url": "https://www.youtube.com/channel/UCabc123xyz",
        "url": "https://www.youtube.com/shorts/vid1",
    }]
    out = cs._filter_youtube_shorts(rows, max_duration_sec=60)
    assert out and out[0]["id"] == "vid1"
    wl_norm = cs._normalize_watchlist_entries(watchlist)
    matched = cs._watchlist_match(rows[0], wl_norm)
    base = cs._arb_relevance_score(rows[0], "aviator", cs.ARBITRAGE_GAME_PATTERNS["aviator"])
    boosted = min(100, base + (25 if matched else 0))
    assert matched == "ucabc123xyz"
    assert boosted >= base


def test_arb_relevance_score_prefers_short_arb_style_titles():
    short_hit = {
        "title": "aviator game big win shorts x100 strategy",
        "duration": 42,
        "view_count": 50_000,
        "channel": "arb test",
    }
    long_generic = {
        "title": "aviator gameplay stream episode",
        "duration": 600,
        "view_count": 50_000,
        "channel": "official channel",
    }
    s1 = cs._arb_relevance_score(short_hit, "aviator", cs.ARBITRAGE_GAME_PATTERNS["aviator"])
    s2 = cs._arb_relevance_score(long_generic, "aviator", cs.ARBITRAGE_GAME_PATTERNS["aviator"])
    assert s1 > s2


def test_finalize_keeps_existing_mp4(tmp_path: Path):
    p = tmp_path / "x.mp4"
    p.write_bytes(b"not-a-real-mp4-but-ends-with-suffix")
    out, name = cs.finalize_downloaded_video_path(p)
    assert out == p
    assert name == "x.mp4"
