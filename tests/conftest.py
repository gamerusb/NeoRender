"""Общие фикстуры: временная БД, пути к тестовым файлам."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_db_path() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        p = Path(f.name)
    yield p
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture
def tiny_png(tmp_path: Path) -> Path:
    """Минимальный валидный PNG 1x1."""
    # PNG signature + minimal IHDR chunk (упрощённо — готовые байты 1x1 прозрачного)
    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n"
        b"-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    path = tmp_path / "overlay.png"
    path.write_bytes(png)
    return path


@pytest.fixture
def tiny_mp4(tmp_path: Path) -> Path:
    """Пустой файл с расширением .mp4 (для проверок «файл есть» при моке ffmpeg)."""
    p = tmp_path / "in.mp4"
    p.write_bytes(b"not real mp4")
    return p
