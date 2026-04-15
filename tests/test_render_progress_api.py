"""GET /api/pipeline/render-progress — ответ для UI модалки."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_render_progress_idle(client: TestClient):
    r = client.get(
        "/api/pipeline/render-progress",
        headers={"X-Tenant-ID": "zz_idle_no_tasks"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("visible") is False
    assert data.get("encoding") is False
    assert "queue_total" in data
    assert "queue_done" in data
