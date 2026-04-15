"""Тесты AdsPower: мок _get_json, без реального локального API."""

from __future__ import annotations

import pytest

from core import adspower_sync as ads


@pytest.mark.asyncio
async def test_extract_ws_puppeteer():
    ws = ads._extract_ws_endpoint({"ws": {"puppeteer": "ws://127.0.0.1:9222"}})
    assert ws == "ws://127.0.0.1:9222"


@pytest.mark.asyncio
async def test_extract_ws_string_block():
    ws = ads._extract_ws_endpoint({"ws": "ws://host/devtools/browser/x"})
    assert ws.startswith("ws://")


@pytest.mark.asyncio
async def test_extract_ws_missing():
    assert ads._extract_ws_endpoint({}) is None
    assert ads._extract_ws_endpoint(None) is None


@pytest.mark.asyncio
async def test_fetch_profiles_ok(monkeypatch):
    async def fake_get_json(session, url):
        return {
            "code": 0,
            "data": {
                "list": [
                    {"user_id": "u1", "name": "One"},
                    {"id": "u2", "remark": "Two"},
                ]
            },
        }

    monkeypatch.setattr(ads, "_get_json", fake_get_json)
    r = await ads.fetch_profiles()
    assert r["status"] == "ok"
    assert len(r["profiles"]) == 2
    assert r["profiles"][0]["user_id"] == "u1"
    assert r["profiles"][1]["user_id"] == "u2"


@pytest.mark.asyncio
async def test_fetch_profiles_tuple_error(monkeypatch):
    async def fake_get_json(session, url):
        return (None, "bad")

    monkeypatch.setattr(ads, "_get_json", fake_get_json)
    r = await ads.fetch_profiles()
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_start_profile_ok(monkeypatch):
    async def fake_get_json(session, url):
        return {
            "code": 0,
            "data": {"ws": {"puppeteer": "ws://127.0.0.1:1/devtools/browser/x"}},
        }

    monkeypatch.setattr(ads, "_get_json", fake_get_json)
    r = await ads.start_profile("abc")
    assert r["status"] == "ok"
    assert r["ws_endpoint"].startswith("ws://")


@pytest.mark.asyncio
async def test_start_profile_empty_id():
    r = await ads.start_profile("   ")
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_stop_profile_ok(monkeypatch):
    async def fake_get_json(session, url):
        return {"code": 0, "data": {"ok": True}}

    monkeypatch.setattr(ads, "_get_json", fake_get_json)
    r = await ads.stop_profile("x")
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_verify_connection_ok(monkeypatch):
    async def fake_get_json(session, url):
        return {"code": 0, "data": {"list": [{"user_id": "a"}]}}

    monkeypatch.setattr(ads, "_get_json", fake_get_json)
    r = await ads.verify_connection()
    assert r["status"] == "ok"
    assert r["profiles_count"] == 1
    assert r["synced_to_db"] is False
    assert "api_base" in r


@pytest.mark.asyncio
async def test_configure_api_base_roundtrip(monkeypatch):
    monkeypatch.delenv("ADSPOWER_API_URL", raising=False)
    assert "50325" in ads.get_adspower_base()
    r = ads.configure_api_base("http://127.0.0.1:50325")
    assert r["status"] == "ok"
    ads.configure_api_base(None)
    assert "50325" in ads.get_adspower_base()


def test_configure_api_settings_and_status(monkeypatch):
    monkeypatch.delenv("ADSPOWER_API_URL", raising=False)
    monkeypatch.delenv("ADSPOWER_API_KEY", raising=False)
    monkeypatch.delenv("ADSPOWER_USE_AUTH", raising=False)
    r = ads.configure_api_settings(
        url="http://127.0.0.1:50325",
        api_key="abcdef1234567890",
        use_auth=True,
    )
    assert r["status"] == "ok"
    status = ads.get_api_settings_status()
    assert status["status"] == "ok"
    assert status["use_auth"] is True
    assert status["api_key_configured"] is True
    assert "••••" in status["api_key_masked"]


def test_build_headers_uses_bearer(monkeypatch):
    monkeypatch.setenv("ADSPOWER_API_KEY", "secret-token")
    monkeypatch.setenv("ADSPOWER_USE_AUTH", "1")
    headers = ads._build_headers()
    assert headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_fetch_profiles_and_sync_db(monkeypatch, temp_db_path):
    async def fake_get_json(session, url):
        return {"code": 0, "data": {"list": [{"user_id": "sync1", "name": "N"}]}}

    monkeypatch.setattr(ads, "_get_json", fake_get_json)

    from core import database as db

    await db.init_db(temp_db_path)
    r = await ads.fetch_profiles_and_sync_db(db_path=temp_db_path)
    assert r["status"] == "ok"
    assert r["count"] == 1
    lst = await db.list_profiles(db_path=temp_db_path)
    assert lst["profiles"][0]["adspower_id"] == "sync1"
