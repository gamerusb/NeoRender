"""
Реестр антидетект-браузеров.

Загружает клиентов из таблицы antidetect_browsers в БД.
Маршрутизирует операции start/stop/fetch по antidetect_id профиля.

Использование:
    registry = AntidetectRegistry(db_path)
    await registry.load()

    # Запуск профиля через нужный антидетект
    client = await registry.client_for_profile("p123")
    result = await client.start_profile("p123")

    # Синхронизация всех профилей из всех антидетектов
    result = await registry.sync_all_profiles(tenant_id="default")
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.antidetect_client import (
    AntidetectClient,
    AdsPowerClient,
    create_client,
    SUPPORTED_BROWSER_TYPES,
    default_url,
)
from core import database as dbmod

logger = logging.getLogger(__name__)


def _error(msg: str) -> dict[str, Any]:
    return {"status": "error", "message": msg}


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


# ── Singleton registry ────────────────────────────────────────────────────────

class AntidetectRegistry:
    """
    Держит словарь antidetect_id → AntidetectClient.

    Поддерживает «нулевой» антидетект (id=0) для обратной совместимости
    с env-var-конфигурацией adspower_sync.py.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path
        self._clients: dict[int, AntidetectClient] = {}
        # profile_id → antidetect_id (кэш, обновляется при sync/load)
        self._profile_map: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def load(self) -> None:
        """Загрузить все активные антидетекты из БД и создать клиентов."""
        res = await dbmod.list_antidetect_browsers(db_path=self._db_path)
        if res.get("status") != "ok":
            logger.warning("antidetect_registry.load: %s", res.get("message"))
            return
        async with self._lock:
            # Закрыть старые сессии
            for client in self._clients.values():
                await client.close()
            self._clients.clear()
            for row in res.get("browsers") or []:
                if not row.get("is_active"):
                    continue
                aid = int(row["id"])
                btype = str(row.get("browser_type") or "adspower")
                url = str(row.get("api_url") or default_url(btype))
                key = str(row.get("api_key") or "")
                auth = bool(row.get("use_auth"))
                try:
                    self._clients[aid] = create_client(aid, btype, url, key, auth)
                    logger.info(
                        "antidetect_registry: loaded %s id=%d url=%s",
                        btype, aid, url,
                    )
                except ValueError as exc:
                    logger.warning("antidetect_registry: skip id=%d — %s", aid, exc)

    async def reload(self) -> None:
        """Перезагрузить реестр (вызывается после создания/удаления антидетекта)."""
        await self.load()

    async def close(self) -> None:
        """Закрыть все HTTP-сессии."""
        async with self._lock:
            for client in self._clients.values():
                await client.close()
            self._clients.clear()

    # ── Client resolution ─────────────────────────────────────────────────────

    def get_client(self, antidetect_id: int) -> AntidetectClient | None:
        return self._clients.get(antidetect_id)

    async def client_for_profile(
        self,
        profile_id: str,
        tenant_id: str = "default",
    ) -> AntidetectClient | None:
        """
        Найти клиент для профиля по antidetect_id из БД.
        Если профиль не привязан к антидетекту — вернуть первый доступный.
        """
        res = await dbmod.get_adspower_profile(profile_id, tenant_id=tenant_id, db_path=self._db_path)
        if res.get("status") == "ok":
            profile = res.get("profile") or {}
            aid = profile.get("antidetect_id")
            if aid is not None:
                client = self._clients.get(int(aid))
                if client:
                    return client
        # Fallback: первый доступный клиент
        if self._clients:
            return next(iter(self._clients.values()))
        return None

    def all_clients(self) -> list[AntidetectClient]:
        return list(self._clients.values())

    def count(self) -> int:
        return len(self._clients)

    # ── Profile start / stop ──────────────────────────────────────────────────

    async def start_profile(
        self,
        profile_id: str,
        tenant_id: str = "default",
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """
        Запустить профиль через правильный антидетект.
        Возвращает {"status": "ok", "ws_endpoint": "ws://..."}.
        """
        client = await self.client_for_profile(profile_id, tenant_id)
        if client is None:
            return _error(
                "Нет доступного антидетект-браузера. "
                "Добавьте хотя бы один в настройках."
            )
        last: dict[str, Any] = _error("Не удалось запустить профиль.")
        for attempt in range(1, max_attempts + 1):
            last = await client.start_profile(profile_id)
            if last.get("status") == "ok":
                return last
            if attempt < max_attempts:
                delay = 1.0 * (1.5 ** (attempt - 1))
                logger.warning(
                    "registry.start_profile %s attempt %d/%d failed, retry %.1fs",
                    profile_id, attempt, max_attempts, delay,
                )
                await asyncio.sleep(delay)
        return last

    async def stop_profile(
        self,
        profile_id: str,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """Остановить профиль. Не бросает исключений — используется в finally."""
        try:
            client = await self.client_for_profile(profile_id, tenant_id)
            if client is None:
                return _error("Нет клиента для остановки профиля.")
            return await client.stop_profile(profile_id)
        except Exception as exc:
            logger.exception("registry.stop_profile %s: %s", profile_id, exc)
            return _error(str(exc))

    # ── Sync ─────────────────────────────────────────────────────────────────

    async def sync_profiles(
        self,
        antidetect_id: int,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """
        Синхронизировать профили одного антидетекта в БД.
        """
        client = self.get_client(antidetect_id)
        if client is None:
            return _error(f"Антидетект id={antidetect_id} не найден в реестре.")
        res = await client.fetch_profiles()
        if res.get("status") != "ok":
            return res
        profiles = res.get("profiles") or []
        synced = 0
        for p in profiles:
            pid = str(p.get("profile_id") or "").strip()
            if not pid:
                continue
            raw = p.get("raw") if isinstance(p.get("raw"), dict) else {}
            r = await dbmod.upsert_adspower_profile(
                adspower_profile_id=pid,
                profile_name=str(p.get("name") or ""),
                group_name=_extract(raw, "group_name", "groupName", "group"),
                proxy_name=_extract(raw, "proxy_name", "proxyName", "proxy"),
                geo=_extract(raw, "geo", "country", "country_name"),
                language=_extract(raw, "language", "lang"),
                antidetect_id=antidetect_id,
                tenant_id=tenant_id,
                db_path=self._db_path,
            )
            if r.get("status") == "ok":
                synced += 1
        # Обновить last_synced_at антидетекта
        await dbmod.touch_antidetect_browser(antidetect_id, profiles_count=synced, db_path=self._db_path)
        return _ok({
            "antidetect_id": antidetect_id,
            "synced": synced,
            "total": len(profiles),
        })

    async def sync_all_profiles(self, tenant_id: str = "default") -> dict[str, Any]:
        """
        Синхронизировать профили из ВСЕХ активных антидетектов.
        """
        if not self._clients:
            return _error("Нет активных антидетект-браузеров в реестре.")
        results = []
        total_synced = 0
        for aid, client in list(self._clients.items()):
            r = await self.sync_profiles(aid, tenant_id)
            results.append({"antidetect_id": aid, **r})
            if r.get("status") == "ok":
                total_synced += int(r.get("synced") or 0)
        return _ok({"total_synced": total_synced, "results": results})

    # ── Verify ────────────────────────────────────────────────────────────────

    async def verify_all(self) -> dict[str, Any]:
        """Проверить связь со всеми антидетектами."""
        results = []
        for aid, client in list(self._clients.items()):
            r = await client.verify_connection()
            results.append({"antidetect_id": aid, **client.info(), **r})
        return _ok({"results": results, "count": len(results)})


# ── Utility ───────────────────────────────────────────────────────────────────

def _extract(d: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            name = v.get("name") or v.get("group_name") or v.get("proxy_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


# ── Process-level singleton ───────────────────────────────────────────────────

_registry: AntidetectRegistry | None = None


def get_registry(db_path: str | None = None) -> AntidetectRegistry:
    """
    Вернуть глобальный реестр (создаётся при первом обращении).
    db_path учитывается только при создании.
    """
    global _registry
    if _registry is None:
        _registry = AntidetectRegistry(db_path=db_path)
    return _registry


async def init_registry(db_path: str | None = None) -> AntidetectRegistry:
    """Инициализировать и загрузить реестр. Вызывается при старте сервера."""
    global _registry
    _registry = AntidetectRegistry(db_path=db_path)
    await _registry.load()
    return _registry
