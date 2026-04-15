"""
Публичные метрики роликов: YouTube (HTML), TikTok и Instagram Reels (yt-dlp JSON).

Официальные API TikTok/Instagram здесь не используются — только публичные страницы /
метаданные, которые отдаёт yt-dlp. Приватный контент и жёсткие блокировки могут
требовать cookies (см. документацию yt-dlp).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

_TIMEOUT = aiohttp.ClientTimeout(total=25, connect=10)
_MAX_RETRIES = 3


def _pick_ua() -> str:
    import random

    return random.choice(_USER_AGENTS)


def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}


def _parse_views_from_soup(soup: BeautifulSoup) -> int | None:
    """interactionCount в meta itemprop (User Interaction Count)."""
    try:
        tag = soup.find("meta", attrs={"itemprop": "interactionCount"})
        if tag and tag.get("content"):
            raw = str(tag["content"]).strip()
            if raw.isdigit():
                return int(raw)
        # Иногда в link rel="shortlink" или других местах — запасной поиск по шаблону
        for meta in soup.find_all("meta"):
            if meta.get("itemprop") == "interactionCount" and meta.get("content"):
                v = str(meta["content"]).strip()
                if v.isdigit():
                    return int(v)
    except Exception:
        pass
    return None


def _parse_views_from_html_fallback(html: str) -> int | None:
    """
    Резервный парсер: JSON-LD / initial data часто содержит viewCount.
    """
    try:
        m = re.search(r'"viewCount"\s*:\s*"(\d+)"', html)
        if m:
            return int(m.group(1))
        m2 = re.search(r'"shortViewCount"\s*:\s*"(\d+)"', html)
        if m2:
            return int(m2.group(1))
    except Exception:
        return None
    return None


def _looks_banned(html: str, http_status: int) -> bool:
    if http_status == 404:
        return True
    lower = html.lower()
    markers = (
        "video unavailable",
        "this video is unavailable",
        "этот видеоролик недоступен",
        "rejected (copyright",
        "private video",
    )
    return any(m in lower for m in markers)


def _detect_platform(url: str) -> str:
    u = (url or "").strip().lower()
    if "tiktok.com" in u or "vm.tiktok.com" in u or "vt.tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "unknown"


def _coerce_count(val: Any) -> int:
    if val is None or isinstance(val, bool):
        return 0
    if isinstance(val, int):
        return max(0, val)
    try:
        s = str(val).replace(",", "").replace(" ", "").strip()
        if s.isdigit():
            return int(s)
    except Exception:
        pass
    return 0


async def _check_ytdlp_metadata(url: str, platform: str) -> dict[str, Any]:
    """Просмотры / лайки / комментарии с публичной страницы через yt-dlp."""
    from core.content_scraper import _yt_dlp_cmd, _ytdlp_available

    if not _ytdlp_available():
        return {
            "status": "error",
            "message": "Установите yt-dlp и добавьте в PATH — для TikTok и Instagram нужен yt-dlp.",
        }
    cmd0 = _yt_dlp_cmd()
    if not cmd0:
        return {"status": "error", "message": "yt-dlp недоступен."}
    cmd = [
        *cmd0,
        "-j",
        "--no-download",
        "--skip-download",
        "--no-warnings",
        "--quiet",
        "--socket-timeout",
        "25",
        url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=55)
    except asyncio.TimeoutError:
        return {"status": "error", "error_type": "timeout", "message": "Таймаут yt-dlp при чтении метаданных."}
    except Exception as exc:
        logger.warning("ytdlp metadata: %s", exc)
        return {"status": "error", "message": f"yt-dlp: {exc}"}

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[-400:]
        logger.warning("ytdlp exit %s for %s: %s", proc.returncode, url[:80], err)
        return {
            "status": "error",
            "message": "Не удалось прочитать ролик (удалён, приват или нужны cookies — см. yt-dlp).",
        }

    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return {"status": "error", "message": "yt-dlp не вернул метаданные."}

    data: dict[str, Any] | None = None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (obj.get("id") or obj.get("display_id")):
            data = obj
            break
    if not data:
        return {"status": "error", "message": "Не удалось разобрать ответ yt-dlp."}

    views = _coerce_count(data.get("view_count"))
    if views == 0:
        views = _coerce_count(data.get("play_count"))
    likes = _coerce_count(data.get("like_count"))
    comments = _coerce_count(data.get("comment_count"))
    title = str(data.get("title") or "")[:240]

    return {
        "status": "active",
        "views": int(views),
        "likes": int(likes),
        "platform": platform,
        "title": title,
        **({"comments": int(comments)} if comments else {}),
    }


async def _check_youtube_html(
    video_url: str,
    published_at: datetime | str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """YouTube: разбор публичной HTML-страницы."""
    headers = {
        "User-Agent": _pick_ua(),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    own_session = session is None
    local: aiohttp.ClientSession | None = None
    try:
        if own_session:
            local = aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers)
            session = local
        assert session is not None

        status = 0
        html = ""
        for attempt in range(_MAX_RETRIES):
            async with session.get(video_url, allow_redirects=True) as resp:
                status = resp.status
                html = await resp.text(errors="replace")
            if status not in (429, 500, 502, 503, 504):
                break
            if attempt < _MAX_RETRIES - 1:
                backoff = (2 ** attempt) + random.uniform(0.1, 0.6)
                logger.warning(
                    "check_video: retryable HTTP %s for %s (attempt %d/%d, sleep %.2fs)",
                    status,
                    video_url[:80],
                    attempt + 1,
                    _MAX_RETRIES,
                    backoff,
                )
                await asyncio.sleep(backoff)

        if status == 429:
            return {
                "status": "error",
                "error_type": "rate_limited",
                "http_status": 429,
                "message": "YouTube временно ограничил запросы (429).",
            }
        if status in (500, 502, 503, 504):
            return {
                "status": "error",
                "error_type": "youtube_unavailable",
                "http_status": status,
                "message": "YouTube временно недоступен. Повторите проверку позже.",
            }
        if status == 403:
            return {
                "status": "error",
                "error_type": "forbidden",
                "http_status": 403,
                "message": "Доступ к странице видео ограничен (403).",
            }

        if _looks_banned(html, status):
            return {"status": "banned", "platform": "youtube"}

        soup = BeautifulSoup(html, "html.parser")
        views = _parse_views_from_soup(soup)
        if views is None:
            views = _parse_views_from_html_fallback(html)

        if views is None:
            # Не смогли распарсить — не пугаем пользователя техникой
            logger.warning("check_video: не найдены просмотры для %s", video_url[:80])
            return {
                "status": "error",
                "message": "Не удалось прочитать статистику видео. Попробуйте позже.",
            }

        pub_dt: datetime | None = None
        if published_at is not None:
            try:
                if isinstance(published_at, datetime):
                    pub_dt = published_at
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                else:
                    raw = str(published_at).strip()
                    raw = raw.replace("Z", "+00:00")
                    pub_dt = datetime.fromisoformat(raw)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = None

        if views == 0 and pub_dt is not None:
            now = datetime.now(timezone.utc)
            if now - pub_dt >= timedelta(hours=24):
                return {"status": "shadowban", "views": 0, "platform": "youtube"}

        return {"status": "active", "views": int(views), "platform": "youtube"}
    except aiohttp.ClientError as exc:
        logger.exception("check_video network: %s", exc)
        return {"status": "error", "error_type": "network", "message": "Нет соединения с интернетом. Проверьте сеть и повторите."}
    except TimeoutError:
        return {"status": "error", "error_type": "timeout", "message": "Превышено время ожидания ответа YouTube."}
    except Exception as exc:
        logger.exception("check_video: %s", exc)
        return {"status": "error", "error_type": "unknown", "message": "Не удалось проверить видео. Попробуйте позже."}
    finally:
        if local is not None:
            await local.close()


async def check_video(
    url: str,
    published_at: datetime | str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """
    Публичные метрики ролика: YouTube (HTML), TikTok и Instagram (yt-dlp).

    Возврат при успехе: status active|shadowban|banned, views, опционально likes, platform.
    published_at учитывается только для YouTube (эвристика shadowban).
    """
    if not url or not str(url).strip():
        return _error("Ссылка на видео пустая.")
    video_url = str(url).strip()
    platform = _detect_platform(video_url)
    if platform == "youtube":
        return await _check_youtube_html(video_url, published_at=published_at, session=session)
    if platform in ("tiktok", "instagram"):
        return await _check_ytdlp_metadata(video_url, platform)
    return _error("Поддерживаются ссылки YouTube, TikTok и Instagram (Reels / видео).")
