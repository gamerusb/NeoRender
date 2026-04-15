"""HTTP-тест: /api/integrations/ping — Groq и AdsPower независимы."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_integrations_ping_groq_ok_when_adspower_fails(monkeypatch, client: TestClient):
    async def groq_ok(_key: str | None = None):
        return {"live": True, "message": "API на связи"}

    async def ads_down():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("api_server.ai_copywriter.ping_groq_api", groq_ok)
    monkeypatch.setattr("api_server.adspower_sync.verify_connection", ads_down)

    r = client.get("/api/integrations/ping", headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["groq"]["live"] is True
    assert data["adspower"]["live"] is False
    assert "AdsPower" in data["adspower"]["message"]


def test_integrations_ping_adspower_ok_when_groq_fails(monkeypatch, client: TestClient):
    async def groq_fail(_key: str | None = None):
        raise OSError("boom")

    async def ads_ok():
        return {
            "status": "ok",
            "message": "OK",
            "profiles_count": 3,
        }

    monkeypatch.setattr("api_server.ai_copywriter.ping_groq_api", groq_fail)
    monkeypatch.setattr("api_server.adspower_sync.verify_connection", ads_ok)

    r = client.get("/api/integrations/ping", headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["groq"]["live"] is False
    assert data["adspower"]["live"] is True
    assert data["adspower"]["profiles_count"] == 3
