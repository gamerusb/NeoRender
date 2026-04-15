"""Тесты парсинга HTML YouTube (мок ответа aiohttp)."""

from __future__ import annotations

import pytest

from core import analytics_scraper as ans


def _html_with_views(n: int) -> str:
    return f"""<!DOCTYPE html><html><head>
<meta itemprop="interactionCount" content="{n}"/>
</head><body>ok</body></html>"""


class FakeResp:
    def __init__(self, status: int, text: str):
        self.status = status
        self._text = text

    async def text(self, errors="replace"):
        return self._text


class _GetCtx:
    def __init__(self, resp: FakeResp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return None


class FakeSession:
    def __init__(self, resp: FakeResp):
        self._resp = resp

    def get(self, url, allow_redirects=True):
        return _GetCtx(self._resp)


@pytest.mark.asyncio
async def test_check_video_banned_404():
    session = FakeSession(FakeResp(404, "<html>Video unavailable</html>"))
    r = await ans.check_video("https://youtube.com/watch?v=x", session=session)
    assert r["status"] == "banned"


@pytest.mark.asyncio
async def test_check_video_banned_text():
    session = FakeSession(FakeResp(200, "<html>Video unavailable</html>"))
    r = await ans.check_video("https://youtube.com/watch?v=x", session=session)
    assert r["status"] == "banned"


@pytest.mark.asyncio
async def test_check_video_active():
    session = FakeSession(FakeResp(200, _html_with_views(12345)))
    r = await ans.check_video("https://youtube.com/watch?v=x", session=session)
    assert r["status"] == "active"
    assert r["views"] == 12345


@pytest.mark.asyncio
async def test_check_video_shadowban_after_24h():
    from datetime import datetime, timedelta, timezone

    session = FakeSession(FakeResp(200, _html_with_views(0)))
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    r = await ans.check_video(
        "https://youtube.com/watch?v=x",
        published_at=old,
        session=session,
    )
    assert r["status"] == "shadowban"
    assert r["views"] == 0


@pytest.mark.asyncio
async def test_check_video_zero_views_recent_not_shadowban():
    from datetime import datetime, timedelta, timezone

    session = FakeSession(FakeResp(200, _html_with_views(0)))
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    r = await ans.check_video(
        "https://youtube.com/watch?v=x",
        published_at=recent,
        session=session,
    )
    assert r["status"] == "active"
    assert r["views"] == 0


@pytest.mark.asyncio
async def test_check_video_empty_url():
    r = await ans.check_video("")
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_check_video_unknown_platform():
    r = await ans.check_video("https://example.com/video/1")
    assert r["status"] == "error"
    assert "YouTube" in (r.get("message") or "")


@pytest.mark.asyncio
async def test_check_video_tiktok_routes_to_ytdlp(monkeypatch):
    async def fake_ytdlp(url: str, platform: str):
        assert "tiktok.com" in url
        assert platform == "tiktok"
        return {"status": "active", "views": 99, "likes": 5, "platform": "tiktok", "title": "t"}

    monkeypatch.setattr(ans, "_check_ytdlp_metadata", fake_ytdlp)
    r = await ans.check_video("https://www.tiktok.com/@u/video/123")
    assert r["status"] == "active"
    assert r["views"] == 99
    assert r["likes"] == 5
