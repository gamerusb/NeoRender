from __future__ import annotations

import pytest

from core.storage import LocalMediaStorage, is_stored_upload_video_filename, resolve_uploaded_video_file


@pytest.mark.asyncio
async def test_save_upload_rejects_when_disk_space_low(monkeypatch, tmp_path) -> None:
    st = LocalMediaStorage(base_dir=tmp_path)
    monkeypatch.setattr(st, "_has_enough_disk_space", lambda _target, _incoming: False)

    res = await st.save_upload("default", "video.mp4", b"abc")
    assert res["status"] == "error"
    assert "Недостаточно" in res["message"]


@pytest.mark.asyncio
async def test_save_upload_stream_writes_file(tmp_path) -> None:
    st = LocalMediaStorage(base_dir=tmp_path)

    async def _chunks():
        yield b"abc"
        yield b"123"

    res = await st.save_upload_stream("acme", "clip.mp4", _chunks())
    assert res["status"] == "ok"
    path = tmp_path / "uploads" / "acme" / str(res["filename"])
    assert path.exists()
    assert path.read_bytes() == b"abc123"


def test_resolve_uploaded_video_file_accepts_only_safe_names(tmp_path, monkeypatch) -> None:
    st = LocalMediaStorage(base_dir=tmp_path)

    # Подменяем singleton, чтобы resolve_* смотрел в temp storage.
    import core.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_default_storage", st)
    tenant_dir = tmp_path / "uploads" / "default"
    tenant_dir.mkdir(parents=True, exist_ok=True)
    good_name = "0123456789abcdef0123456789abcdef.mp4"
    good_path = tenant_dir / good_name
    good_path.write_bytes(b"x")

    assert is_stored_upload_video_filename(good_name) is True
    assert resolve_uploaded_video_file("default", good_name) == good_path.resolve()
    assert resolve_uploaded_video_file("default", "../evil.mp4") is None
