from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from core import content_scraper
from core import database as db
from core import profile_job_runner


def test_cookies_restore_rejects_path_traversal():
    client = TestClient(api_server.app)
    r = client.post(
        "/api/cookies/restore/p1",
        headers={"X-Tenant-ID": "default"},
        json={"filename": "..\\..\\windows\\win.ini"},
    )
    assert r.status_code == 400
    assert r.json().get("status") == "error"


def test_analytics_check_all_counts_active_as_ok(monkeypatch, temp_db_path: Path, tiny_png: Path):
    api_server._pipelines.clear()
    assert asyncio.run(db.init_db(temp_db_path)).get("status") == "ok"
    api_server._pipelines["default"] = api_server.AutomationPipeline(
        db_path=temp_db_path, overlay_png=tiny_png, tenant_id="default"
    )

    async def _fake_check(_url: str):
        return {"status": "active", "views": 123}

    monkeypatch.setattr(api_server.analytics_scraper, "check_video", _fake_check)
    client = TestClient(api_server.app)
    r = client.post(
        "/api/analytics/check-all",
        headers={"X-Tenant-ID": "default"},
        json={"urls": ["https://youtube.com/watch?v=abc"], "delay_sec": 0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "ok"
    assert body.get("ok") == 1


def test_profile_job_runner_parse_utc_datetime():
    dt1 = profile_job_runner._parse_dt_utc("2026-04-10 14:00:00")
    dt2 = profile_job_runner._parse_dt_utc("2026-04-10T14:00:00+03:00")
    assert dt1 is not None and dt1.tzinfo is not None
    assert dt2 is not None and dt2.tzinfo is not None
    assert dt2.hour == 11  # UTC normalization


@pytest.mark.asyncio
async def test_download_video_uses_printed_output_path(monkeypatch, tmp_path: Path):
    out_file = tmp_path / "x.mp4"
    out_file.write_bytes(b"v")

    class _Proc:
        returncode = 0

        async def communicate(self):
            return (f"{out_file}\n".encode(), b"")

    async def _fake_exec(*_args, **_kwargs):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    r = await content_scraper.download_video("https://youtube.com/watch?v=abc", uploads_dir=tmp_path)
    assert r.get("status") == "ok"
    assert Path(str(r.get("path"))).resolve() == out_file.resolve()
