"""Проверка пути к файлу слоя (картинка / видео) внутри uploads/{tenant}."""

from __future__ import annotations

import logging
from pathlib import Path

from core.tenancy import normalize_tenant_id

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

ALLOWED_OVERLAY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".mp4", ".mov", ".webm", ".mkv", ".avi"}
)


def validate_overlay_media_path(path: str | None, tenant_id: str) -> str | None:
    if not path or not str(path).strip():
        return None
    try:
        p = Path(path).resolve()
    except OSError:
        return None
    default_png = (ROOT / "data" / "overlay.png").resolve()
    if p == default_png and p.is_file():
        return str(p)
    t = normalize_tenant_id(tenant_id)
    base = (ROOT / "data" / "uploads" / t).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        logger.warning("validate_overlay_media_path: path outside tenant: %s", path)
        return None
    suf = p.suffix.lower()
    if suf not in ALLOWED_OVERLAY_SUFFIXES or not p.is_file():
        return None
    return str(p)
