"""
funnel_resolver.py — Асинхронный резолвер цепочек редиректов.

Логика:
    1. HEAD-запросы по цепочке Location: заголовков (не скачивает HTML)
    2. До 10 хопов, 8 сек на шаг, 25 сек суммарно
    3. Финальный URL классифицируется: casino / telegram / aggregator / shortener
    4. arb_score_boost = 100 при прямом казино-домене, 85 при t.me/*

Зависимости: только aiohttp (уже установлен).

Использование:
    from core.funnel_resolver import resolve_funnel, resolve_urls_in_text

    result = await resolve_funnel("https://bit.ly/3xAbcde")
    print(result.final_url, result.funnel_type, result.arb_score_boost)

    results = await resolve_urls_in_text("ссылка в шапке bit.ly/abc t.me/channel")
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

# ── Домены-казино (2026) ──────────────────────────────────────────────────────

_CASINO_EXACT: frozenset[str] = frozenset({
    "1win.com", "1win.xyz", "1win.pro", "1win.bet",
    "mostbet.com", "mostbet.uz", "mostbet.kg", "mostbet.in", "mostbet.az",
    "pin-up.casino", "pin-up.bet", "pinup.bet", "pinupcasino.com",
    "betwinner.com", "betwinner.org",
    "bc.game",
    "stake.com", "stake.us",
    "1xbet.com", "1xbet.ug", "1xbet.ng",
    "melbet.com", "melbet.in", "melbet.org",
    "betandyou.com",
    "parimatch.com", "parimatch.bet",
    "linebet.com",
    "vavada.com",
    "leon.bet", "leonbets.com",
    "joycasino.com", "cat.casino", "pokerdom.com",
    "vulkan-vegas.com", "vulkanbet.com",
    "winbet.az", "winbet.com",
    "casinox.com", "fresh.casino",
    "glory.casino", "jet.casino",
})

# Паттерны поддоменов/суффиксов (если домен содержит → казино)
_CASINO_KEYWORDS: tuple[str, ...] = (
    "1win.", "mostbet.", "pinup.", "pin-up.", "betwinner.",
    "1xbet.", "melbet.", "betandyou.", "parimatch.", "linebet.",
    "vavada.", "vulkan", ".casino", "casinobet", "slotbet",
)

_TELEGRAM_MARKERS: tuple[str, ...] = ("t.me/", "telegram.me/", "telegram.dog/")

# Агрегаторы ссылок (прокладки — видно, что скрывают реальный URL)
_AGGREGATOR_EXACT: frozenset[str] = frozenset({
    "linktr.ee", "taplink.cc", "lit.link", "bio.link",
    "beacons.ai", "direct.me", "milkshake.app",
    "linkin.bio", "solo.to", "campsite.bio",
    "msha.ke", "carrd.co", "about.me",
    "bento.me", "flow.page",
})

_SHORTENER_EXACT: frozenset[str] = frozenset({
    "bit.ly", "tinyurl.com", "short.io", "t.ly", "rb.gy",
    "ow.ly", "is.gd", "buff.ly", "adf.ly", "cutt.ly",
    "smarturl.it", "lnk.to", "shorte.st", "bc.vc",
    "tiny.cc", "t.co", "snip.ly", "clck.ru", "vk.cc",
})

# Регулярка для поиска URL в тексте
_URL_RE = re.compile(r"https?://[^\s\"'<>\]\[)]+")


# ── Dataclass результата ──────────────────────────────────────────────────────

@dataclasses.dataclass
class FunnelResult:
    source_url: str = ""
    redirect_chain: list[str] = dataclasses.field(default_factory=list)
    final_url: str = ""
    final_domain: str = ""
    funnel_type: str = "unknown"    # casino | telegram | aggregator | shortener | direct | unknown
    is_casino: bool = False
    is_telegram: bool = False
    hops: int = 0
    arb_score_boost: int = 0
    flags: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    """Извлекает нормализованный домен без www."""
    try:
        host = urlparse(url).netloc.lower()
        return host.lstrip("www.")
    except Exception:
        return ""


def _classify(url: str, domain: str) -> tuple[str, bool, bool, int]:
    """
    Возвращает (funnel_type, is_casino, is_telegram, score_boost).
    Вызывается для финального URL после раскрутки цепочки.
    """
    url_lower = url.lower()

    # Telegram — первый приоритет (сильнейший сигнал в 2026)
    for marker in _TELEGRAM_MARKERS:
        if marker in url_lower:
            return "telegram", False, True, 85

    # Точное совпадение с казино-доменом
    if domain in _CASINO_EXACT:
        return "casino", True, False, 100

    # Паттерн в домене (поддомены казино-операторов)
    for kw in _CASINO_KEYWORDS:
        if kw in domain:
            return "casino", True, False, 90

    # Агрегатор (taplink, linktr.ee — явная прокладка, не раскрылась полностью)
    if domain in _AGGREGATOR_EXACT:
        return "aggregator", False, False, 50

    # Нераскрывшийся сокращатель
    if domain in _SHORTENER_EXACT:
        return "shortener", False, False, 25

    return "unknown", False, False, 10


def _is_worth_resolving(url: str) -> bool:
    """
    Быстрая проверка перед резолвом: стоит ли тратить запрос.
    Резолвим только сокращатели, агрегаторы и явные Telegram-ссылки.
    """
    url_lower = url.lower()
    domain = _extract_domain(url)

    if any(m in url_lower for m in _TELEGRAM_MARKERS):
        return True
    if domain in _SHORTENER_EXACT:
        return True
    if domain in _AGGREGATOR_EXACT:
        return True
    return False


# ── HTTP клиент ───────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; SM-S928N Build/UP1A.231005.007) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.6367.82 Mobile Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_MAX_HOPS = 10
_STEP_TIMEOUT_SEC = 8.0
_TOTAL_TIMEOUT_SEC = 25.0


# ── Основная функция ──────────────────────────────────────────────────────────

async def resolve_funnel(url: str) -> FunnelResult:
    """
    Проходит по цепочке редиректов от url до финального URL.
    Использует HEAD-запросы — не скачивает тело страниц.

    Возвращает FunnelResult с полной цепочкой, типом воронки и score_boost.
    """
    result = FunnelResult(source_url=url)

    if not url or not url.startswith(("http://", "https://")):
        result.error = "Невалидный URL"
        return result

    chain: list[str] = [url]
    current = url

    connector = aiohttp.TCPConnector(ssl=False, limit=5, ttl_dns_cache=60)
    total_timeout = aiohttp.ClientTimeout(total=_TOTAL_TIMEOUT_SEC, connect=5.0)

    try:
        async with aiohttp.ClientSession(
            headers=_HEADERS,
            timeout=total_timeout,
            connector=connector,
        ) as session:
            for hop in range(_MAX_HOPS):
                try:
                    step_timeout = aiohttp.ClientTimeout(total=_STEP_TIMEOUT_SEC, connect=5.0)
                    async with session.head(
                        current,
                        allow_redirects=False,
                        timeout=step_timeout,
                    ) as resp:
                        location = (
                            resp.headers.get("Location")
                            or resp.headers.get("location")
                            or ""
                        ).strip()

                        # Нет редиректа → конец цепочки
                        if resp.status not in (301, 302, 303, 307, 308) or not location:
                            # Некоторые сайты возвращают 200 сразу без редиректа
                            break

                        # Нормализуем относительный URL
                        if location.startswith("/"):
                            parsed = urlparse(current)
                            location = f"{parsed.scheme}://{parsed.netloc}{location}"
                        elif not location.startswith(("http://", "https://")):
                            result.flags.append(f"redirect:malformed_location_hop{hop}")
                            break

                        # Защита от петель
                        if location in chain:
                            result.flags.append("redirect:loop")
                            break

                        chain.append(location)
                        current = location

                        # Если уже на Telegram или казино — дальше не идём
                        domain_now = _extract_domain(current)
                        ftype, *_ = _classify(current, domain_now)
                        if ftype in ("casino", "telegram"):
                            break

                except asyncio.TimeoutError:
                    result.flags.append(f"redirect:timeout_hop{hop}")
                    break
                except aiohttp.ClientConnectorError as exc:
                    result.flags.append(f"redirect:connect_error:{type(exc).__name__}")
                    break
                except aiohttp.ClientError as exc:
                    result.flags.append(f"redirect:client_error:{type(exc).__name__}")
                    break

    except asyncio.TimeoutError:
        result.flags.append("total_timeout")
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {str(exc)[:150]}"
        logger.debug("resolve_funnel %s: %s", url[:80], exc)

    # Заполняем итог
    result.redirect_chain = chain
    result.final_url       = chain[-1]
    result.final_domain    = _extract_domain(result.final_url)
    result.hops            = len(chain) - 1

    ftype, is_casino, is_tg, boost = _classify(result.final_url, result.final_domain)
    result.funnel_type       = ftype
    result.is_casino         = is_casino
    result.is_telegram       = is_tg
    result.arb_score_boost   = boost

    # Длинная цепочка сама по себе подозрительна
    if result.hops >= 4:
        result.flags.append(f"deep_chain:{result.hops}_hops")
        result.arb_score_boost = min(100, result.arb_score_boost + 10)

    logger.debug(
        "funnel %s → [%d hops] → %s (%s +%d)",
        url[:55], result.hops, result.final_url[:55], ftype, boost,
    )
    return result


async def resolve_urls_in_text(text: str, max_urls: int = 4) -> list[FunnelResult]:
    """
    Находит все URL в тексте (описание, теги) и резолвит параллельно.
    Резолвит только сокращатели и агрегаторы — пропускает прямые YouTube/Google.
    Используется внутри enrich_video_risk().
    """
    if not text:
        return []

    found_urls = _URL_RE.findall(text)
    # Оставляем только те, что стоит резолвить
    candidates = [u for u in found_urls if _is_worth_resolving(u)][:max_urls]

    if not candidates:
        return []

    results = await asyncio.gather(
        *[resolve_funnel(u) for u in candidates],
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, FunnelResult) and not r.error]


# ── Быстрая синхронная pre-check (без HTTP) ───────────────────────────────────

def has_resolvable_urls(text: str) -> bool:
    """
    Быстрая проверка без HTTP: есть ли в тексте сокращатели/агрегаторы/телеграм.
    Используется для флага needs_funnel_resolve в enrich_video_risk().
    """
    if not text:
        return False
    text_lower = text.lower()

    for domain in _SHORTENER_EXACT:
        if domain in text_lower:
            return True
    for domain in _AGGREGATOR_EXACT:
        if domain in text_lower:
            return True
    for marker in _TELEGRAM_MARKERS:
        if marker in text_lower:
            return True
    return False
