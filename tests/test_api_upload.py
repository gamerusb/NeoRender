"""Минимальный HTTP-тест загрузки файла."""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from api_server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_upload_video_returns_path(client: TestClient):
    files = {"file": ("tiny.mp4", BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")}
    r = client.post("/api/upload", files=files, headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert "path" in data
    assert ".mp4" in str(data["path"]).lower() or "mp4" in str(data["path"]).lower()


def test_stream_uploaded_video_by_header(client: TestClient):
    body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    files = {"file": ("tiny.mp4", BytesIO(body), "video/mp4")}
    r = client.post("/api/upload", files=files, headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200
    data = r.json()
    fn = data.get("filename")
    assert fn and str(fn).endswith(".mp4")
    r2 = client.get(f"/api/uploads/video/{fn}", headers={"X-Tenant-ID": "default"})
    assert r2.status_code == 200
    assert r2.content == body


def test_stream_uploaded_video_by_tenant_query(client: TestClient):
    body = b"\x00\x00\x00\x18ftypmp42"
    files = {"file": ("q.mp4", BytesIO(body), "video/mp4")}
    r = client.post("/api/upload", files=files, headers={"X-Tenant-ID": "default"})
    fn = r.json()["filename"]
    r2 = client.get(f"/api/uploads/video/{fn}?tenant=default")
    assert r2.status_code == 200
    assert r2.content == body


def test_stream_uploaded_video_wrong_tenant_404(client: TestClient):
    body = b"\x00\x00\x00\x18ftypmp42"
    files = {"file": ("iso.mp4", BytesIO(body), "video/mp4")}
    r = client.post("/api/upload", files=files, headers={"X-Tenant-ID": "acme"})
    assert r.status_code == 200
    fn = r.json()["filename"]
    r2 = client.get(f"/api/uploads/video/{fn}", headers={"X-Tenant-ID": "default"})
    assert r2.status_code == 404


def test_stream_uploaded_video_bad_name_404(client: TestClient):
    r = client.get("/api/uploads/video/not-a-uuid.mp4", headers={"X-Tenant-ID": "default"})
    assert r.status_code == 404


def test_upload_overlay_via_purpose(client: TestClient):
    """Корректный PNG-оверлей принимается (мок ffprobe)."""
    import struct, zlib
    # Минимальный валидный PNG 2×2 (ffprobe его читает)
    def make_png_chunk(name: bytes, data: bytes) -> bytes:
        c = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = make_png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\x00\x00" * 2 + b"\x00\x00\xff\x00" * 2
    idat = make_png_chunk(b"IDAT", zlib.compress(raw))
    iend = make_png_chunk(b"IEND", b"")
    valid_png = sig + ihdr + idat + iend

    files = {"file": ("layer.png", BytesIO(valid_png), "image/png")}
    r = client.post(
        "/api/upload",
        files=files,
        data={"purpose": "overlay"},
        headers={"X-Tenant-ID": "default"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok", f"Ожидался ok, получен: {data}"
    assert data.get("overlay_media_path")
    assert str(data["path"]).lower().endswith(".png")


def test_upload_overlay_corrupt_rejected(client: TestClient):
    """Битый оверлей (< 16 байт) должен отклоняться с ошибкой."""
    files = {"file": ("layer.png", BytesIO(b"x"), "image/png")}
    r = client.post(
        "/api/upload",
        files=files,
        data={"purpose": "overlay"},
        headers={"X-Tenant-ID": "default"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "error"
    assert "повреждён" in data.get("message", "") or "мал" in data.get("message", "")


def test_upload_srt_via_purpose(client: TestClient):
    srt_body = b"1\n00:00:00,000 --> 00:00:01,000\nhi\n"
    files = {"file": ("subs.srt", BytesIO(srt_body), "text/plain")}
    r = client.post(
        "/api/upload",
        files=files,
        data={"purpose": "srt"},
        headers={"X-Tenant-ID": "default"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert str(data.get("path", "")).lower().endswith(".srt")
    assert data.get("subtitle_srt_path")


def test_upload_srt_wrong_extension_rejected(client: TestClient):
    files = {"file": ("subs.txt", BytesIO(b"1\n00:00:00,000 --> 00:00:01,000\nhi\n"), "text/plain")}
    r = client.post(
        "/api/upload",
        files=files,
        data={"purpose": "srt"},
        headers={"X-Tenant-ID": "default"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["status"] == "error"
    assert ".srt" in body["message"]


def test_upload_returns_429_when_rate_limited(client: TestClient, monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "_is_rate_limited", lambda *_a, **_k: True)
    files = {"file": ("tiny.mp4", BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")}
    r = client.post("/api/upload", files=files, headers={"X-Tenant-ID": "default"})
    assert r.status_code == 429
    assert r.json()["status"] == "error"


def test_upload_returns_413_when_stream_too_large(client: TestClient, monkeypatch):
    import api_server
    import core.storage as storage_mod

    class _BoomStorage:
        async def save_upload_stream(self, tenant_id, filename_hint, chunks):
            # Убеждаемся, что endpoint действительно передал async-чанки.
            assert tenant_id == "default"
            assert filename_hint.endswith(".mp4")
            raise ValueError("too big")

    monkeypatch.setattr(storage_mod, "get_default_storage", lambda: _BoomStorage())
    files = {"file": ("big.mp4", BytesIO(b"x" * 32), "video/mp4")}
    r = client.post("/api/upload", files=files, headers={"X-Tenant-ID": "default"})
    assert r.status_code == 413
    assert r.json()["status"] == "error"
