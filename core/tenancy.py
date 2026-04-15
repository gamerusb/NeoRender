"""
Изоляция данных по арендатору (tenant) для будущего SaaS / мультиаккаунтности.

MVP: один tenant_id = \"default\" (локальный десктоп).
Production: заголовок X-Tenant-ID, JWT org_id, поддомен и т.д.

Идентификатор — только безопасные символы; при мусоре подставляется default,
чтобы не ломать SQLite и пути (без слешей).
"""

from __future__ import annotations

import os
import re
from typing import Final

# Локальная установка и тесты без заголовков
DEFAULT_TENANT_ID: Final[str] = "default"

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def normalize_tenant_id(raw: str | None) -> str:
    """
    Нормализация tenant_id: lower-case, латиница, цифры, _ и -.

    Пустое или невалидное → DEFAULT_TENANT_ID (мягко, без исключений в UI).
    """
    try:
        if raw is None:
            return DEFAULT_TENANT_ID
        s = str(raw).strip().lower()
        if not s:
            return DEFAULT_TENANT_ID
        if not _TENANT_RE.match(s):
            return DEFAULT_TENANT_ID
        return s
    except Exception:
        return DEFAULT_TENANT_ID


def tenant_id_from_environ() -> str:
    """Переопределение для сервера: NEORENDER_TENANT_ID=acme."""
    return normalize_tenant_id(os.environ.get("NEORENDER_TENANT_ID"))
