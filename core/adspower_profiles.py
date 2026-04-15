from __future__ import annotations

import json
import logging
from typing import Any

from core import adspower_sync
from core import database as dbmod

logger = logging.getLogger(__name__)


def _error(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "error", "message": message}
    if data:
        out.update(data)
    return out


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def _raw_first(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_group_name(raw: dict[str, Any]) -> str | None:
    group = raw.get("group_name") or raw.get("groupName") or raw.get("group")
    if isinstance(group, dict):
        return _raw_first(group, "name", "group_name")
    if isinstance(group, str) and group.strip():
        return group.strip()
    return None


def _extract_proxy_name(raw: dict[str, Any]) -> str | None:
    proxy = raw.get("proxy_name") or raw.get("proxyName") or raw.get("proxy")
    if isinstance(proxy, dict):
        return _raw_first(proxy, "proxy_name", "name", "proxy_soft")
    if isinstance(proxy, str) and proxy.strip():
        return proxy.strip()
    user_proxy = raw.get("user_proxy_config")
    if isinstance(user_proxy, dict):
        return _raw_first(user_proxy, "proxy_soft", "proxy_name", "name")
    return None


def _extract_tags_json(raw: dict[str, Any]) -> str | None:
    for key in ("tags", "tag_list", "tagList"):
        val = raw.get(key)
        if isinstance(val, list):
            return json.dumps([str(x) for x in val], ensure_ascii=False)
        if isinstance(val, str) and val.strip():
            return json.dumps([x.strip() for x in val.split(",") if x.strip()], ensure_ascii=False)
    return None


async def record_profile_event(
    profile_id: str,
    event_type: str,
    message: str = "",
    payload: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    return await dbmod.record_profile_event(
        profile_id,
        event_type,
        message=message,
        payload_json=payload_json,
        tenant_id=tenant_id,
        db_path=db_path,
    )


async def sync_profiles_from_adspower(
    tenant_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        fetched = await adspower_sync.fetch_profiles()
        if fetched.get("status") != "ok":
            return fetched
        profiles = fetched.get("profiles") or []
        synced: list[dict[str, Any]] = []
        for item in profiles:
            if not isinstance(item, dict):
                continue
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
            profile_id = str(item.get("user_id") or "").strip()
            if not profile_id:
                continue
            upsert = await dbmod.upsert_adspower_profile(
                adspower_profile_id=profile_id,
                profile_name=str(item.get("name") or "").strip(),
                group_name=_extract_group_name(raw),
                proxy_name=_extract_proxy_name(raw),
                geo=_raw_first(raw, "geo", "country", "country_name"),
                language=_raw_first(raw, "language", "lang"),
                tags_json=_extract_tags_json(raw),
                tenant_id=tenant_id,
                db_path=db_path,
            )
            if upsert.get("status") != "ok":
                return upsert
            await record_profile_event(
                profile_id,
                "sync",
                message="Профиль синхронизирован из AdsPower.",
                payload={"raw": raw},
                tenant_id=tenant_id,
                db_path=db_path,
            )
            synced.append(
                {
                    "adspower_profile_id": profile_id,
                    "profile_name": str(item.get("name") or "").strip(),
                    "group_name": _extract_group_name(raw),
                    "proxy_name": _extract_proxy_name(raw),
                }
            )
        return _ok(
            {
                "message": "Профили AdsPower синхронизированы.",
                "count": len(synced),
                "profiles": synced,
            }
        )
    except Exception as exc:
        logger.exception("sync_profiles_from_adspower: %s", exc)
        return _error("Не удалось синхронизировать профили AdsPower.")


async def list_profiles(
    tenant_id: str | None = None,
    status_filter: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    return await dbmod.list_adspower_profiles(
        tenant_id=tenant_id,
        status_filter=status_filter,
        db_path=db_path,
    )


async def get_profile(
    profile_id: str,
    tenant_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    return await dbmod.get_adspower_profile(profile_id, tenant_id=tenant_id, db_path=db_path)


async def update_profile_status(
    profile_id: str,
    status: str,
    tenant_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    updated = await dbmod.update_adspower_profile_status(
        profile_id,
        status,
        tenant_id=tenant_id,
        db_path=db_path,
    )
    if updated.get("status") == "ok":
        await record_profile_event(
            profile_id,
            "status_changed",
            message=f"Статус профиля изменён на {status}.",
            payload={"status": status},
            tenant_id=tenant_id,
            db_path=db_path,
        )
    return updated


async def assign_profile_metadata(
    profile_id: str,
    tenant_id: str | None = None,
    db_path: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    updated = await dbmod.patch_adspower_profile(
        profile_id,
        tenant_id=tenant_id,
        db_path=db_path,
        **fields,
    )
    if updated.get("status") == "ok":
        await record_profile_event(
            profile_id,
            "metadata_updated",
            message="Метаданные профиля обновлены.",
            payload=fields,
            tenant_id=tenant_id,
            db_path=db_path,
        )
    return updated
