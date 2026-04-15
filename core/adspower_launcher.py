from __future__ import annotations

import logging
from typing import Any

from core import adspower_sync

logger = logging.getLogger(__name__)


def _error(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "error", "message": message}
    if data:
        out["data"] = data
    return out


def _ok(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok", "message": message, "data": data or {}}
    return out


async def start_profile(profile_id: str) -> dict[str, Any]:
    if not str(profile_id or "").strip():
        return _error("Не указан профиль AdsPower.")
    try:
        res = await adspower_sync.start_profile_with_retry(str(profile_id).strip())
        if res.get("status") != "ok":
            return _error(str(res.get("message") or "Не удалось запустить профиль AdsPower."), dict(res))
        return _ok(
            "Профиль AdsPower запущен.",
            {
                "profile_id": str(profile_id).strip(),
                "ws_endpoint": str(res.get("ws_endpoint") or ""),
                "raw": res.get("raw"),
            },
        )
    except Exception as exc:
        logger.exception("adspower_launcher.start_profile: %s", exc)
        return _error("Ошибка запуска профиля AdsPower.")


async def stop_profile(profile_id: str) -> dict[str, Any]:
    if not str(profile_id or "").strip():
        return _error("Не указан профиль AdsPower.")
    try:
        res = await adspower_sync.stop_profile(str(profile_id).strip())
        if res.get("status") != "ok":
            return _error(str(res.get("message") or "Не удалось остановить профиль AdsPower."), dict(res))
        return _ok(
            "Профиль AdsPower остановлен.",
            {"profile_id": str(profile_id).strip(), "raw": res.get("raw")},
        )
    except Exception as exc:
        logger.exception("adspower_launcher.stop_profile: %s", exc)
        return _error("Ошибка остановки профиля AdsPower.")


async def check_profile_health(profile_id: str) -> dict[str, Any]:
    if not str(profile_id or "").strip():
        return _error("Не указан профиль AdsPower.")
    try:
        started = await start_profile(profile_id)
        if started.get("status") != "ok":
            return _error(
                str(started.get("message") or "Профиль не удалось запустить."),
                {
                    "profile_id": str(profile_id).strip(),
                    "launch_ok": False,
                },
            )
        ws_endpoint = str((started.get("data") or {}).get("ws_endpoint") or "")
        stopped = await stop_profile(profile_id)
        return _ok(
            "Профиль доступен через AdsPower API.",
            {
                "profile_id": str(profile_id).strip(),
                "launch_ok": True,
                "stop_ok": stopped.get("status") == "ok",
                "ws_endpoint": ws_endpoint,
            },
        )
    except Exception as exc:
        logger.exception("adspower_launcher.check_profile_health: %s", exc)
        return _error("Не удалось проверить профиль AdsPower.")
