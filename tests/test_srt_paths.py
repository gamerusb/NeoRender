"""Проверка путей к SRT и файлу слоя оверлея."""

from __future__ import annotations

from pathlib import Path

from core import overlay_paths as op
from core import srt_paths as sp


def test_validate_overlay_default_png(tmp_path: Path, monkeypatch):
    root = tmp_path / "proj"
    d = root / "data"
    d.mkdir(parents=True)
    png = d / "overlay.png"
    png.write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(op, "ROOT", root)
    assert op.validate_overlay_media_path(str(png.resolve()), "default") == str(png.resolve())


def test_validate_srt_path_for_tenant(tmp_path: Path, monkeypatch):
    root = tmp_path / "proj"
    tenant_root = root / "data" / "uploads" / "default"
    tenant_root.mkdir(parents=True)
    srt = tenant_root / "x.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")

    monkeypatch.setattr(sp, "ROOT", root)

    ok = sp.validate_srt_path_for_tenant(str(srt.resolve()), "default")
    assert ok == str(srt.resolve())

    bad = sp.validate_srt_path_for_tenant(str(tmp_path / "outside.srt"), "default")
    assert bad is None
