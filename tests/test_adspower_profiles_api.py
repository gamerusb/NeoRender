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


def test_sync_profiles_from_adspower(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_fetch_profiles():
        return {
            "status": "ok",
            "profiles": [
                {
                    "user_id": "prof_1",
                    "name": "KR Main",
                    "raw": {"group_name": "KR", "proxy_name": "kr-proxy", "geo": "KR", "tags": ["kr", "shorts"]},
                }
            ],
        }

    monkeypatch.setattr(api_server.adspower_sync, "fetch_profiles", fake_fetch_profiles)
    r = client.post("/api/adspower/profiles/sync", headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ok"
    lst = client.get("/api/adspower/profiles", headers={"X-Tenant-ID": "default"}).json()
    assert lst["status"] == "ok"
    assert lst["profiles"][0]["adspower_profile_id"] == "prof_1"
    assert lst["profiles"][0]["group_name"] == "KR"
    events = client.get("/api/adspower/profiles/prof_1/events", headers={"X-Tenant-ID": "default"}).json()
    assert events["status"] == "ok"
    assert events["events"][0]["event_type"] == "sync"


def test_pause_resume_profile(client: TestClient):
    assert asyncio.run(
        dbmod.upsert_adspower_profile("prof_2", profile_name="P2", tenant_id="default", db_path=api_server._pipelines["default"].db_path)
    )["status"] == "ok"
    pause = client.post("/api/adspower/profiles/prof_2/pause", headers={"X-Tenant-ID": "default"})
    assert pause.status_code == 200
    assert pause.json()["status"] == "ok"
    prof = asyncio.run(dbmod.get_adspower_profile("prof_2", tenant_id="default", db_path=api_server._pipelines["default"].db_path))
    assert prof["profile"]["status"] == "paused"
    resume = client.post("/api/adspower/profiles/prof_2/resume", headers={"X-Tenant-ID": "default"})
    assert resume.status_code == 200
    prof = asyncio.run(dbmod.get_adspower_profile("prof_2", tenant_id="default", db_path=api_server._pipelines["default"].db_path))
    assert prof["profile"]["status"] == "ready"


def test_create_profile_link(client: TestClient):
    assert asyncio.run(
        dbmod.upsert_adspower_profile("prof_3", profile_name="P3", tenant_id="default", db_path=api_server._pipelines["default"].db_path)
    )["status"] == "ok"
    r = client.post(
        "/api/adspower/profile-links",
        headers={"X-Tenant-ID": "default"},
        json={
            "adspower_profile_id": "prof_3",
            "youtube_channel_id": "chan1",
            "youtube_channel_handle": "@chan1",
            "geo": "KR",
            "offer_name": "offer-a",
            "operator_label": "worker-1",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    rows = asyncio.run(dbmod.list_profile_channel_links(tenant_id="default", db_path=api_server._pipelines["default"].db_path))
    assert rows["links"][0]["youtube_channel_handle"] == "@chan1"


def test_create_retry_cancel_profile_job(client: TestClient):
    assert asyncio.run(
        dbmod.upsert_adspower_profile("prof_4", profile_name="P4", tenant_id="default", db_path=api_server._pipelines["default"].db_path)
    )["status"] == "ok"
    created = client.post(
        "/api/adspower/profile-jobs",
        headers={"X-Tenant-ID": "default"},
        json={
            "adspower_profile_id": "prof_4",
            "job_type": "warmup",
            "payload": {"intensity": "medium"},
            "run_now": False,
        },
    )
    assert created.status_code == 200, created.text
    job_id = int(created.json()["id"])
    cancel = client.post(f"/api/adspower/profile-jobs/{job_id}/cancel", headers={"X-Tenant-ID": "default"})
    assert cancel.status_code == 200
    assert cancel.json()["new_status"] == "cancelled"
    retry = client.post(f"/api/adspower/profile-jobs/{job_id}/retry", headers={"X-Tenant-ID": "default"})
    assert retry.status_code == 200
    assert retry.json()["new_status"] == "pending"


def test_launch_test_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    assert asyncio.run(
        dbmod.upsert_adspower_profile("prof_5", profile_name="P5", tenant_id="default", db_path=api_server._pipelines["default"].db_path)
    )["status"] == "ok"

    async def fake_check_profile_health(profile_id: str):
        return {
            "status": "ok",
            "message": "Профиль доступен через AdsPower API.",
            "data": {"profile_id": profile_id, "launch_ok": True, "stop_ok": True, "ws_endpoint": "ws://fake"},
        }

    monkeypatch.setattr(api_server.adspower_launcher, "check_profile_health", fake_check_profile_health)
    r = client.post("/api/adspower/profiles/prof_5/launch-test", headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    prof = asyncio.run(dbmod.get_adspower_profile("prof_5", tenant_id="default", db_path=api_server._pipelines["default"].db_path))
    assert prof["profile"]["last_launch_at"]


def test_create_publish_job_with_adspower_profile(client: TestClient):
    assert asyncio.run(
        dbmod.upsert_adspower_profile("prof_6", profile_name="P6", tenant_id="default", db_path=api_server._pipelines["default"].db_path)
    )["status"] == "ok"
    video_path = api_server.ROOT / "data" / "rendered" / "default" / "pub_test.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"fake-mp4")
    try:
        created = asyncio.run(
            dbmod.create_task(
                original_video=str(video_path),
                target_profile="prof_6",
                tenant_id="default",
                db_path=api_server._pipelines["default"].db_path,
            )
        )
        task_id = int(created["id"])
        assert asyncio.run(
            dbmod.update_task_status(
                task_id,
                "success",
                unique_video=str(video_path),
                tenant_id="default",
                db_path=api_server._pipelines["default"].db_path,
            )
        )["status"] == "ok"
        r = client.post(
            "/api/publish/jobs",
            headers={"X-Tenant-ID": "default"},
            json={
                "task_id": task_id,
                "adspower_profile_id": "prof_6",
                "title": "KR short",
                "description": "desc",
                "tags": ["kr", "test"],
                "run_now": False,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ok"
        jobs = client.get("/api/publish/jobs", headers={"X-Tenant-ID": "default"}).json()
        assert jobs["status"] == "ok"
        assert jobs["jobs"][0]["job_type"] == "publish"
        assert jobs["jobs"][0]["adspower_profile_id"] == "prof_6"
    finally:
        video_path.unlink(missing_ok=True)


def test_record_profile_events_endpoint(client: TestClient):
    assert asyncio.run(
        dbmod.upsert_adspower_profile("prof_7", profile_name="P7", tenant_id="default", db_path=api_server._pipelines["default"].db_path)
    )["status"] == "ok"
    assert asyncio.run(
        dbmod.record_profile_event("prof_7", "manual_note", "hello", tenant_id="default", db_path=api_server._pipelines["default"].db_path)
    )["status"] == "ok"
    events = client.get("/api/adspower/profiles/prof_7/events", headers={"X-Tenant-ID": "default"}).json()
    assert events["status"] == "ok"
    assert events["events"][0]["event_type"] == "manual_note"
