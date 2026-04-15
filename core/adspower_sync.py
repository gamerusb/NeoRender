"""
Синхронизация с локальным API AdsPower.

Базовый URL по умолчанию: http://127.0.0.1:50325
Переопределение: переменная окружения ADSPOWER_API_URL или configure_api_base() из UI.

verify_connection / verify_and_sync_db — проверка «софт ↔ антидетект» без traceback в UI.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import asyncio
import aiohttp
from aiohttp import ClientConnectorError

# По умолчанию локальный API AdsPower. Переопределение: ADSPOWER_API_URL или configure_api_base().
_DEFAULT_ADSPOWER = "http://127.0.0.1:50325"
# Оптимизированные таймауты для локального API (127.0.0.1 не должен отвечать медленнее 5 сек).
_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=5)

logger = logging.getLogger(__name__)

# ── Singleton aiohttp session ─────────────────────────────────────────────────
# Переиспользуем TCP-соединение между вызовами — устраняет overhead TCP-хэндшейка
# на каждый запрос к локальному AdsPower API (~200-500мс экономии на вызов).
_shared_session: aiohttp.ClientSession | None = None
_session_lock: asyncio.Lock | None = None


def _get_session_lock() -> asyncio.Lock:
    """Lazy-создание Lock (нельзя создавать до старта event loop)."""
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


async def _get_shared_session() -> aiohttp.ClientSession:
    """Возвращает (и при необходимости создаёт) глобальную aiohttp.ClientSession."""
    global _shared_session
    async with _get_session_lock():
        if _shared_session is None or _shared_session.closed:
            connector = aiohttp.TCPConnector(
                limit=10,              # до 10 параллельных соединений
                keepalive_timeout=60,  # keep-alive 60 сек
                enable_cleanup_closed=True,
            )
            _shared_session = aiohttp.ClientSession(
                timeout=_DEFAULT_TIMEOUT,
                connector=connector,
            )
    return _shared_session


def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def get_adspower_base() -> str:
    """Текущий базовый URL API AdsPower (без завершающего /)."""
    try:
        raw = (os.environ.get("ADSPOWER_API_URL") or _DEFAULT_ADSPOWER).strip().rstrip("/")
        return raw if raw else _DEFAULT_ADSPOWER
    except Exception:
        return _DEFAULT_ADSPOWER


def get_adspower_api_key() -> str:
    """Текущий API key AdsPower для Bearer Authorization (если включена проверка API)."""
    try:
        return (os.environ.get("ADSPOWER_API_KEY") or "").strip()
    except Exception:
        return ""


def is_adspower_auth_enabled() -> bool:
    """Флаг отправки Authorization: Bearer <key> в Local API AdsPower."""
    try:
        raw = (os.environ.get("ADSPOWER_USE_AUTH") or "").strip().lower()
        return raw in {"1", "true", "yes", "on"}
    except Exception:
        return False


def _masked_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "••••"
    return f"{key[:4]}••••{key[-4:]}"


def configure_api_base(url: str | None) -> dict[str, Any]:
    """
    Сохранить адрес API антидетекта в переменной окружения процесса.

    Пустая строка / None — сброс к значению по умолчанию (127.0.0.1:50325).
    Для постоянного хранения между перезапусками запишите в .env или реестр на стороне UI.
    """
    try:
        if not url or not str(url).strip():
            os.environ.pop("ADSPOWER_API_URL", None)
            return _ok(
                {
                    "api_base": get_adspower_base(),
                    "cleared": True,
                    "message": "Используется адрес по умолчанию.",
                }
            )
        u = str(url).strip().rstrip("/")
        if not u.startswith(("http://", "https://")):
            return _error("Адрес должен начинаться с http:// или https://")
        os.environ["ADSPOWER_API_URL"] = u
        return _ok(
            {
                "api_base": get_adspower_base(),
                "saved": True,
                "message": "Адрес API сохранён для этой сессии программы.",
            }
        )
    except Exception as exc:
        logger.exception("configure_api_base: %s", exc)
        return _error("Не удалось сохранить настройки AdsPower.")


def configure_api_settings(
    url: str | None = None,
    api_key: str | None = None,
    use_auth: bool | None = None,
) -> dict[str, Any]:
    """
    Сохранить базовый URL, API key и флаг авторизации для текущей сессии процесса.
    """
    try:
        base_res = configure_api_base(url)
        if base_res.get("status") != "ok":
            return base_res

        if api_key is not None:
            key = str(api_key).strip()
            if key:
                os.environ["ADSPOWER_API_KEY"] = key
            else:
                os.environ.pop("ADSPOWER_API_KEY", None)

        if use_auth is not None:
            os.environ["ADSPOWER_USE_AUTH"] = "1" if bool(use_auth) else "0"

        return _ok(
            {
                "api_base": get_adspower_base(),
                "use_auth": is_adspower_auth_enabled(),
                "api_key_masked": _masked_key(get_adspower_api_key()),
                "message": "Настройки AdsPower сохранены для текущей сессии программы.",
            }
        )
    except Exception as exc:
        logger.exception("configure_api_settings: %s", exc)
        return _error("Не удалось сохранить настройки AdsPower.")


def get_api_settings_status() -> dict[str, Any]:
    """Статус настроек AdsPower для UI."""
    try:
        key = get_adspower_api_key()
        return _ok(
            {
                "api_base": get_adspower_base(),
                "use_auth": is_adspower_auth_enabled(),
                "api_key_configured": bool(key),
                "api_key_masked": _masked_key(key),
            }
        )
    except Exception as exc:
        logger.exception("get_api_settings_status: %s", exc)
        return _error("Не удалось прочитать настройки AdsPower.")


def _build_headers() -> dict[str, str]:
    """Заголовки для Local API AdsPower, включая Bearer API key при включенной проверке API."""
    headers: dict[str, str] = {}
    if is_adspower_auth_enabled():
        key = get_adspower_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
    return headers


async def verify_connection() -> dict[str, Any]:
    """
    Проверка связи: AdsPower отвечает, список профилей читается.
    БД не трогает — только «достучались ли мы до антидетекта».
    """
    try:
        res = await fetch_profiles()
        if res.get("status") != "ok":
            return res
        profiles = res.get("profiles") or []
        return _ok(
            {
                "message": "Софт и AdsPower на связи. API отвечает.",
                "profiles_count": len(profiles),
                "api_base": get_adspower_base(),
                "synced_to_db": False,
            }
        )
    except Exception as exc:
        logger.exception("verify_connection: %s", exc)
        return _error("Не удалось проверить связь с AdsPower.")


async def verify_and_sync_db(
    tenant_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Сначала проверка API, затем синхронизация профилей в локальную БД.
    Удобно для кнопки «Проверить и синхронизировать» в настройках.
    """
    try:
        conn = await verify_connection()
        if conn.get("status") != "ok":
            return conn
        sync = await fetch_profiles_and_sync_db(db_path=db_path, tenant_id=tenant_id)
        if sync.get("status") != "ok":
            return sync
        n = int(sync.get("count") or 0)
        return _ok(
            {
                "message": "AdsPower работает, профили загружены в базу.",
                "profiles_count": n,
                "api_base": get_adspower_base(),
                "synced_to_db": True,
            }
        )
    except Exception as exc:
        logger.exception("verify_and_sync_db: %s", exc)
        return _error("Проверка или синхронизация с AdsPower не удалась.")


def _friendly_ads_power_offline() -> dict[str, str]:
    """Текст для нетехнической аудитории при недоступности порта 50325."""
    return _error(
        "AdsPower не запущен. Пожалуйста, откройте AdsPower."
    )


async def _get_json(
    session: aiohttp.ClientSession,
    url: str,
) -> dict[str, Any] | tuple[None, str]:
    """
    Выполнить GET и распарсить JSON.
    Возвращает либо dict, либо (None, короткое сообщение для лога/внутреннего use).
    """
    try:
        async with session.get(url, timeout=_DEFAULT_TIMEOUT, headers=_build_headers()) as resp:
            raw = await resp.read()
            try:
                payload: Any = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                logger.warning(
                    "adspower non-json response: %s",
                    raw[:500].decode("utf-8", errors="replace"),
                )
                return None, "invalid_json"

            if not isinstance(payload, dict):
                return None, "not_dict"

            # Некоторые версии API возвращают HTTP 200 даже при code != 0
            code = payload.get("code")
            if code is not None and code != 0:
                msg = str(payload.get("msg") or payload.get("message") or "ошибка API")
                logger.warning("adspower api code=%s msg=%s", code, msg)
                return None, msg

            return payload
    except ClientConnectorError:
        raise
    except aiohttp.ClientError as exc:
        logger.exception("adspower request failed: %s", exc)
        return None, "client_error"
    except TimeoutError:
        logger.warning("adspower request timeout: %s", url)
        return None, "timeout"
    except Exception as exc:
        logger.exception("adspower unexpected: %s", exc)
        return None, "unexpected"


def _extract_ws_endpoint(data: Any) -> str | None:
    """
    Достать ws endpoint из ответа /browser/start.

    В документации AdsPower часто: data.ws.puppeteer; оставляем запасные варианты.
    """
    if not isinstance(data, dict):
        return None

    ws_block = data.get("ws")
    if isinstance(ws_block, dict):
        for key in ("puppeteer", "puppteer", "selenium"):
            val = ws_block.get(key)
            if isinstance(val, str) and val.startswith("ws"):
                return val
        # Иногда одна строка на весь блок
        if isinstance(ws_block, str) and ws_block.startswith("ws"):
            return ws_block

    # Реже: плоско в data
    for key in ("ws", "webdriver", "debug_port", "puppeteer"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("ws"):
            return val

    return None


async def fetch_profiles(
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """
    GET /api/v1/user/list — список профилей AdsPower.

    Возвращает {"status": "ok", "profiles": [...]} где каждый элемент —
    нормализованный словарь с полями user_id, name (если есть в ответе).
    """
    url = f"{get_adspower_base()}/api/v1/user/list"
    _own_session = session is None
    try:
        sess = session if session is not None else await _get_shared_session()
        try:
            result = await _get_json(sess, url)
        except ClientConnectorError:
            return _friendly_ads_power_offline()

        if isinstance(result, tuple):
            return _error("Не удалось связаться с AdsPower. Проверьте, что программа запущена.")

        data = result.get("data")
        raw_list: list[Any] = []
        if isinstance(data, dict):
            raw_list = data.get("list") or data.get("users") or []
        elif isinstance(data, list):
            raw_list = data

        if not isinstance(raw_list, list):
            raw_list = []

        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = (
                item.get("user_id")
                or item.get("id")
                or item.get("profile_id")
                or item.get("userId")
            )
            if uid is None:
                continue
            name = (
                item.get("name")
                or item.get("user_name")
                or item.get("remark")
                or str(uid)
            )
            profiles.append(
                {
                    "user_id": str(uid),
                    "name": str(name),
                    "raw": item,
                }
            )

        return _ok({"profiles": profiles})
    except ClientConnectorError:
        return _friendly_ads_power_offline()
    except Exception as exc:
        logger.exception("fetch_profiles: %s", exc)
        return _error("Произошла ошибка при загрузке профилей AdsPower.")


async def start_profile(
    profile_id: str,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """
    GET /api/v1/browser/start?user_id=...

    Успех: {"status": "ok", "ws_endpoint": "ws://...", "raw": {...}}.
    """
    if not profile_id or not str(profile_id).strip():
        return _error("Не указан профиль AdsPower.")

    uid = str(profile_id).strip()
    url = f"{get_adspower_base()}/api/v1/browser/start?user_id={uid}"
    try:
        sess = session if session is not None else await _get_shared_session()
        try:
            result = await _get_json(sess, url)
        except ClientConnectorError:
            return _friendly_ads_power_offline()

        if isinstance(result, tuple):
            return _error("Не удалось запустить браузер профиля. Попробуйте ещё раз.")

        data = result.get("data")
        if not isinstance(data, dict):
            return _error("AdsPower вернул неожиданный ответ. Перезапустите профиль вручную.")

        ws = _extract_ws_endpoint(data)
        if not ws:
            logger.warning("start_profile: no ws in data keys=%s", list(data.keys()))
            return _error(
                "Не удалось получить адрес браузера. Откройте профиль в AdsPower и повторите."
            )

        return _ok({"ws_endpoint": ws, "raw": data})
    except ClientConnectorError:
        return _friendly_ads_power_offline()
    except Exception as exc:
        logger.exception("start_profile: %s", exc)
        return _error("Ошибка при запуске браузера AdsPower.")


async def start_profile_with_retry(
    profile_id: str,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> dict[str, Any]:
    """
    Запуск профиля с exponential backoff (попытки: 3, задержки: 1s → 1.5s → 2.25s).
    Оптимизировано для локального API (127.0.0.1): маленькие задержки, быстрый отклик.
    Используйте вместо start_profile() в пайплайне.
    """
    last: dict[str, Any] = _error("Не удалось запустить браузер AdsPower.")
    for attempt in range(1, max_attempts + 1):
        last = await start_profile(profile_id)
        if last.get("status") == "ok":
            return last
        if attempt < max_attempts:
            delay = base_delay * (1.5 ** (attempt - 1))  # 1.0s → 1.5s → 2.25s
            logger.warning(
                "start_profile attempt %d/%d failed (%s), retry in %.1fs",
                attempt, max_attempts, last.get("message", ""), delay,
            )
            await asyncio.sleep(delay)
    return last


async def stop_profile(
    profile_id: str,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """
    GET /api/v1/browser/stop?user_id=...

    Безопасно закрыть профиль после загрузки (оркестратор должен вызывать в finally).
    """
    if not profile_id or not str(profile_id).strip():
        return _error("Не указан профиль AdsPower.")

    uid = str(profile_id).strip()
    url = f"{get_adspower_base()}/api/v1/browser/stop?user_id={uid}"
    try:
        sess = session if session is not None else await _get_shared_session()
        try:
            result = await _get_json(sess, url)
        except ClientConnectorError:
            return _friendly_ads_power_offline()

        if isinstance(result, tuple):
            return _error("Не удалось остановить браузер профиля.")

        return _ok({"raw": result.get("data")})
    except ClientConnectorError:
        return _friendly_ads_power_offline()
    except Exception as exc:
        logger.exception("stop_profile: %s", exc)
        return _error("Ошибка при остановке браузера AdsPower.")


async def fetch_profiles_and_sync_db(
    db_path: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Удобная обёртка: подтянуть профили из AdsPower и сохранить в локальную БД.

    Импорт внутри функции — чтобы избежать циклических импортов при старте.
    """
    try:
        from core import database as dbmod
    except ImportError:
        try:
            import database as dbmod  # type: ignore
        except ImportError:
            logger.exception("fetch_profiles_and_sync_db: database module missing")
            return _error("Внутренняя ошибка модулей. Перезапустите приложение.")

    try:
        res = await fetch_profiles()
        if res.get("status") != "ok":
            return res

        profiles = res.get("profiles") or []
        for p in profiles:
            uid = p.get("user_id")
            name = p.get("name") or ""
            if uid:
                sync = await dbmod.upsert_profile(
                    adspower_id=str(uid),
                    name=str(name),
                    status="synced",
                    tenant_id=tenant_id,
                    db_path=db_path,
                )
                if sync.get("status") != "ok":
                    return sync

        return _ok({"count": len(profiles), "profiles": profiles})
    except Exception as exc:
        logger.exception("fetch_profiles_and_sync_db: %s", exc)
        return _error("Не удалось синхронизировать профили с базой данных.")
