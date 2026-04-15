from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import api_server


def test_subtitles_job_persists_ass_path(monkeypatch, tmp_path: Path):
    video = tmp_path / "in.mp4"
    srt = tmp_path / "x.srt"
    ass = tmp_path / "x.ass"
    video.write_bytes(b"fake")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    ass.write_text("[Script Info]\nScriptType: v4.00+\n", encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "test_key")

    async def _fake_generate_subtitles(*_a, **_k):
        return {
            "status": "ok",
            "srt_path": str(srt),
            "srt_filename": srt.name,
            "ass_path": str(ass),
            "ass_filename": ass.name,
            "burned_path": None,
            "burned_filename": None,
            "segment_count": 1,
            "source_lang": "en",
            "target_lang": "en",
        }

    monkeypatch.setattr(api_server.subtitle_generator, "generate_subtitles", _fake_generate_subtitles)
    client = TestClient(api_server.app)
    r = client.post(
        "/api/subtitles/generate",
        headers={"X-Tenant-ID": "default"},
        json={"file_path": str(video), "burn": False},
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    st = client.get(f"/api/subtitles/{job_id}", headers={"X-Tenant-ID": "default"})
    assert st.status_code == 200
    job = st.json()["job"]
    assert job["status"] == "done"
    assert job.get("ass_path") == str(ass)

    dl = client.get(f"/api/subtitles/{job_id}/download/ass", headers={"X-Tenant-ID": "default"})
    assert dl.status_code == 200
