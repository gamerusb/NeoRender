"""
Абстрактные клиенты для антидетект-браузеров.

Поддерживаемые типы:
  - adspower   — AdsPower Local API (порт 50325)
  - dolphin    — Dolphin Anty Local API (порт 3001)
  - octo       — Octo Browser Local Agent (порт 58888)
  - multilogin — Multilogin Agent (порт 35000)

Каждый клиент реализует единый интерфейс:
  fetch_profiles() → list[{"profile_id", "name", "raw"}]
  start_profile(profile_id) → {"ws_endpoint": "ws://..."}
  stop_profile(profile_id) → {}
  verify_connection() → {"profiles_count": N}

Все методы возвращают {"status": "ok|error", ...} — исключения не выбрасываются наружу.
"""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import aiohttp
from aiohttp import ClientConnectorError

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=5)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _error(msg: str) -> dict[str, Any]:
    return {"status": "error", "message": msg}


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def _masked(key: str) -> str:
    if not key:
        return ""
    return f"{key[:4]}••••{key[-4:]}" if len(key) > 8 else "••••"


# ── Base class ────────────────────────────────────────────────────────────────

class AntidetectClient(ABC):
    """
    Единый интерфейс для любого антидетект-браузера.
    Конкретный экземпляр создаётся через AntidetectClientFactory.
    """

    def __init__(
        self,
        antidetect_id: int,
        api_url: str,
        api_key: str = "",
        use_auth: bool = False,
    ) -> None:
        self.antidetect_id = antidetect_id
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.use_auth = use_auth
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                connector = aiohttp.TCPConnector(
                    limit=10,
                    keepalive_timeout=60,
                    enable_cleanup_closed=True,
                )
                self._session = aiohttp.ClientSession(
                    timeout=_TIMEOUT,
                    connector=connector,
                )
        return self._session

    async def close(self) -> None:
        async with self._lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    def _auth_headers(self) -> dict[str, str]:
        if self.use_auth and self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def _get_json(self, path: str, **kwargs: Any) -> dict[str, Any] | None:
        """GET + JSON decode. None при любой ошибке."""
        url = f"{self.api_url}{path}"
        sess = await self._get_session()
        try:
            async with sess.get(url, headers=self._auth_headers(), **kwargs) as resp:
                raw = await resp.read()
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    logger.warning("[antidetect %s] non-json: %s", self.antidetect_id, raw[:200])
                    return None
        except ClientConnectorError as exc:
            logger.warning("[antidetect %s] connect error: %s", self.antidetect_id, exc)
            return None
        except Exception as exc:
            logger.exception("[antidetect %s] get_json error: %s", self.antidetect_id, exc)
            return None

    async def _post_json(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """POST JSON + decode. None при любой ошибке."""
        url = f"{self.api_url}{path}"
        sess = await self._get_session()
        try:
            async with sess.post(url, json=body or {}, headers=self._auth_headers()) as resp:
                raw = await resp.read()
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    return None
        except ClientConnectorError as exc:
            logger.warning("[antidetect %s] connect error: %s", self.antidetect_id, exc)
            return None
        except Exception as exc:
            logger.exception("[antidetect %s] post_json error: %s", self.antidetect_id, exc)
            return None

    @abstractmethod
    async def fetch_profiles(self) -> dict[str, Any]:
        """Возвращает {"status": "ok", "profiles": [{"profile_id", "name", "raw"}]}"""

    @abstractmethod
    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        """Возвращает {"status": "ok", "ws_endpoint": "ws://..."}"""

    @abstractmethod
    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        """Возвращает {"status": "ok"}"""

    async def verify_connection(self) -> dict[str, Any]:
        res = await self.fetch_profiles()
        if res.get("status") != "ok":
            return res
        profiles = res.get("profiles") or []
        return _ok({"profiles_count": len(profiles), "api_url": self.api_url})

    def info(self) -> dict[str, Any]:
        return {
            "antidetect_id": self.antidetect_id,
            "browser_type": self.__class__.__name__.lower().replace("client", ""),
            "api_url": self.api_url,
            "use_auth": self.use_auth,
            "api_key_masked": _masked(self.api_key),
        }


# ── AdsPower ─────────────────────────────────────────────────────────────────

class AdsPowerClient(AntidetectClient):
    """
    AdsPower Local API v1.
    Документация: https://localapi-doc-en.adspower.com
    """

    def _extract_ws(self, data: dict[str, Any]) -> str | None:
        ws_block = data.get("ws")
        if isinstance(ws_block, dict):
            for k in ("puppeteer", "puppteer", "selenium"):
                v = ws_block.get(k)
                if isinstance(v, str) and v.startswith("ws"):
                    return v
            if isinstance(ws_block, str) and ws_block.startswith("ws"):
                return ws_block
        for k in ("ws", "webdriver", "puppeteer"):
            v = data.get(k)
            if isinstance(v, str) and v.startswith("ws"):
                return v
        return None

    async def fetch_profiles(self) -> dict[str, Any]:
        payload = await self._get_json("/api/v1/user/list")
        if payload is None:
            return _error("AdsPower не отвечает. Убедитесь, что программа запущена.")
        code = payload.get("code")
        if code is not None and code != 0:
            return _error(str(payload.get("msg") or "Ошибка API AdsPower."))
        data = payload.get("data", {})
        raw_list = []
        if isinstance(data, dict):
            raw_list = data.get("list") or data.get("users") or []
        elif isinstance(data, list):
            raw_list = data
        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = (
                item.get("user_id") or item.get("id")
                or item.get("profile_id") or item.get("userId")
            )
            if not uid:
                continue
            profiles.append({
                "profile_id": str(uid),
                "name": str(item.get("name") or item.get("user_name") or item.get("remark") or uid),
                "raw": item,
            })
        return _ok({"profiles": profiles})

    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/api/v1/browser/start?user_id={profile_id}")
        if payload is None:
            return _error("AdsPower не отвечает при запуске профиля.")
        code = payload.get("code")
        if code is not None and code != 0:
            return _error(str(payload.get("msg") or "Не удалось запустить профиль AdsPower."))
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return _error("Неожиданный ответ AdsPower при запуске.")
        ws = self._extract_ws(data)
        if not ws:
            return _error("AdsPower не вернул ws_endpoint. Попробуйте ещё раз.")
        return _ok({"ws_endpoint": ws, "raw": data})

    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/api/v1/browser/stop?user_id={profile_id}")
        if payload is None:
            return _error("AdsPower не отвечает при остановке профиля.")
        return _ok({"raw": payload.get("data")})

    async def start_profile_with_retry(
        self, profile_id: str, max_attempts: int = 3, base_delay: float = 1.0
    ) -> dict[str, Any]:
        last: dict[str, Any] = _error("Не удалось запустить AdsPower профиль.")
        for attempt in range(1, max_attempts + 1):
            last = await self.start_profile(profile_id)
            if last.get("status") == "ok":
                return last
            if attempt < max_attempts:
                delay = base_delay * (1.5 ** (attempt - 1))
                logger.warning(
                    "[AdsPower %s] start attempt %d/%d failed, retry in %.1fs",
                    self.antidetect_id, attempt, max_attempts, delay,
                )
                await asyncio.sleep(delay)
        return last


# ── Dolphin Anty ─────────────────────────────────────────────────────────────

class DolphinClient(AntidetectClient):
    """
    Dolphin Anty Local API v1.0.
    Документация: https://docs.dolphin-anty.com/local-api
    Порт по умолчанию: 3001.
    """

    async def fetch_profiles(self) -> dict[str, Any]:
        # Dolphin возвращает paginated список; берём первые 200
        payload = await self._get_json("/v1.0/browser_profiles?limit=200&offset=0")
        if payload is None:
            return _error("Dolphin Anty не отвечает. Убедитесь, что приложение запущено.")
        if payload.get("success") is False:
            return _error(str(payload.get("message") or "Ошибка Dolphin Anty API."))
        raw_list = payload.get("data") or []
        if not isinstance(raw_list, list):
            raw_list = []
        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("id") or "").strip()
            if not uid:
                continue
            profiles.append({
                "profile_id": uid,
                "name": str(item.get("name") or uid),
                "raw": item,
            })
        return _ok({"profiles": profiles})

    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/v1.0/browser_profiles/{profile_id}/start?automation=1")
        if payload is None:
            return _error("Dolphin Anty не отвечает при запуске профиля.")
        if payload.get("success") is False:
            return _error(str(payload.get("message") or "Не удалось запустить профиль Dolphin."))
        automation = payload.get("automation") or {}
        if isinstance(automation, dict):
            ws = automation.get("wsEndpoint") or automation.get("ws_endpoint")
            if isinstance(ws, str) and ws.startswith("ws"):
                return _ok({"ws_endpoint": ws, "raw": automation})
        return _error("Dolphin Anty не вернул wsEndpoint.")

    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/v1.0/browser_profiles/{profile_id}/stop")
        if payload is None:
            return _error("Dolphin Anty не отвечает при остановке профиля.")
        return _ok({"raw": payload})


# ── Octo Browser ─────────────────────────────────────────────────────────────

class OctoClient(AntidetectClient):
    """
    Octo Browser Local Agent REST API.
    Порт по умолчанию: 58888.
    Документация: https://docs.octobrowser.net/local-api
    """

    async def fetch_profiles(self) -> dict[str, Any]:
        payload = await self._get_json("/api/profiles?limit=200&offset=0")
        if payload is None:
            return _error("Octo Browser не отвечает. Убедитесь, что агент запущен.")
        if not isinstance(payload, dict):
            return _error("Неожиданный ответ Octo Browser API.")
        raw_list = payload.get("data") or []
        if not isinstance(raw_list, list):
            raw_list = []
        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("uuid") or item.get("id") or "").strip()
            if not uid:
                continue
            profiles.append({
                "profile_id": uid,
                "name": str(item.get("title") or item.get("name") or uid),
                "raw": item,
            })
        return _ok({"profiles": profiles})

    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._post_json(f"/api/profiles/{profile_id}/start")
        if payload is None:
            return _error("Octo Browser не отвечает при запуске профиля.")
        data = payload.get("data") or {}
        if isinstance(data, dict):
            ws = data.get("wsEndpoint") or data.get("ws_endpoint") or data.get("ws")
            if isinstance(ws, str) and ws.startswith("ws"):
                return _ok({"ws_endpoint": ws, "raw": data})
        return _error("Octo Browser не вернул wsEndpoint.")

    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._post_json(f"/api/profiles/{profile_id}/stop")
        if payload is None:
            return _error("Octo Browser не отвечает при остановке профиля.")
        return _ok({"raw": payload})


# ── Multilogin ────────────────────────────────────────────────────────────────

class MultiloginClient(AntidetectClient):
    """
    Multilogin Agent Local API.
    Порт по умолчанию: 35000.
    Требует api_key (токен из /user/signin или Personal Access Token из UI).
    Документация: https://docs.multilogin.com/docs/local-api
    """

    def _auth_headers(self) -> dict[str, str]:
        # Multilogin использует просто Bearer без отдельного флага
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        return {"Accept": "application/json"}

    async def fetch_profiles(self) -> dict[str, Any]:
        payload = await self._get_json("/profile/list?folder=default&limit=200")
        if payload is None:
            return _error("Multilogin не отвечает. Убедитесь, что агент запущен.")
        # Multilogin возвращает список напрямую или в data
        raw_list: list[Any] = []
        if isinstance(payload, list):
            raw_list = payload
        elif isinstance(payload, dict):
            raw_list = payload.get("data") or payload.get("profiles") or []
        if not isinstance(raw_list, list):
            raw_list = []
        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("id") or item.get("profileId") or item.get("uuid") or "").strip()
            if not uid:
                continue
            profiles.append({
                "profile_id": uid,
                "name": str(item.get("name") or item.get("title") or uid),
                "raw": item,
            })
        return _ok({"profiles": profiles})

    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/profile/start?profileId={profile_id}")
        if payload is None:
            return _error("Multilogin не отвечает при запуске профиля.")
        if isinstance(payload, dict):
            # MLX возвращает value.browserWSEndpoint или прямо в корне
            value = payload.get("value") or {}
            if isinstance(value, dict):
                ws = value.get("browserWSEndpoint") or value.get("wsEndpoint")
            else:
                ws = None
            ws = ws or payload.get("browserWSEndpoint") or payload.get("wsEndpoint")
            if isinstance(ws, str) and ws.startswith("ws"):
                return _ok({"ws_endpoint": ws, "raw": payload})
        return _error("Multilogin не вернул browserWSEndpoint.")

    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/profile/stop?profileId={profile_id}")
        if payload is None:
            return _error("Multilogin не отвечает при остановке профиля.")
        return _ok({"raw": payload})


# ── GoLogin ──────────────────────────────────────────────────────────────────

class GoLoginClient(AntidetectClient):
    """
    GoLogin Local REST API.
    Порт по умолчанию: 36912.
    Документация: https://gologin.com/local-api
    API-ключ не требуется для локального агента.
    """

    async def fetch_profiles(self) -> dict[str, Any]:
        payload = await self._get_json("/browser_profiles?page=1&per_page=200")
        if payload is None:
            return _error("GoLogin не отвечает. Убедитесь, что приложение запущено.")
        # GoLogin возвращает { "data": [...] } или напрямую список
        raw_list: list[Any] = []
        if isinstance(payload, dict):
            raw_list = payload.get("data") or payload.get("profiles") or []
        elif isinstance(payload, list):
            raw_list = payload
        if not isinstance(raw_list, list):
            raw_list = []
        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("uuid") or item.get("id") or item.get("profile_id") or "").strip()
            if not uid:
                continue
            profiles.append({
                "profile_id": uid,
                "name": str(item.get("name") or item.get("title") or uid),
                "raw": item,
            })
        return _ok({"profiles": profiles})

    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        # GoLogin поддерживает и GET, и POST — пробуем GET сначала
        payload = await self._get_json(f"/browser_profiles/{profile_id}/start")
        if payload is None:
            # Fallback: POST
            payload = await self._post_json(f"/browser_profiles/{profile_id}/start")
        if payload is None:
            return _error("GoLogin не отвечает при запуске профиля.")
        if isinstance(payload, dict):
            ws = (
                payload.get("wsUrl") or payload.get("ws_url")
                or payload.get("wsEndpoint") or payload.get("webSocketDebuggerUrl")
            )
            if isinstance(ws, str) and ws.startswith("ws"):
                return _ok({"ws_endpoint": ws, "raw": payload})
            # Иногда GoLogin возвращает { data: { wsUrl: ... } }
            data = payload.get("data") or {}
            if isinstance(data, dict):
                ws = data.get("wsUrl") or data.get("wsEndpoint")
                if isinstance(ws, str) and ws.startswith("ws"):
                    return _ok({"ws_endpoint": ws, "raw": data})
        return _error("GoLogin не вернул wsUrl. Проверьте, что приложение обновлено.")

    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/browser_profiles/{profile_id}/stop")
        if payload is None:
            payload = await self._post_json(f"/browser_profiles/{profile_id}/stop")
        if payload is None:
            return _error("GoLogin не отвечает при остановке профиля.")
        return _ok({"raw": payload})


# ── Undetectable.io ───────────────────────────────────────────────────────────

class UndetectableClient(AntidetectClient):
    """
    Undetectable.io Local API.
    Порт по умолчанию: 25325.
    Документация: https://undetectable.io/docs/local-api
    """

    async def fetch_profiles(self) -> dict[str, Any]:
        # Undetectable принимает GET /list с опциональным ?status=Active
        payload = await self._get_json("/list?status=Active&page=0&pageLen=200")
        if payload is None:
            # Fallback без параметров
            payload = await self._get_json("/list")
        if payload is None:
            return _error("Undetectable не отвечает. Убедитесь, что приложение запущено.")
        raw_list: list[Any] = []
        if isinstance(payload, list):
            raw_list = payload
        elif isinstance(payload, dict):
            raw_list = payload.get("data") or payload.get("profiles") or payload.get("list") or []
        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("id") or item.get("uuid") or item.get("profile_id") or "").strip()
            if not uid:
                continue
            profiles.append({
                "profile_id": uid,
                "name": str(item.get("name") or item.get("title") or uid),
                "raw": item,
            })
        return _ok({"profiles": profiles})

    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._post_json("/start", {"profile_id": profile_id})
        if payload is None:
            # Fallback: GET-стиль
            payload = await self._get_json(f"/start?profile_id={profile_id}")
        if payload is None:
            return _error("Undetectable не отвечает при запуске профиля.")
        if isinstance(payload, dict):
            ws = (
                payload.get("wsUrl") or payload.get("ws_url")
                or payload.get("wsEndpoint") or payload.get("ws")
            )
            if isinstance(ws, str) and ws.startswith("ws"):
                return _ok({"ws_endpoint": ws, "raw": payload})
            data = payload.get("data") or {}
            if isinstance(data, dict):
                ws = data.get("wsUrl") or data.get("wsEndpoint")
                if isinstance(ws, str) and ws.startswith("ws"):
                    return _ok({"ws_endpoint": ws, "raw": data})
        return _error("Undetectable не вернул wsUrl.")

    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._post_json("/stop", {"profile_id": profile_id})
        if payload is None:
            payload = await self._get_json(f"/stop?profile_id={profile_id}")
        if payload is None:
            return _error("Undetectable не отвечает при остановке профиля.")
        return _ok({"raw": payload})


# ── MoreLogin ─────────────────────────────────────────────────────────────────

class MoreLoginClient(AntidetectClient):
    """
    MoreLogin Local API.
    Порт по умолчанию: 8888.
    Популярен для UBT-арбитража.
    Документация: https://www.morelogin.com/blog/api-guide
    Требует api_key (токен из настроек приложения).
    """

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            }
        return {"Content-Type": "application/json"}

    async def fetch_profiles(self) -> dict[str, Any]:
        payload = await self._post_json("/api/env/list", {"page": 1, "pageSize": 200})
        if payload is None:
            return _error("MoreLogin не отвечает. Убедитесь, что приложение запущено.")
        if isinstance(payload, dict) and payload.get("code") not in (0, None, "0", "success"):
            return _error(str(payload.get("msg") or payload.get("message") or "Ошибка MoreLogin API."))
        data = (payload.get("data") or {}) if isinstance(payload, dict) else {}
        raw_list: list[Any] = []
        if isinstance(data, dict):
            raw_list = data.get("dataList") or data.get("list") or data.get("profiles") or []
        elif isinstance(data, list):
            raw_list = data
        profiles: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("envId") or item.get("id") or item.get("profile_id") or "").strip()
            if not uid:
                continue
            profiles.append({
                "profile_id": uid,
                "name": str(item.get("envName") or item.get("name") or uid),
                "raw": item,
            })
        return _ok({"profiles": profiles})

    async def start_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._post_json("/api/env/start", {"envId": profile_id})
        if payload is None:
            return _error("MoreLogin не отвечает при запуске профиля.")
        if isinstance(payload, dict):
            data = payload.get("data") or {}
            if isinstance(data, dict):
                ws = (
                    data.get("ws") or data.get("wsUrl") or data.get("wsEndpoint")
                    or data.get("webSocketDebuggerUrl")
                )
                if isinstance(ws, str) and ws.startswith("ws"):
                    return _ok({"ws_endpoint": ws, "raw": data})
            # Иногда прямо в корне ответа
            ws = payload.get("ws") or payload.get("wsUrl") or payload.get("wsEndpoint")
            if isinstance(ws, str) and ws.startswith("ws"):
                return _ok({"ws_endpoint": ws, "raw": payload})
        return _error("MoreLogin не вернул wsEndpoint.")

    async def stop_profile(self, profile_id: str) -> dict[str, Any]:
        payload = await self._post_json("/api/env/close", {"envId": profile_id})
        if payload is None:
            return _error("MoreLogin не отвечает при остановке профиля.")
        return _ok({"raw": payload})


# ── Factory ───────────────────────────────────────────────────────────────────

_BROWSER_TYPES: dict[str, type[AntidetectClient]] = {
    "adspower":      AdsPowerClient,
    "dolphin":       DolphinClient,
    "octo":          OctoClient,
    "multilogin":    MultiloginClient,
    "gologin":       GoLoginClient,
    "undetectable":  UndetectableClient,
    "morelogin":     MoreLoginClient,
}

_DEFAULT_PORTS: dict[str, int] = {
    "adspower":      50325,
    "dolphin":       3001,
    "octo":          58888,
    "multilogin":    35000,
    "gologin":       36912,
    "undetectable":  25325,
    "morelogin":     8888,
}


def default_url(browser_type: str) -> str:
    port = _DEFAULT_PORTS.get(browser_type, 50325)
    return f"http://127.0.0.1:{port}"


def create_client(
    antidetect_id: int,
    browser_type: str,
    api_url: str,
    api_key: str = "",
    use_auth: bool = False,
) -> AntidetectClient:
    """
    Создать клиент нужного типа.

    Raises ValueError если browser_type не поддерживается.
    """
    cls = _BROWSER_TYPES.get(browser_type.lower())
    if cls is None:
        supported = ", ".join(_BROWSER_TYPES)
        raise ValueError(
            f"Неизвестный тип антидетект-браузера: {browser_type!r}. "
            f"Поддерживаются: {supported}."
        )
    return cls(antidetect_id=antidetect_id, api_url=api_url, api_key=api_key, use_auth=use_auth)


SUPPORTED_BROWSER_TYPES: list[str] = list(_BROWSER_TYPES)
