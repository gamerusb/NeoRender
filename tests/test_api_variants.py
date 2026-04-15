"""API-тесты пакетной генерации задач (variants)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from core import database as dbmod
from core.main_loop import AutomationPipeline


@pytest.fixture
def client(temp_db_path: Path, tiny_png: Path) -> TestClient:
    # Изолируем пайплайн на тестовую БД, чтобы не трогать рабочую.
    api_server._pipelines.clear()
    assert asyncio.run(dbmod.init_db(temp_db_path)).get("status") == "ok"
    api_server._pipelines["default"] = AutomationPipeline(
        db_path=temp_db_path,
        overlay_png=tiny_png,
        tenant_id="default",
    )
    return TestClient(api_server.app)


def test_variants_generate_rejects_bad_count(client: TestClient, tiny_mp4: Path):
    r = client.post(
        "/api/variants/generate",
        headers={"X-Tenant-ID": "default"},
        json={
            "source_video": str(tiny_mp4.resolve()),
            "render_only": True,
            "count": 0,
        },
    )
    assert r.status_code == 400
    data = r.json()
    assert data.get("status") == "error"
    assert "1..50" in str(data.get("message"))


def test_variants_generate_creates_tasks_and_enqueues(client: TestClient, tiny_mp4: Path):
    r = client.post(
        "/api/variants/generate",
        headers={"X-Tenant-ID": "default"},
        json={
            "source_video": str(tiny_mp4.resolve()),
            "render_only": True,
            "count": 3,
            "enqueue": True,
            "auto_start_pipeline": False,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("created") == 3
    assert data.get("enqueued") == 3
    ids = data.get("created_ids") or []
    assert len(ids) == 3

    tr = client.get("/api/tasks?limit=10", headers={"X-Tenant-ID": "default"})
    assert tr.status_code == 200
    tasks = tr.json().get("tasks") or []
    got = [t for t in tasks if t.get("id") in ids]
    assert len(got) == 3
    assert all(t.get("status") == "pending" for t in got)
