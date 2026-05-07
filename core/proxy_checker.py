"""
Proxy health checker для NeoRender Pro.

check_proxy()      — проверить одну прокси (ping через httpbin)
check_all_proxies() — пакетная проверка всех прокси тенанта
rotate_proxy()      — выбрать живую прокси из той же группы

Результаты пишутся в БД через update_proxy_check_result().
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Публичный сервис для определения реального IP и гео
_IP_CHECK_URLS = [
    "http://ip-api.com/json/?fields=status,country,countryCode,city,query",
    "http://ipinfo.io/json",
]
_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)
_SLOW_THRESHOLD_MS = 2000   # >2s считается slow
_CONCURRENT = 10            # параллельных проверок


def _proxy_url(row: dict[str, Any]) -> str:
    proto   = row.get("protocol") or "http"
    host    = row.get("host") or ""
    port    = int(row.get("port") or 0)
    user    = row.get("username") or ""
    pw      = row.get("password") or ""
    if user and pw:
        return f"{proto}://{user}:{pw}@{host}:{port}"
    return f"{proto}://{host}:{port}"


async def check_proxy(
    proxy_id: int,
    host: str,
    port: int,
    protocol: str = "http",
    username: str = "",
    password: str = "",
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Проверить прокси.
    Возвращает {"status": "alive"|"slow"|"dead", "latency_ms": N, "detected_ip": "...", "geo": "..."}
    Записывает результат в БД.
    """
    row = {"protocol": protocol, "host": host, "port": port,
           "username": username, "password": password}
    proxy_url = _proxy_url(row)

    connector = aiohttp.TCPConnector(ssl=False)
    result: dict[str, Any] = {"status": "dead", "latency_ms": None,
                               "detected_ip": None, "geo": None, "geo_city": None}
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=_TIMEOUT) as session:
            for url in _IP_CHECK_URLS:
                try:
                    t0 = time.monotonic()
                    async with session.get(url, proxy=proxy_url) as resp:
                        latency_ms = int((time.monotonic() - t0) * 1000)
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            detected_ip = (
                                data.get("query") or
                                data.get("ip") or
                                None
                            )
                            geo = (
                                data.get("countryCode") or
                                data.get("country") or
                                None
                            )
                            geo_city = data.get("city")
                            status = "slow" if latency_ms > _SLOW_THRESHOLD_MS else "alive"
                            result = {
                                "status": status,
                                "latency_ms": latency_ms,
                                "detected_ip": detected_ip,
                                "geo": geo,
                                "geo_city": geo_city,
                            }
                            break
                except Exception:
                    continue
    except Exception as exc:
        logger.debug("proxy check %s:%s failed: %s", host, port, exc)

    # Persist to DB
    try:
        from core import database as dbmod
        await dbmod.update_proxy_check_result(
            proxy_id=proxy_id,
            status=result["status"],
            latency_ms=result.get("latency_ms"),
            detected_ip=result.get("detected_ip"),
            geo=result.get("geo"),
            geo_city=result.get("geo_city"),
            db_path=db_path,
        )
    except Exception as exc:
        logger.warning("persist proxy result %s: %s", proxy_id, exc)

    return {"proxy_id": proxy_id, **result}


async def check_all_proxies(
    tenant_id: str = "default",
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Проверить все прокси тенанта параллельно (до _CONCURRENT одновременно).
    Возвращает агрегированный результат.
    """
    from core import database as dbmod

    res = await dbmod.list_proxies(tenant_id=tenant_id, db_path=db_path)
    if res.get("status") != "ok":
        return res

    proxies: list[dict] = res.get("proxies") or []
    if not proxies:
        return {"status": "ok", "checked": 0, "results": []}

    sem = asyncio.Semaphore(_CONCURRENT)

    async def _check_one(p: dict) -> dict:
        async with sem:
            return await check_proxy(
                proxy_id=int(p["id"]),
                host=str(p["host"]),
                port=int(p["port"]),
                protocol=str(p.get("protocol") or "http"),
                username=str(p.get("username") or ""),
                password=str(p.get("password") or ""),
                db_path=db_path,
            )

    results = await asyncio.gather(*[_check_one(p) for p in proxies])
    alive = sum(1 for r in results if r.get("status") == "alive")
    slow  = sum(1 for r in results if r.get("status") == "slow")
    dead  = sum(1 for r in results if r.get("status") == "dead")
    return {
        "status": "ok",
        "checked": len(results),
        "alive": alive,
        "slow": slow,
        "dead": dead,
        "results": list(results),
    }


async def rotate_proxy_for_profile(
    profile_id: str,
    tenant_id: str = "default",
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Выбрать следующую живую прокси из той же группы что у профиля.
    Назначает автоматически и возвращает прокси.
    Если живых нет — возвращает error.
    """
    from core import database as dbmod

    # Получить текущую прокси и её группу
    cur_res = await dbmod.get_profile_proxy(profile_id, tenant_id=tenant_id, db_path=db_path)
    cur_proxy = cur_res.get("proxy") or {}
    group = cur_proxy.get("group_name") or ""

    # Найти живые прокси из той же группы
    list_res = await dbmod.list_proxies(tenant_id=tenant_id, group_name=group or None, db_path=db_path)
    candidates = [
        p for p in (list_res.get("proxies") or [])
        if p.get("status") in ("alive", "slow")
        and p.get("id") != cur_proxy.get("id")
    ]

    if not candidates:
        # Если группа не помогла — ищем любую живую
        all_res = await dbmod.list_proxies(tenant_id=tenant_id, db_path=db_path)
        candidates = [
            p for p in (all_res.get("proxies") or [])
            if p.get("status") in ("alive", "slow")
            and p.get("id") != cur_proxy.get("id")
        ]

    if not candidates:
        return {"status": "error", "message": "Нет живых прокси для ротации."}

    # Выбрать прокси с наименьшей задержкой
    best = min(candidates, key=lambda p: int(p.get("latency_ms") or 9999))
    await dbmod.assign_proxy_to_profile(
        profile_id=profile_id,
        proxy_id=int(best["id"]),
        tenant_id=tenant_id,
        db_path=db_path,
    )
    return {"status": "ok", "proxy": best, "profile_id": profile_id}


def parse_proxy_line(line: str) -> dict[str, Any] | None:
    """
    Парсит строку прокси в форматах:
      host:port
      host:port:user:pass
      protocol://host:port
      protocol://user:pass@host:port
    Возвращает dict или None если строка невалидна.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    protocol = "http"
    username = ""
    password = ""

    # Извлечь протокол
    if "://" in line:
        protocol, rest = line.split("://", 1)
        protocol = protocol.lower()
        line = rest

    # Извлечь user:pass@
    if "@" in line:
        creds, line = line.rsplit("@", 1)
        parts = creds.split(":", 1)
        username = parts[0] if parts else ""
        password = parts[1] if len(parts) > 1 else ""

    # Извлечь host:port[:user:pass] (legacy format)
    parts = line.split(":")
    if len(parts) == 4 and not username:
        host, port_str, username, password = parts
    elif len(parts) >= 2:
        host = parts[0]
        port_str = parts[1]
    else:
        return None

    try:
        port = int(port_str)
    except ValueError:
        return None

    if not host or not (1 <= port <= 65535):
        return None
    if protocol not in ("http", "https", "socks5"):
        protocol = "http"

    return {
        "host": host.strip(),
        "port": port,
        "protocol": protocol,
        "username": username.strip(),
        "password": password.strip(),
    }
