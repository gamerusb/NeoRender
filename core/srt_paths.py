"""
Проверка путей к .srt внутри хранилища tenant (без модуля распознавания речи).
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.tenancy import normalize_tenant_id

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def validate_srt_path_for_tenant(path: str | None, tenant_id: str) -> str | None:
    """Убедиться, что путь к SRT лежит в data/uploads/{tenant}/."""
    if not path or not str(path).strip():
        return None
    t = normalize_tenant_id(tenant_id)
    base = (ROOT / "data" / "uploads" / t).resolve()
    try:
        p = Path(path).resolve()
        p.relative_to(base)
    except ValueError:
        logger.warning("validate_srt_path_for_tenant: path outside tenant: %s", path)
        return None
    if p.suffix.lower() != ".srt" or not p.is_file():
        return None
    return str(p)
