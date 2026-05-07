"""
Launcher обёртка — маршрутизирует запуск/остановку профилей
через AntidetectRegistry вместо прямого вызова adspower_sync.

Интерфейс не изменился: все импортирующие модули продолжают работать.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _error(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "error", "message": message}
    if data:
        out["data"] = data
    return out


def _ok(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "ok", "message": message, "data": data or {}}


async def start_profile(profile_id: str, tenant_id: str = "default") -> dict[str, Any]:
    """Запустить профиль через реестр (любой тип антидетекта)."""
    if not str(profile_id or "").strip():
        return _error("Не указан profile_id.")
    try:
        from core.antidetect_registry import get_registry
        registry = get_registry()
        res = await registry.start_profile(str(profile_id).strip(), tenant_id=tenant_id)
        if res.get("status") != "ok":
            return _error(str(res.get("message") or "Не удалось запустить профиль."), dict(res))
        return _ok(
            "Профиль запущен.",
            {
                "profile_id": str(profile_id).strip(),
                "ws_endpoint": str(res.get("ws_endpoint") or ""),
                "raw": res.get("raw"),
            },
        )
    except Exception as exc:
        logger.exception("launcher.start_profile %s: %s", profile_id, exc)
        return _error("Ошибка запуска профиля.")


async def stop_profile(profile_id: str, tenant_id: str = "default") -> dict[str, Any]:
    """Остановить профиль через реестр."""
    if not str(profile_id or "").strip():
        return _error("Не указан profile_id.")
    try:
        from core.antidetect_registry import get_registry
        registry = get_registry()
        res = await registry.stop_profile(str(profile_id).strip(), tenant_id=tenant_id)
        if res.get("status") != "ok":
            return _error(str(res.get("message") or "Не удалось остановить профиль."), dict(res))
        return _ok(
            "Профиль остановлен.",
            {"profile_id": str(profile_id).strip(), "raw": res.get("raw")},
        )
    except Exception as exc:
        logger.exception("launcher.stop_profile %s: %s", profile_id, exc)
        return _error("Ошибка остановки профиля.")


async def check_profile_health(profile_id: str, tenant_id: str = "default") -> dict[str, Any]:
    """Запустить профиль и сразу остановить — проверка доступности."""
    if not str(profile_id or "").strip():
        return _error("Не указан profile_id.")
    try:
        started = await start_profile(profile_id, tenant_id=tenant_id)
        if started.get("status") != "ok":
            return _error(
                str(started.get("message") or "Профиль не запустился."),
                {"profile_id": str(profile_id).strip(), "launch_ok": False},
            )
        ws_endpoint = str((started.get("data") or {}).get("ws_endpoint") or "")
        stopped = await stop_profile(profile_id, tenant_id=tenant_id)
        return _ok(
            "Профиль доступен.",
            {
                "profile_id": str(profile_id).strip(),
                "launch_ok": True,
                "stop_ok": stopped.get("status") == "ok",
                "ws_endpoint": ws_endpoint,
            },
        )
    except Exception as exc:
        logger.exception("launcher.check_profile_health %s: %s", profile_id, exc)
        return _error("Не удалось проверить профиль.")
