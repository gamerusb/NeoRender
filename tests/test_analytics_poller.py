from __future__ import annotations

from dataclasses import dataclass

import pytest

from core import analytics_poller as ap
from core import analytics_scraper, database, notifier


@dataclass
class _Pipe:
    tenant_id: str = "default"
    db_path: str = "test.db"


class _FakeSession:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeAiohttp:
    class ClientTimeout:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    ClientSession = _FakeSession


def test_env_parsers(monkeypatch) -> None:
    monkeypatch.setenv("NEORENDER_ANALYTICS_POLL_INTERVAL_SEC", "120")
    monkeypatch.setenv("NEORENDER_ANALYTICS_PER_VIDEO_DELAY_SEC", "0")
    monkeypatch.setenv("NEORENDER_ANALYTICS_CONCURRENCY", "50")
    assert ap._poll_interval() == 120.0
    assert ap._per_video_delay() == 0.0
    assert ap._concurrency() == 20


@pytest.mark.asyncio
async def test_tick_updates_metrics_and_sends_alert_on_status_change(monkeypatch) -> None:
    monkeypatch.setenv("NEORENDER_ANALYTICS_PER_VIDEO_DELAY_SEC", "0")
    monkeypatch.setenv("NEORENDER_ANALYTICS_CONCURRENCY", "1")
    monkeypatch.setitem(__import__("sys").modules, "aiohttp", _FakeAiohttp())

    async def _fake_list_active(_tenant: str, _db_path: str):
        return {
            "status": "ok",
            "analytics": [
                {"video_url": "https://yt/1", "status": "active", "views": 10, "likes": 1, "published_at": None}
            ],
        }

    async def _fake_check_video(*_args, **_kwargs):
        return {"status": "shadowban", "views": 123}

    upserts = []
    alerts = []

    async def _fake_upsert(url: str, **kwargs):
        upserts.append((url, kwargs))
        return {"status": "ok"}

    async def _fake_send_text(text: str, parse_mode: str = "HTML"):
        alerts.append((text, parse_mode))
        return True

    monkeypatch.setattr(database, "list_active_analytics", _fake_list_active)
    monkeypatch.setattr(database, "upsert_analytics", _fake_upsert)
    monkeypatch.setattr(analytics_scraper, "check_video", _fake_check_video)
    monkeypatch.setattr(notifier, "send_text", _fake_send_text)

    poller = ap.AnalyticsPoller(_Pipe())
    await poller._tick()

    assert len(upserts) == 1
    assert upserts[0][1]["status"] == "shadowban"
    assert len(alerts) == 1
    assert "shadowban" in alerts[0][0]


@pytest.mark.asyncio
async def test_tick_no_alert_when_status_unchanged(monkeypatch) -> None:
    monkeypatch.setenv("NEORENDER_ANALYTICS_PER_VIDEO_DELAY_SEC", "0")
    monkeypatch.setitem(__import__("sys").modules, "aiohttp", _FakeAiohttp())

    async def _fake_list_active(_tenant: str, _db_path: str):
        return {"status": "ok", "analytics": [{"video_url": "https://yt/1", "status": "active", "views": 10, "likes": 1}]}

    async def _fake_check_video(*_args, **_kwargs):
        return {"status": "active", "views": 50}

    async def _fake_upsert(url: str, **kwargs):
        return {"status": "ok"}

    alerts = []

    async def _fake_send_text(text: str, parse_mode: str = "HTML"):
        alerts.append((text, parse_mode))
        return True

    monkeypatch.setattr(database, "list_active_analytics", _fake_list_active)
    monkeypatch.setattr(database, "upsert_analytics", _fake_upsert)
    monkeypatch.setattr(analytics_scraper, "check_video", _fake_check_video)
    monkeypatch.setattr(notifier, "send_text", _fake_send_text)

    poller = ap.AnalyticsPoller(_Pipe())
    await poller._tick()
    assert alerts == []
