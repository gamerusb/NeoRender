"""API: создание задач и отмена."""

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
    api_server._pipelines.clear()
    assert asyncio.run(dbmod.init_db(temp_db_path)).get("status") == "ok"
    api_server._pipelines["default"] = AutomationPipeline(
        db_path=temp_db_path,
        overlay_png=tiny_png,
        tenant_id="default",
    )
    return TestClient(api_server.app)


def test_tasks_create_rejects_missing_file(client: TestClient):
    r = client.post(
        "/api/tasks",
        headers={"X-Tenant-ID": "default"},
        json={
            "original_video": r"C:\no\such\file\video.mp4",
            "target_profile": "",
            "render_only": True,
        },
    )
    assert r.status_code == 400
    assert r.json().get("status") == "error"


def test_tasks_create_rejects_empty_path(client: TestClient):
    r = client.post(
        "/api/tasks",
        headers={"X-Tenant-ID": "default"},
        json={"original_video": "  ", "target_profile": "", "render_only": True},
    )
    assert r.status_code == 400


def _make_video_in_data(suffix: str = ".mp4") -> Path:
    """Создать фиктивный файл внутри data/ (path traversal защита разрешает только data/)."""
    import api_server as _srv
    p = _srv.ROOT / "data" / "uploads" / "default" / f"test_video{suffix}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"not real mp4")
    return p


def test_tasks_create_ok(client: TestClient):
    vp = _make_video_in_data()
    try:
        r = client.post(
            "/api/tasks",
            headers={"X-Tenant-ID": "default"},
            json={
                "original_video": str(vp.resolve()),
                "target_profile": "",
                "render_only": True,
                "subtitle": "CTA",
                "template": "ugc",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "ok"
        tid = int(data.get("id") or 0)
        assert tid > 0
        g = asyncio.run(dbmod.get_task_by_id(tid, tenant_id="default", db_path=api_server._pipelines["default"].db_path))
        assert g["task"]["subtitle"] == "CTA"
        assert g["task"]["template"] == "ugc"
        assert g["task"]["created_at"]  # новое поле
    finally:
        vp.unlink(missing_ok=True)


def test_task_cancel_pending(client: TestClient):
    vp = _make_video_in_data()
    try:
        cr = client.post(
            "/api/tasks",
            headers={"X-Tenant-ID": "default"},
            json={
                "original_video": str(vp.resolve()),
                "target_profile": "",
                "render_only": True,
            },
        )
        tid = int(cr.json().get("id") or 0)
        r = client.post(f"/api/tasks/{tid}/cancel", headers={"X-Tenant-ID": "default"})
        assert r.status_code == 200
        assert r.json().get("status") == "ok"
        g = asyncio.run(dbmod.get_task_by_id(tid, tenant_id="default", db_path=api_server._pipelines["default"].db_path))
        assert g["task"]["status"] == "error"
        assert "Отменено" in str(g["task"].get("error_message") or "")
    finally:
        vp.unlink(missing_ok=True)


def test_task_retry_endpoint(client: TestClient):
    """POST /api/tasks/{id}/retry сбрасывает error-задачу в pending."""
    vp = _make_video_in_data()
    try:
        cr = client.post(
            "/api/tasks",
            headers={"X-Tenant-ID": "default"},
            json={"original_video": str(vp.resolve()), "target_profile": "", "render_only": True},
        )
        tid = int(cr.json().get("id") or 0)
        # Сначала отменяем → error
        client.post(f"/api/tasks/{tid}/cancel", headers={"X-Tenant-ID": "default"})
        # Retry
        r = client.post(f"/api/tasks/{tid}/retry", headers={"X-Tenant-ID": "default"})
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "ok"
        # Статус снова pending
        g = asyncio.run(dbmod.get_task_by_id(tid, tenant_id="default", db_path=api_server._pipelines["default"].db_path))
        assert g["task"]["status"] == "pending"
        assert not g["task"].get("error_message")
    finally:
        vp.unlink(missing_ok=True)


def test_task_retry_fails_for_non_error(client: TestClient):
    """Retry pending-задачи возвращает 400."""
    vp = _make_video_in_data()
    try:
        cr = client.post(
            "/api/tasks",
            headers={"X-Tenant-ID": "default"},
            json={"original_video": str(vp.resolve()), "target_profile": "", "render_only": True},
        )
        tid = int(cr.json().get("id") or 0)
        r = client.post(f"/api/tasks/{tid}/retry", headers={"X-Tenant-ID": "default"})
        assert r.status_code == 400
        assert r.json().get("status") == "error"
    finally:
        vp.unlink(missing_ok=True)


def test_tasks_create_path_traversal_blocked(client: TestClient, tmp_path: Path):
    """Файл за пределами data/ должен быть отклонён."""
    outside = tmp_path / "evil.mp4"
    outside.write_bytes(b"fake")
    r = client.post(
        "/api/tasks",
        headers={"X-Tenant-ID": "default"},
        json={"original_video": str(outside.resolve()), "target_profile": "", "render_only": True},
    )
    assert r.status_code == 400
    assert "запрещён" in r.json().get("message", "")


def test_render_progress_ok(client: TestClient):
    r = client.get("/api/pipeline/render-progress", headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert "visible" in data
    assert "queue_total" in data


def test_task_schedule_requires_timezone(client: TestClient):
    vp = _make_video_in_data()
    try:
        cr = client.post(
            "/api/tasks",
            headers={"X-Tenant-ID": "default"},
            json={"original_video": str(vp.resolve()), "target_profile": "", "render_only": True},
        )
        tid = int(cr.json().get("id") or 0)
        r = client.post(
            f"/api/tasks/{tid}/schedule",
            headers={"X-Tenant-ID": "default"},
            json={"scheduled_at": "2026-04-10T14:00:00"},
        )
        assert r.status_code == 400
        assert "timezone" in r.json().get("message", "").lower()
    finally:
        vp.unlink(missing_ok=True)


def test_task_schedule_normalizes_to_utc(client: TestClient):
    vp = _make_video_in_data()
    try:
        cr = client.post(
            "/api/tasks",
            headers={"X-Tenant-ID": "default"},
            json={"original_video": str(vp.resolve()), "target_profile": "", "render_only": True},
        )
        tid = int(cr.json().get("id") or 0)
        r = client.post(
            f"/api/tasks/{tid}/schedule",
            headers={"X-Tenant-ID": "default"},
            json={"scheduled_at": "2026-04-10T14:00:00+03:00"},
        )
        assert r.status_code == 200, r.text
        assert r.json().get("scheduled_at") == "2026-04-10 11:00:00"
    finally:
        vp.unlink(missing_ok=True)
