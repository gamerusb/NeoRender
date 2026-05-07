"""
channel_analyzer.py — Риск-анализ YouTube-каналов через Data API v3.

Детектируемые паттерны «расходных» каналов (2026):
    • Velocity  — > 5 видео за 24 ч (спам-заливка)
    • Age       — канал < 7 дней (одноразовый)
    • Bio       — эмодзи 🔗👇💰 или «t.me/» в описании канала
    • Ratio     — views >> subscribers (вирус без органики)
    • Density   — много видео на молодом канале (>5 в день)
    • Name      — генерик/рандомное имя (user123456, ChannelAbc)

Зависимости: только aiohttp (уже установлен) + env YOUTUBE_API_KEY.

Использование:
    from core.channel_analyzer import analyze_channel_risk

    result = await analyze_channel_risk("UCxxxxxxxxxxxxxxxxxxxxxx")
    if result.is_burner:
        print(result.risk_flags)
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_YT_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
_YT_SEARCH_URL   = "https://www.googleapis.com/youtube/v3/search"

# Эмодзи, типичные для спам-биографий
_BURNER_EMOJI: frozenset[str] = frozenset({
    "🔗", "👇", "💰", "💸", "✅", "🎯", "🤑", "💎", "🏆",
    "⬇️", "👆", "🔥", "💥", "🤩", "🎰", "🎲", "⚡", "🚀",
    "💵", "💴", "💶", "💷", "🤫", "🔑",
})

# Telegram-маркеры в биографии
_TG_BIO_PATTERNS: tuple[str, ...] = (
    "t.me/", "telegram.me/", "telegram:", "@",
    "телеграм", "telegram", "тг канал", "tg channel",
)

# Казино-слова в биографии
_CASINO_BIO_KW: tuple[str, ...] = (
    "1win", "mostbet", "pin-up", "pinup", "casino", "казино",
    "slots", "слоты", "betwinner", "stake", "bc.game",
    "промокод", "promo code", "bonus", "free spins",
)

# Паттерн «генерик/рандомного» названия канала
_GENERIC_NAME_RE = re.compile(
    r"^(channel|shorts|official|gaming|clips|videos|best|top|"
    r"[a-z]{2,6}\d{4,}|user\d+|yt\d+|[A-Z][a-z]{2,8}\d{3,}|"
    r"[A-Z]{2,6}\d{2,})$",
    re.IGNORECASE,
)


# ── Dataclass результата ──────────────────────────────────────────────────────

@dataclasses.dataclass
class ChannelRiskResult:
    channel_id: str = ""
    channel_name: str = ""
    description: str = ""
    subscriber_count: int = 0
    video_count: int = 0
    total_views: int = 0
    created_at: str = ""            # ISO 8601
    channel_age_days: int = -1      # -1 = не удалось определить
    uploads_last_24h: int = 0
    uploads_last_7d: int = 0
    risk_score: int = 0             # 0–100
    risk_flags: list[str] = dataclasses.field(default_factory=list)
    is_burner: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def risk_summary(self) -> str:
        """Короткое человекочитаемое описание для логов/UI."""
        tier = "HIGH" if self.risk_score >= 65 else "MED" if self.risk_score >= 35 else "LOW"
        age = f"{self.channel_age_days}d" if self.channel_age_days >= 0 else "?"
        return (
            f"[{tier} {self.risk_score}] {self.channel_name!r} "
            f"age={age} u24h={self.uploads_last_24h} subs={self.subscriber_count}"
        )


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _count_burner_emoji(text: str) -> int:
    return sum(1 for ch in text if ch in _BURNER_EMOJI)


def _has_tg_in_bio(text: str) -> bool:
    text_lower = text.lower()
    return any(pat in text_lower for pat in _TG_BIO_PATTERNS)


def _has_casino_kw_in_bio(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in _CASINO_BIO_KW)


def _is_generic_name(name: str) -> bool:
    clean = re.sub(r"\s+", "", (name or "")).strip()
    return bool(_GENERIC_NAME_RE.match(clean))


# ── Основная функция ──────────────────────────────────────────────────────────

async def analyze_channel_risk(
    channel_id: str,
    *,
    api_key: str | None = None,
) -> ChannelRiskResult:
    """
    Анализирует канал channel_id через YouTube Data API v3.
    api_key берётся из параметра или env YOUTUBE_API_KEY.

    Делает 3 HTTP-запроса:
        1. channels.list  — snippet + statistics + contentDetails
        2. search.list    — количество загрузок за 24 ч
        3. search.list    — количество загрузок за 7 дней
    Запросы 2 и 3 выполняются параллельно.
    """
    result = ChannelRiskResult(channel_id=channel_id)

    key = (api_key or os.environ.get("YOUTUBE_API_KEY") or "").strip()
    if not key:
        result.error = "YOUTUBE_API_KEY не задан — channel analysis недоступен"
        return result

    if not channel_id or not channel_id.startswith("UC"):
        result.error = f"Невалидный channel_id: {channel_id!r}"
        return result

    session_timeout = aiohttp.ClientTimeout(total=20, connect=6)

    try:
        async with aiohttp.ClientSession(timeout=session_timeout) as session:

            # ── 1. Базовые данные канала ────────────────────────────────────
            ch_params: dict[str, str] = {
                "key":  key,
                "part": "snippet,statistics",
                "id":   channel_id,
            }
            async with session.get(_YT_CHANNELS_URL, params=ch_params) as resp:
                if resp.status == 403:
                    result.error = "YouTube API: quota exceeded или ключ недействителен"
                    return result
                if resp.status != 200:
                    result.error = f"YouTube API HTTP {resp.status}"
                    return result
                ch_data: dict[str, Any] = await resp.json()

            items = ch_data.get("items") or []
            if not items:
                result.error = "Канал не найден в YouTube API"
                return result

            item       = items[0]
            snippet    = item.get("snippet") or {}
            statistics = item.get("statistics") or {}

            result.channel_name    = str(snippet.get("title") or "")
            result.description     = str(snippet.get("description") or "")
            result.subscriber_count = int(statistics.get("subscriberCount") or 0)
            result.video_count      = int(statistics.get("videoCount") or 0)
            result.total_views      = int(statistics.get("viewCount") or 0)
            result.created_at       = str(snippet.get("publishedAt") or "")

            # Возраст канала
            if result.created_at:
                try:
                    created = datetime.fromisoformat(
                        result.created_at.replace("Z", "+00:00")
                    )
                    result.channel_age_days = max(0, (datetime.now(timezone.utc) - created).days)
                except (ValueError, TypeError):
                    pass

            # ── 2 + 3. Количество загрузок (параллельно) ────────────────────
            now = datetime.now(timezone.utc)

            async def _count_uploads(published_after: str) -> int:
                params: dict[str, str] = {
                    "key":            key,
                    "part":           "id",
                    "channelId":      channel_id,
                    "type":           "video",
                    "publishedAfter": published_after,
                    "maxResults":     "50",
                    "order":          "date",
                }
                try:
                    step_timeout = aiohttp.ClientTimeout(total=10, connect=5)
                    async with session.get(
                        _YT_SEARCH_URL, params=params, timeout=step_timeout
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            page_info = data.get("pageInfo") or {}
                            # totalResults может быть завышен YouTube; берём max(реальные, total)
                            real = len(data.get("items") or [])
                            reported = int(page_info.get("totalResults") or real)
                            return max(real, min(reported, 500))
                except Exception as exc:
                    logger.debug("_count_uploads %s: %s", channel_id, exc)
                return 0

            after_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
            after_7d  = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

            result.uploads_last_24h, result.uploads_last_7d = await asyncio.gather(
                _count_uploads(after_24h),
                _count_uploads(after_7d),
            )

    except aiohttp.ClientError as exc:
        result.error = f"Сетевая ошибка: {type(exc).__name__}: {str(exc)[:120]}"
        return result
    except asyncio.TimeoutError:
        result.error = "Таймаут при запросе YouTube API"
        return result
    except Exception as exc:
        result.error = str(exc)[:200]
        logger.exception("analyze_channel_risk %s: %s", channel_id, exc)
        return result

    # ── Скоринг ───────────────────────────────────────────────────────────────
    score = 0
    flags: list[str] = []

    def _add(flag: str, pts: int) -> None:
        flags.append(flag)
        nonlocal score
        score += pts

    # — Velocity (заливка видео) ——————————————————————————————————————————————
    if result.uploads_last_24h >= 15:
        _add(f"velocity:extreme:{result.uploads_last_24h}_per_24h", 40)
    elif result.uploads_last_24h >= 7:
        _add(f"velocity:high:{result.uploads_last_24h}_per_24h", 28)
    elif result.uploads_last_24h >= 4:
        _add(f"velocity:moderate:{result.uploads_last_24h}_per_24h", 15)
    elif result.uploads_last_24h >= 2:
        _add(f"velocity:low:{result.uploads_last_24h}_per_24h", 7)

    # — Возраст канала —————————————————————————————————————————————————————————
    if 0 <= result.channel_age_days < 3:
        _add(f"age:brand_new:{result.channel_age_days}d", 35)
    elif 0 <= result.channel_age_days < 7:
        _add(f"age:fresh:{result.channel_age_days}d", 25)
    elif 0 <= result.channel_age_days < 30:
        _add(f"age:new:{result.channel_age_days}d", 12)

    # — Биография: триггерные эмодзи ——————————————————————————————————————————
    emoji_n = _count_burner_emoji(result.description)
    if emoji_n >= 5:
        _add(f"bio:emoji_heavy:{emoji_n}", 22)
    elif emoji_n >= 2:
        _add(f"bio:emoji:{emoji_n}", 10)

    # — Биография: Telegram ————————————————————————————————————————————————————
    if _has_tg_in_bio(result.description):
        # Telegram в биографии + молодой канал = почти наверняка бёрнер
        bonus = 10 if result.channel_age_days < 30 else 0
        _add("bio:telegram_link", 28 + bonus)

    # — Биография: казино-слова ————————————————————————————————————————————————
    if _has_casino_kw_in_bio(result.description):
        _add("bio:casino_keyword", 25)

    # — views/subscribers аномалия (вирус без органики) ———————————————————————
    if result.subscriber_count > 0:
        vps = result.total_views / result.subscriber_count
        if vps > 50_000:
            _add(f"ratio:extreme:{int(vps)}x", 22)
        elif vps > 10_000:
            _add(f"ratio:very_high:{int(vps)}x", 15)
        elif vps > 3_000:
            _add(f"ratio:high:{int(vps)}x", 8)
    elif result.total_views > 100_000:
        # Скрытые подписчики + много просмотров
        _add("ratio:hidden_subs_high_views", 18)

    # — Плотность контента (много видео на молодом канале) ————————————————————
    if result.channel_age_days and result.channel_age_days > 0:
        vpd = result.video_count / result.channel_age_days
        if vpd > 15:
            _add(f"density:extreme:{int(vpd)}_per_day", 22)
        elif vpd > 7:
            _add(f"density:high:{int(vpd)}_per_day", 12)
        elif vpd > 3:
            _add(f"density:moderate:{int(vpd)}_per_day", 5)

    # — Мало подписчиков + активная заливка ———————————————————————————————————
    if result.subscriber_count < 500 and result.uploads_last_7d >= 5:
        _add("pattern:micro_active", 15)
    if result.subscriber_count < 100 and result.video_count >= 10:
        _add("pattern:new_heavy_upload", 12)

    # — Генерик/рандомное имя ——————————————————————————————————————————————————
    if _is_generic_name(result.channel_name):
        _add("name:generic", 8)

    # — Нет описания вообще ————————————————————————————————————————————————————
    if not result.description.strip():
        _add("bio:empty", 5)

    result.risk_score = min(100, score)
    result.risk_flags = flags
    result.is_burner  = result.risk_score >= 55

    logger.debug("channel_risk: %s", result.risk_summary())
    return result


# ── Хелпер: извлечь channel_id из YouTube URL ────────────────────────────────

def extract_channel_id(channel_url: str) -> str | None:
    """
    Извлекает UCxxxxxxxxx из URL вида:
        https://www.youtube.com/channel/UCxxxxx
        https://www.youtube.com/@handle  (требует отдельного API-запроса)
    Возвращает None если не удалось.
    """
    if not channel_url:
        return None
    m = re.search(r"/channel/(UC[A-Za-z0-9_\-]{20,})", channel_url)
    if m:
        return m.group(1)
    return None
