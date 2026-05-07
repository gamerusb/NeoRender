"""
Cookie Farmer — автоматическое обновление и обогащение cookie-профилей.

Что делает за один цикл:
  1. Берёт batch_size профилей из БД (status in ready/active/new)
     с учётом «давности» — первыми идут профили, которые не фармились дольше всего
  2. Для каждого профиля (параллельно, через Semaphore):
       a. Открывает AdsPower-профиль
       b. Посещает 5–9 сайтов (Google, новости, lifestyle, Reddit…) —
          это строит разнообразный cookie-профиль за пределами YouTube
       c. Делает 2–3 Google-поиска с человекоподобными паузами
       d. Запускает быстрый YouTube-прогрев (intensity=light, без DB-сессии)
       e. Сохраняет бэкап cookies через AdsPower API
       f. Закрывает профиль
  3. Обновляет in-memory состояние и историю

Шедулер поднимается через start() / stop().
Ручной запуск одного профиля — farm_now(profile_id, tenant_id).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import database as dbmod
    from .tenancy import normalize_tenant_id
except ImportError:
    from core import database as dbmod
    from core.tenancy import normalize_tenant_id

logger = logging.getLogger(__name__)

_COOKIE_BACKUPS_DIR = Path(__file__).resolve().parent.parent / "data" / "cookie_backups"

# ── Конфиг ────────────────────────────────────────────────────────────────────

@dataclass
class CookieFarmerConfig:
    tenant_id: str = "default"
    interval_sec: int = 1800        # интервал между циклами (мин. 30 сек)
    batch_size: int = 5             # профилей за один цикл
    concurrency: int = 2            # параллельных браузеров
    warmup_intensity: str = "light" # light / medium / deep
    niche: str = "general"          # ниша (ключевые слова для YouTube-прогрева)
    adspower_api_url: str = "http://127.0.0.1:50325"
    min_farm_interval_sec: int = 3600  # минимальный интервал между фармингом одного профиля


# ── Пулы сайтов для web-browsing ──────────────────────────────────────────────

_NEWS_SITES: list[tuple[str, str]] = [
    ("https://www.bbc.com/news",          "BBC News"),
    ("https://www.reuters.com",           "Reuters"),
    ("https://edition.cnn.com",           "CNN"),
    ("https://www.nbcnews.com",           "NBC News"),
    ("https://news.yahoo.com",            "Yahoo News"),
    ("https://www.theguardian.com",       "The Guardian"),
    ("https://apnews.com",                "AP News"),
    ("https://www.nytimes.com",           "NY Times"),
    ("https://www.foxnews.com",           "Fox News"),
    ("https://www.msn.com",               "MSN"),
]

_LIFESTYLE_SITES: list[tuple[str, str]] = [
    ("https://www.reddit.com",            "Reddit"),
    ("https://www.buzzfeed.com",          "BuzzFeed"),
    ("https://www.huffpost.com",          "HuffPost"),
    ("https://www.vice.com",              "Vice"),
    ("https://www.complex.com",           "Complex"),
    ("https://www.sportskeeda.com",       "Sportskeeda"),
    ("https://www.menshealth.com",        "Men's Health"),
    ("https://www.theverge.com",          "The Verge"),
    ("https://www.engadget.com",          "Engadget"),
    ("https://techcrunch.com",            "TechCrunch"),
]

_GOOGLE_QUERIES: list[str] = [
    "best youtube shorts 2024",
    "trending videos this week",
    "how to cook pasta at home",
    "morning workout routine",
    "best travel destinations europe",
    "smartphone comparison 2024",
    "funny cats compilation",
    "satisfying videos compilation",
    "daily vlog tips",
    "ambient music for studying",
    "top 10 movies 2024",
    "street food tour asia",
    "productivity hacks morning",
    "minimalist room decor ideas",
    "language learning tips beginner",
]


# ── In-memory state ────────────────────────────────────────────────────────────

_QUARANTINE_THRESHOLD = 3       # ошибок подряд → карантин
_QUARANTINE_DURATION_SEC = 3600  # карантин на 1 час


@dataclass
class _ProfileFarmState:
    profile_id: str
    last_farmed_at: datetime | None = None
    last_error: str | None = None
    total_farmed: int = 0
    last_result: dict[str, Any] = field(default_factory=dict)
    consecutive_failures: int = 0
    quarantined: bool = False
    quarantined_at: datetime | None = None


_tasks: dict[str, asyncio.Task[None]] = {}
_states: dict[str, dict[str, Any]] = {}            # tenant_id → global state
_profile_states: dict[str, _ProfileFarmState] = {} # profile_id → per-profile state
_manual_tasks: dict[str, asyncio.Task[None]] = {}  # profile_id → manual task


def _global_state(tenant_id: str) -> dict[str, Any]:
    st = _states.get(tenant_id)
    if st is None:
        st = {
            "running": False,
            "cycles": 0,
            "last_cycle_at": None,
            "last_error": None,
            "tenant_id": tenant_id,
            "cfg": None,
        }
        _states[tenant_id] = st
    return st


def _profile_state(profile_id: str) -> _ProfileFarmState:
    if profile_id not in _profile_states:
        _profile_states[profile_id] = _ProfileFarmState(profile_id=profile_id)
    return _profile_states[profile_id]


# ── Playwright helpers ─────────────────────────────────────────────────────────

async def _pause(lo: float = 1.0, hi: float = 3.5) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def _bezier_move(page: Any, x0: float, y0: float, x1: float, y1: float, steps: int = 15) -> None:
    try:
        cx = random.uniform(min(x0, x1), max(x0, x1))
        cy = random.uniform(min(y0, y1) - 50, max(y0, y1) + 50)
        for i in range(steps + 1):
            t = i / steps
            bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
            by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
            await page.mouse.move(bx, by)
            await asyncio.sleep(math.sin(t * math.pi) * 0.010 + 0.003)
    except Exception:
        try:
            await page.mouse.move(x1, y1)
        except Exception:
            pass


async def _random_hover(page: Any) -> None:
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        x0, y0 = random.uniform(100, vp["width"] - 100), random.uniform(100, vp["height"] - 100)
        x1, y1 = random.uniform(100, vp["width"] - 100), random.uniform(100, vp["height"] - 100)
        await _bezier_move(page, x0, y0, x1, y1)
    except Exception:
        pass


async def _scroll_page(page: Any, steps: int = 3) -> None:
    try:
        for _ in range(steps):
            delta = random.randint(200, 450)
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(random.uniform(0.4, 1.2))
        await _random_hover(page)
    except Exception:
        pass


async def _accept_cookies_dialog(page: Any) -> None:
    """Кликает Accept/I agree если появился баннер cookies."""
    _selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        'button:has-text("I agree")',
        'button:has-text("Agree")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        '[aria-label*="Accept" i]',
        '#accept-button',
        '.fc-cta-consent',
    ]
    for sel in _selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await _pause(0.5, 1.5)
                return
        except Exception:
            continue


# ── Основная функция web-browsing ──────────────────────────────────────────────

async def _browse_web_for_cookies(
    page: Any,
    cancel_event: asyncio.Event | None = None,
    log: list[str] | None = None,
) -> dict[str, Any]:
    """
    Посещает 5–9 случайных сайтов (новости + lifestyle) и делает 2–3 Google-поиска.
    Возвращает {"sites_visited": int, "searches_done": int}.
    """
    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    sites_visited = 0
    searches_done = 0

    # Берём случайную подборку сайтов: 3–5 новостных + 2–4 lifestyle
    n_news = random.randint(3, 5)
    n_life = random.randint(2, 4)
    chosen_news = random.sample(_NEWS_SITES, min(n_news, len(_NEWS_SITES)))
    chosen_life = random.sample(_LIFESTYLE_SITES, min(n_life, len(_LIFESTYLE_SITES)))
    all_sites = chosen_news + chosen_life
    random.shuffle(all_sites)

    for url, name in all_sites:
        if _cancelled():
            break
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await _pause(1.5, 3.5)
            await _accept_cookies_dialog(page)
            await _scroll_page(page, steps=random.randint(2, 5))
            await _random_hover(page)
            sites_visited += 1
            if log is not None:
                log.append(f"web:visited:{name}")
            logger.debug("cookie_farmer: visited %s", name)
        except Exception as exc:
            logger.debug("cookie_farmer: skip %s: %s", name, exc)
        await _pause(0.8, 2.0)

    # Google-поиски
    n_searches = random.randint(2, 3)
    queries = random.sample(_GOOGLE_QUERIES, min(n_searches, len(_GOOGLE_QUERIES)))
    for q in queries:
        if _cancelled():
            break
        try:
            encoded = q.replace(" ", "+")
            await page.goto(
                f"https://www.google.com/search?q={encoded}&hl=en",
                wait_until="domcontentloaded",
                timeout=25_000,
            )
            await _pause(2.0, 4.5)
            await _accept_cookies_dialog(page)
            await _scroll_page(page, steps=random.randint(2, 4))
            await _random_hover(page)
            searches_done += 1
            if log is not None:
                log.append(f"web:search:{q[:30]}")
            logger.debug("cookie_farmer: google search '%s'", q)
        except Exception as exc:
            logger.debug("cookie_farmer: google search failed '%s': %s", q, exc)
        await _pause(1.0, 2.5)

    return {"sites_visited": sites_visited, "searches_done": searches_done}


# ── Сохранение бэкапа через AdsPower API ──────────────────────────────────────

async def _export_cookies(
    profile_id: str,
    tenant_id: str,
    adspower_api_url: str,
) -> dict[str, Any]:
    """Запрашивает cookies у AdsPower и сохраняет JSON-бэкап."""
    import httpx

    backup_dir = _COOKIE_BACKUPS_DIR / normalize_tenant_id(tenant_id)
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{profile_id}_cookie_{ts}.json"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{adspower_api_url}/api/v1/browser/cookies",
                params={"user_id": profile_id},
            )
            data = resp.json()
        backup_file.write_text(
            json.dumps(
                {"profile_id": profile_id, "cookies": data, "backed_up_at": ts},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        cookie_count = len(data.get("data", data) if isinstance(data, dict) else data)
        return {"status": "ok", "filename": backup_file.name, "cookie_count": cookie_count}
    except Exception as exc:
        logger.warning("cookie_farmer: export_cookies %s: %s", profile_id, exc)
        backup_file.write_text(
            json.dumps(
                {"profile_id": profile_id, "cookies": [], "backed_up_at": ts, "error": str(exc)},
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"status": "partial", "filename": backup_file.name, "message": str(exc)}


# ── Импорт cookies из последнего бэкапа ───────────────────────────────────────

async def _import_cookies_from_backup(
    profile_id: str,
    tenant_id: str,
    adspower_api_url: str,
) -> dict[str, Any]:
    """
    Находит последний JSON-бэкап для профиля и загружает cookies обратно
    через AdsPower /api/v1/browser/cookies/import.
    Вызывается для новых/холодных профилей перед стартом сессии.
    """
    import httpx

    backup_dir = _COOKIE_BACKUPS_DIR / normalize_tenant_id(tenant_id)
    if not backup_dir.exists():
        return {"status": "skipped", "reason": "no_backup_dir"}

    # Найти последний бэкап этого профиля
    backups = sorted(
        backup_dir.glob(f"{profile_id}_cookie_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not backups:
        return {"status": "skipped", "reason": "no_backup_found"}

    latest = backups[0]
    try:
        raw = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "error", "reason": f"read_error: {exc}"}

    cookies = raw.get("cookies", {})
    # AdsPower cookie export wraps data in {"data": [...]}
    if isinstance(cookies, dict):
        cookie_list = cookies.get("data") or []
    elif isinstance(cookies, list):
        cookie_list = cookies
    else:
        cookie_list = []

    if not cookie_list:
        return {"status": "skipped", "reason": "empty_backup"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{adspower_api_url}/api/v1/browser/cookies/import",
                json={"user_id": profile_id, "cookies": cookie_list},
            )
            data = resp.json()
        if data.get("code") == 0:
            return {"status": "ok", "imported": len(cookie_list), "from": latest.name}
        return {"status": "partial", "message": data.get("msg", "unknown"), "from": latest.name}
    except Exception as exc:
        logger.warning("cookie_farmer: import_cookies %s: %s", profile_id, exc)
        return {"status": "error", "reason": str(exc)}


# ── Фарминг одного профиля ────────────────────────────────────────────────────

async def farm_single_profile(
    profile_id: str,
    tenant_id: str = "default",
    warmup_intensity: str = "light",
    niche_keywords: list[str] | None = None,
    adspower_api_url: str = "http://127.0.0.1:50325",
    cancel_event: asyncio.Event | None = None,
) -> dict[str, Any]:
    """
    Полный цикл фарминга для одного профиля:
      1. Открыть браузер
      2. Web-browsing (новости + Google)
      3. YouTube-прогрев (light)
      4. Экспорт cookies
      5. Закрыть браузер

    Возвращает dict с полем status ('ok'|'error'|'cancelled') и деталями.
    """
    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc).isoformat()
    log: list[str] = []
    result: dict[str, Any] = {
        "profile_id": profile_id,
        "started_at": started_at,
        "status": "error",
        "steps": {},
        "actions_log": log,
    }

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    # ── 1. Открыть профиль ────────────────────────────────────────────────────
    try:
        from .antidetect_registry import get_registry
    except ImportError:
        from core.antidetect_registry import get_registry

    registry = get_registry()

    # ── Proxy pre-flight check ────────────────────────────────────────────────
    try:
        proxy_res = await dbmod.get_profile_proxy(profile_id, tenant_id=tenant_id)
        proxy = proxy_res.get("proxy") or {}
        proxy_status = str(proxy.get("status") or "").lower()
        if proxy_status == "dead":
            result["status"] = "skipped"
            result["message"] = f"Прокси профиля мёртва (proxy_id={proxy.get('id')}), пропускаем"
            log.append(f"proxy_dead:{proxy.get('id')}")
            logger.info("cookie_farmer: skip %s — proxy dead", profile_id)
            return result
    except Exception as exc:
        logger.debug("cookie_farmer: proxy pre-flight check failed for %s: %s", profile_id, exc)

    log.append("open_profile")
    try:
        start_res = await registry.start_profile(profile_id, tenant_id=tenant_id)
    except Exception as exc:
        result["message"] = f"Не удалось открыть профиль: {exc}"
        return result

    if start_res.get("status") != "ok":
        result["message"] = start_res.get("message", "start_profile failed")
        return result

    ws_endpoint: str = start_res.get("ws_endpoint", "")
    if not ws_endpoint:
        await _try_stop_profile(registry, profile_id, tenant_id)
        result["message"] = "ws_endpoint отсутствует"
        return result

    log.append("profile_opened")

    # ── 2. Подключение Playwright ─────────────────────────────────────────────
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await _try_stop_profile(registry, profile_id, tenant_id)
        result["message"] = "Playwright не установлен"
        return result

    playwright_inst = None
    browser = None
    try:
        playwright_inst = await async_playwright().start()
        browser = await playwright_inst.chromium.connect_over_cdp(ws_endpoint)
    except Exception as exc:
        await _try_stop_profile(registry, profile_id, tenant_id)
        if playwright_inst:
            await playwright_inst.stop()
        result["message"] = f"CDP connect failed: {exc}"
        return result

    try:
        if not browser.contexts:
            result["message"] = "Нет браузерного контекста"
            return result

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(30_000)

        # ── Fingerprint spoof (инжектируется до первого goto) ─────────────────
        try:
            from .fingerprint_spoofer import apply_fingerprint_spoof
        except ImportError:
            from core.fingerprint_spoofer import apply_fingerprint_spoof
        fp_res = await apply_fingerprint_spoof(context=context)
        if fp_res.get("status") == "ok":
            log.append(f"fp_spoof:seed={fp_res['seed']}")
            logger.debug("cookie_farmer: fingerprint spoof applied seed=%s for %s", fp_res["seed"], profile_id)
        else:
            logger.debug("cookie_farmer: fp spoof failed for %s: %s", profile_id, fp_res.get("message"))

        # ── Playwright-stealth (если установлен) ──────────────────────────────
        try:
            from playwright_stealth import stealth_async  # type: ignore
            await stealth_async(page)
            log.append("stealth_applied")
            logger.debug("cookie_farmer: stealth applied for %s", profile_id)
        except ImportError:
            pass  # playwright-stealth не установлен — продолжаем без него
        except Exception as exc:
            logger.debug("cookie_farmer: stealth failed for %s: %s", profile_id, exc)

        # ── Восстановление cookies из бэкапа (для холодных профилей) ─────────
        ps = _profile_state(profile_id)
        if ps.last_farmed_at is None:
            log.append("restore_cookies_from_backup")
            imp_res = await _import_cookies_from_backup(profile_id, tenant_id, adspower_api_url)
            result["steps"]["cookie_import"] = imp_res
            log.append(f"cookie_import:{imp_res.get('status')}")
            logger.info("cookie_farmer: cookie restore %s: %s", profile_id, imp_res)

        if _cancelled():
            result["status"] = "cancelled"
            result["message"] = "Отменено"
            return result

        # ── 3. Web-browsing ───────────────────────────────────────────────────
        log.append("web_browse_start")
        try:
            wb_res = await asyncio.wait_for(
                _browse_web_for_cookies(page, cancel_event=cancel_event, log=log),
                timeout=180,
            )
        except asyncio.TimeoutError:
            wb_res = {"sites_visited": 0, "searches_done": 0, "error": "timeout"}
        except Exception as exc:
            wb_res = {"sites_visited": 0, "searches_done": 0, "error": str(exc)}
        result["steps"]["web_browse"] = wb_res
        log.append(f"web_browse_done:sites={wb_res.get('sites_visited', 0)},searches={wb_res.get('searches_done', 0)}")

        if _cancelled():
            result["status"] = "cancelled"
            result["message"] = "Отменено после web-browsing"
            return result

        # ── 4. YouTube warmup (быстрый, light) ───────────────────────────────
        log.append("youtube_warmup_start")
        try:
            from .warmup_automator import run_warmup_session
        except ImportError:
            from core.warmup_automator import run_warmup_session

        try:
            yt_res = await asyncio.wait_for(
                run_warmup_session(
                    ws_endpoint=ws_endpoint,
                    profile_id=profile_id,
                    intensity=warmup_intensity,
                    niche_keywords=niche_keywords,
                    tenant_id=tenant_id,
                    enable_prewarm=False,   # web-browsing уже сделали pre-warm
                    cancel_event=cancel_event,
                ),
                timeout=300,
            )
        except asyncio.TimeoutError:
            yt_res = {"status": "partial", "message": "warmup timeout"}
        except Exception as exc:
            yt_res = {"status": "error", "message": str(exc)}

        result["steps"]["youtube_warmup"] = {
            "status": yt_res.get("status"),
            "stats": yt_res.get("stats"),
        }
        log.append(f"youtube_warmup:{yt_res.get('status')}")

        if _cancelled():
            result["status"] = "cancelled"
            result["message"] = "Отменено после прогрева"
            return result

        # ── 5. Экспорт cookies ────────────────────────────────────────────────
        log.append("export_cookies")
        exp_res = await _export_cookies(profile_id, tenant_id, adspower_api_url)
        result["steps"]["cookie_export"] = exp_res
        log.append(f"cookies_exported:{exp_res.get('status')}")

        result["status"] = "ok"
        result["message"] = (
            f"Посещено сайтов: {wb_res.get('sites_visited', 0)}, "
            f"поисков: {wb_res.get('searches_done', 0)}, "
            f"cookies: {exp_res.get('cookie_count', '?')}"
        )

    except asyncio.CancelledError:
        result["status"] = "cancelled"
        result["message"] = "Отменено"
        raise
    except Exception as exc:
        logger.exception("farm_single_profile %s: %s", profile_id, exc)
        result["message"] = str(exc)
    finally:
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if playwright_inst:
                await playwright_inst.stop()
        except Exception:
            pass
        await _try_stop_profile(registry, profile_id, tenant_id)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()

    return result


async def _try_stop_profile(registry: Any, profile_id: str, tenant_id: str) -> None:
    try:
        await registry.stop_profile(profile_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.debug("cookie_farmer: stop_profile %s: %s", profile_id, exc)


# ── Шедулер ──────────────────────────────────────────────────────────────────

async def _run_cycle(cfg: CookieFarmerConfig) -> dict[str, Any]:
    """Один цикл: выбор профилей → параллельный фарминг."""
    profiles_res = await dbmod.list_adspower_profiles(tenant_id=cfg.tenant_id)
    if profiles_res.get("status") != "ok":
        return {"status": "error", "message": profiles_res.get("message", "list profiles failed")}

    profiles = profiles_res.get("profiles") or []
    active = [
        p for p in profiles
        if str(p.get("status", "")).lower() in {"ready", "active", "new"}
    ]
    if not active:
        return {"status": "ok", "message": "нет профилей для фарминга", "farmed": 0}

    # Сортируем: давно фармленные идут первыми
    def _sort_key(p: dict) -> float:
        pid = str(p.get("adspower_profile_id", ""))
        ps = _profile_state(pid)
        if ps.last_farmed_at is None:
            return 0.0
        return ps.last_farmed_at.timestamp()

    active.sort(key=_sort_key)

    # Фильтруем недавно фармленных
    min_interval = cfg.min_farm_interval_sec
    now_ts = datetime.now(timezone.utc).timestamp()
    eligible = [
        p for p in active
        if (lambda pid: _profile_state(pid).last_farmed_at is None
            or (now_ts - _profile_state(pid).last_farmed_at.timestamp()) >= min_interval)(
            str(p.get("adspower_profile_id", ""))
        )
    ]

    if not eligible:
        return {"status": "ok", "message": "все профили фармились недавно", "farmed": 0}

    batch = eligible[:max(1, cfg.batch_size)]
    sem = asyncio.Semaphore(max(1, cfg.concurrency))
    results: dict[str, dict] = {}
    niche_kws = [k.strip() for k in cfg.niche.split(",") if k.strip()] or None

    async def _farm_one(p: dict) -> None:
        pid = str(p.get("adspower_profile_id", "")).strip()
        if not pid:
            return
        async with sem:
            ps = _profile_state(pid)

            # ── Circuit breaker: проверка карантина ───────────────────────────
            if ps.quarantined:
                if ps.quarantined_at is not None:
                    elapsed = (datetime.now(timezone.utc) - ps.quarantined_at).total_seconds()
                    if elapsed >= _QUARANTINE_DURATION_SEC:
                        # Карантин истёк — даём ещё один шанс
                        ps.quarantined = False
                        ps.quarantined_at = None
                        ps.consecutive_failures = 0
                        logger.info("cookie_farmer: quarantine lifted for %s after %.0fs", pid, elapsed)
                    else:
                        remaining = _QUARANTINE_DURATION_SEC - elapsed
                        logger.debug(
                            "cookie_farmer: skip %s (quarantined, %.0fs remaining)", pid, remaining
                        )
                        results[pid] = {
                            "status": "skipped",
                            "message": f"quarantine ({remaining:.0f}s remaining)",
                        }
                        return

            try:
                res = await farm_single_profile(
                    profile_id=pid,
                    tenant_id=cfg.tenant_id,
                    warmup_intensity=cfg.warmup_intensity,
                    niche_keywords=niche_kws,
                    adspower_api_url=cfg.adspower_api_url,
                )
                ps.last_result = res
                if res.get("status") == "ok":
                    ps.last_farmed_at = datetime.now(timezone.utc)
                    ps.total_farmed += 1
                    ps.last_error = None
                    ps.consecutive_failures = 0  # сбросить счётчик при успехе
                else:
                    ps.last_error = res.get("message", "unknown error")
                    if res.get("status") not in ("cancelled", "skipped"):
                        ps.consecutive_failures += 1
                        if ps.consecutive_failures >= _QUARANTINE_THRESHOLD:
                            ps.quarantined = True
                            ps.quarantined_at = datetime.now(timezone.utc)
                            logger.warning(
                                "cookie_farmer: profile %s quarantined after %d failures",
                                pid, ps.consecutive_failures,
                            )
                results[pid] = res
            except asyncio.CancelledError:
                results[pid] = {"status": "cancelled"}
                raise
            except Exception as exc:
                logger.exception("cookie_farmer _farm_one %s: %s", pid, exc)
                ps.last_error = str(exc)
                ps.consecutive_failures += 1
                if ps.consecutive_failures >= _QUARANTINE_THRESHOLD:
                    ps.quarantined = True
                    ps.quarantined_at = datetime.now(timezone.utc)
                    logger.warning(
                        "cookie_farmer: profile %s quarantined after %d failures (exception)",
                        pid, ps.consecutive_failures,
                    )
                results[pid] = {"status": "error", "message": str(exc)}

    await asyncio.gather(*[_farm_one(p) for p in batch], return_exceptions=True)

    ok_count = sum(1 for r in results.values() if r.get("status") == "ok")
    return {
        "status": "ok",
        "farmed": ok_count,
        "total": len(batch),
        "profiles": list(results.keys()),
    }


async def _worker(cfg: CookieFarmerConfig) -> None:
    state = _global_state(cfg.tenant_id)
    state["running"] = True
    state["cfg"] = {
        "interval_sec": cfg.interval_sec,
        "batch_size": cfg.batch_size,
        "concurrency": cfg.concurrency,
        "warmup_intensity": cfg.warmup_intensity,
        "niche": cfg.niche,
    }
    try:
        while True:
            try:
                res = await _run_cycle(cfg)
                state["cycles"] = int(state.get("cycles") or 0) + 1
                state["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
                if res.get("status") == "ok":
                    state["last_error"] = None
                    logger.info(
                        "cookie_farmer cycle done: farmed=%d/%d",
                        res.get("farmed", 0), res.get("total", 0),
                    )
                else:
                    state["last_error"] = res.get("message", "cycle error")
                    logger.warning("cookie_farmer cycle error: %s", state["last_error"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("cookie_farmer cycle exception: %s", exc)
                state["last_error"] = str(exc)

            await asyncio.sleep(max(30, int(cfg.interval_sec)))
    except asyncio.CancelledError:
        logger.info("cookie_farmer stopped (tenant=%s)", cfg.tenant_id)
        raise
    except Exception as exc:
        logger.exception("cookie_farmer worker crashed: %s", exc)
        state["last_error"] = str(exc)
    finally:
        state["running"] = False


# ── Ручной запуск одного профиля ─────────────────────────────────────────────

async def farm_now(
    profile_id: str,
    tenant_id: str = "default",
    warmup_intensity: str = "light",
    niche: str = "general",
    adspower_api_url: str = "http://127.0.0.1:50325",
) -> dict[str, Any]:
    """
    Немедленный запуск фарминга для конкретного профиля.
    Если профиль уже фармится — возвращает ошибку.
    """
    task = _manual_tasks.get(profile_id)
    if task is not None and not task.done():
        return {"status": "error", "message": f"Профиль {profile_id} уже в процессе фарминга"}

    cancel_ev = asyncio.Event()
    niche_kws = [k.strip() for k in niche.split(",") if k.strip()] or None

    async def _run() -> None:
        ps = _profile_state(profile_id)
        try:
            res = await farm_single_profile(
                profile_id=profile_id,
                tenant_id=tenant_id,
                warmup_intensity=warmup_intensity,
                niche_keywords=niche_kws,
                adspower_api_url=adspower_api_url,
                cancel_event=cancel_ev,
            )
            ps.last_result = res
            if res.get("status") == "ok":
                ps.last_farmed_at = datetime.now(timezone.utc)
                ps.total_farmed += 1
                ps.last_error = None
            else:
                ps.last_error = res.get("message")
        except Exception as exc:
            ps.last_error = str(exc)
        finally:
            _manual_tasks.pop(profile_id, None)

    task = asyncio.create_task(_run(), name=f"cookie_farmer_manual_{profile_id}")
    _manual_tasks[profile_id] = task
    return {"status": "ok", "message": f"Запущен фарминг для {profile_id}"}


def cancel_farm_now(profile_id: str) -> dict[str, Any]:
    task = _manual_tasks.get(profile_id)
    if task is None or task.done():
        return {"status": "ok", "message": "Задача не найдена или уже завершена"}
    task.cancel()
    return {"status": "ok", "message": f"Отмена отправлена для {profile_id}"}


# ── Публичный API ─────────────────────────────────────────────────────────────

def get_status(tenant_id: str = "default") -> dict[str, Any]:
    state = _global_state(tenant_id)
    task = _tasks.get(tenant_id)
    alive = task is not None and not task.done()
    return {**state, "running": alive}


def get_profiles_status(tenant_id: str = "default") -> list[dict[str, Any]]:
    """Возвращает per-profile статус фарминга (только профили с историей)."""
    out = []
    now_ts = datetime.now(timezone.utc)
    for pid, ps in _profile_states.items():
        manual_task = _manual_tasks.get(pid)
        is_farming = manual_task is not None and not manual_task.done()

        quarantine_remaining: int | None = None
        if ps.quarantined and ps.quarantined_at:
            elapsed = (now_ts - ps.quarantined_at).total_seconds()
            quarantine_remaining = max(0, int(_QUARANTINE_DURATION_SEC - elapsed))

        if is_farming:
            status = "farming"
        elif ps.quarantined:
            status = "quarantined"
        elif ps.last_error:
            status = "error"
        elif ps.last_farmed_at:
            status = "ok"
        else:
            status = "pending"

        out.append({
            "profile_id": pid,
            "last_farmed_at": ps.last_farmed_at.isoformat() if ps.last_farmed_at else None,
            "total_farmed": ps.total_farmed,
            "last_error": ps.last_error,
            "status": status,
            "consecutive_failures": ps.consecutive_failures,
            "quarantined": ps.quarantined,
            "quarantine_remaining_sec": quarantine_remaining,
        })
    return out


async def start(cfg: CookieFarmerConfig) -> dict[str, Any]:
    task = _tasks.get(cfg.tenant_id)
    if task is not None and not task.done():
        return {"status": "ok", "message": "already running", "state": get_status(cfg.tenant_id)}
    _tasks[cfg.tenant_id] = asyncio.create_task(
        _worker(cfg), name=f"cookie_farmer_{cfg.tenant_id}"
    )
    return {"status": "ok", "message": "started", "state": get_status(cfg.tenant_id)}


async def stop(tenant_id: str = "default") -> dict[str, Any]:
    state = _global_state(tenant_id)
    task = _tasks.get(tenant_id)
    if task is None or task.done():
        state["running"] = False
        return {"status": "ok", "message": "already stopped", "state": get_status(tenant_id)}
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    _tasks.pop(tenant_id, None)
    state["running"] = False
    return {"status": "ok", "message": "stopped", "state": get_status(tenant_id)}
