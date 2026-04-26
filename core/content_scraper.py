"""
content_scraper.py — модуль для поиска трендового контента через yt-dlp.
Используется страницей Контент-ресёрч для парсинга топ-видео по нише.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import re

import aiohttp

logger = logging.getLogger(__name__)

# Расширения, которые плееры и ОС обычно понимают без донастройки
_KNOWN_VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".3gp"})


def _sniff_video_suffix(path: Path) -> str:
    """Определить подходящее расширение по заголовку файла (если yt-dlp оставил без суффикса)."""
    try:
        buf = path.read_bytes()[:64]
    except OSError:
        return ".mp4"
    if len(buf) >= 12 and buf[4:8] == b"ftyp":
        brand = buf[8:12]
        if brand == b"qt  ":
            return ".mov"
        return ".mp4"
    if len(buf) >= 4 and buf[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    if len(buf) >= 12 and buf[:4] == b"RIFF" and buf[8:12] == b"AVI ":
        return ".avi"
    return ".mp4"


def _safe_download_stem(stem: str, *, max_len: int = 120) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", (stem or "").strip()).strip("._ ") or "video"
    return s[:max_len]


def finalize_downloaded_video_path(path: Path) -> tuple[Path, str]:
    """
    Гарантировать «нормальное» имя с расширением (.mp4 и др.) для плееров и соцсетей.

    Если у файла нет известного видео-расширения — определяем по сигнатуре и переименовываем.
    """
    path = path.resolve()
    if not path.is_file():
        return path, path.name

    suf = path.suffix.lower()
    if suf in _KNOWN_VIDEO_SUFFIXES:
        return path, path.name

    sniff = _sniff_video_suffix(path)
    stem = path.stem if path.suffix else path.name
    base_stem = _safe_download_stem(stem)
    parent = path.parent
    candidate = parent / f"{base_stem}{sniff}"
    n = 0
    while candidate.exists() and candidate.resolve() != path.resolve():
        n += 1
        candidate = parent / f"{base_stem}_{n}{sniff}"
    try:
        path.rename(candidate)
    except OSError as exc:
        logger.warning("finalize_download: не удалось переименовать %s → %s: %s", path, candidate, exc)
        return path, path.name
    return candidate, candidate.name


# Map region code → relevance language for YouTube API
_REGION_LANG: dict[str, str] = {
    "KR": "ko",
    "TH": "th",
    "MY": "ms",
    "JP": "ja",
    "ID": "id",
    "US": "en",
    "RU": "ru",
    "VN": "vi",
}


def _to_youtube_shorts_url(url: str, video_id: str) -> str:
    """
    Normalize any YouTube video URL to shorts format.
    """
    vid = (video_id or "").strip()
    if vid:
        return f"https://www.youtube.com/shorts/{vid}"
    raw = (url or "").strip()
    if "watch?v=" in raw:
        try:
            vid = raw.split("watch?v=", 1)[1].split("&", 1)[0]
            if vid:
                return f"https://www.youtube.com/shorts/{vid}"
        except Exception:
            pass
    return raw


def _parse_iso_duration(iso: str) -> int:
    """Convert ISO 8601 duration (PT1M30S) to total seconds."""
    if not iso:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mn = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mn * 60 + s

ROOT = Path(__file__).resolve().parent.parent
_UPLOADS_DIR = ROOT / "data" / "uploads"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# ── Arbitrage game patterns ───────────────────────────────────────────────────
# Multilingual search queries used to find arbitrage-style gaming videos.
# Each entry covers EN + KO + TH variants to maximise recall across target GEOs.

ARBITRAGE_GAME_LABELS: dict[str, str] = {
    "tower_rust":  "Tower Rust",
    "mine_drop":   "Mine Drop",
    "aviator":     "Avia Master",
    "ice_fishing": "Ice Fishing",
}

ARBITRAGE_GAME_COLORS: dict[str, str] = {
    "tower_rust":  "#F59E0B",
    "mine_drop":   "#EF4444",
    "aviator":     "#3B82F6",
    "ice_fishing": "#06B6D4",
}

ARBITRAGE_GAME_PATTERNS: dict[str, list[str]] = {
    # Запросы под типичные заливы арбитража: shorts, x100, crash, strategy, «быстрый выигрыш», #shorts
    "tower_rust": [
        "tower game big win shorts",
        "tower rust win shorts strategy",
        "tower crash game x100 shorts",
        "towers gambling cashout win",
        "tower game quick win shorts",
        "타워 게임 대박 shorts",
        "tower game hack win shorts",
        "tower cashout reaction shorts",
    ],
    "mine_drop": [
        "mines game big win shorts",
        "mines predictor win shorts",
        "mine drop x100 cashout shorts",
        "mines strategy big win shorts",
        "mine game jackpot win shorts",
        "마인 게임 대박 shorts",
        "mines crash win shorts",
        "mines quick win shorts",
    ],
    "aviator": [
        "aviator game big win shorts",
        "aviator crash strategy shorts",
        "aviator x100 cashout shorts",
        "aviator quick big win shorts",
        "aviator 1win big win shorts",
        "aviator signal game shorts",
        "авиатор большой выигрыш shorts",
        "aviatrix big win shorts",
        "avia master game win shorts",
    ],
    "ice_fishing": [
        "ice fishing game big win shorts",
        "ice fishing slot max win shorts",
        "ice fishing crash win shorts",
        "ice fishing quick win shorts",
        "ice fishing x100 cashout shorts",
        "아이스 피싱 대박 shorts",
        "ice fishing gambling win shorts",
        "ice fishing bonus buy shorts",
    ],
}

ARBITRAGE_STYLE_KEYWORDS: tuple[str, ...] = (
    "shorts",
    "#shorts",
    "big win",
    "quick win",
    "x100",
    "cashout",
    "jackpot",
    "crash",
    "predictor",
    "strategy",
    "signal",
    "hack",
    "1win",
)


def _is_global_region(region: str | None) -> bool:
    if region is None:
        return True
    r = str(region).strip().upper()
    return r in ("", "GLOBAL", "ALL", "WORLD", "WW", "*")


def _normalize_yt_upload_date(ud: Any) -> str:
    """
    yt-dlp отдаёт upload_date как YYYYMMDD — фронт ждёт ISO для timeAgo.
    """
    s = str(ud or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}T12:00:00.000Z"
    return s


def _filter_youtube_shorts(
    videos: list[dict[str, Any]],
    *,
    max_duration_sec: int = 60,
) -> list[dict[str, Any]]:
    """YouTube Shorts ≤ 60 с; длительность 0 (неизвестна) пропускаем при фильтре."""
    out: list[dict[str, Any]] = []
    for v in videos:
        d = int(v.get("duration") or 0)
        if 0 < d <= max_duration_sec:
            out.append(v)
    return out


def _video_channel_id(video: dict[str, Any]) -> str:
    """Extract channel ID from channel_url, if present."""
    cu = str(video.get("channel_url") or "").strip()
    if not cu:
        return ""
    if "/channel/" in cu:
        return cu.rsplit("/channel/", 1)[-1].split("/", 1)[0].split("?", 1)[0].strip()
    return ""


def _normalize_watchlist_entries(watchlist: list[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in watchlist or []:
        s = str(raw or "").strip().lower()
        if not s:
            continue
        out.add(s)
        if "youtube.com/channel/" in s:
            out.add(s.rsplit("youtube.com/channel/", 1)[-1].split("/", 1)[0].split("?", 1)[0].strip())
    return {x for x in out if x}


def _watchlist_match(video: dict[str, Any], watchlist_norm: set[str]) -> str | None:
    if not watchlist_norm:
        return None
    channel = str(video.get("channel") or "").strip().lower()
    channel_url = str(video.get("channel_url") or "").strip().lower()
    channel_id = _video_channel_id(video).lower()
    for candidate in (channel, channel_url, channel_id):
        if candidate and candidate in watchlist_norm:
            return candidate
    return None


def _arb_relevance_score(video: dict[str, Any], game_key: str, game_queries: list[str]) -> int:
    """Heuristic relevance score for arbitrage-style uploads (0..100)."""
    title = str(video.get("title") or "").lower()
    channel = str(video.get("channel") or "").lower()
    views = int(video.get("view_count") or 0)
    duration = int(video.get("duration") or 0)
    score = 0

    if duration and duration <= 60:
        score += 25
    elif duration:
        score -= 10

    query_hits = 0
    for q in game_queries:
        qn = str(q or "").strip().lower()
        if not qn:
            continue
        tokens = [t for t in qn.split() if len(t) >= 4]
        if any(t in title for t in tokens):
            query_hits += 1
    score += min(30, query_hits * 4)

    kw_hits = sum(1 for kw in ARBITRAGE_STYLE_KEYWORDS if kw in title)
    score += min(30, kw_hits * 6)

    if views >= 1_000_000:
        score += 10
    elif views >= 100_000:
        score += 6
    elif views >= 10_000:
        score += 3

    game_hint = game_key.replace("_", " ")
    if any(tok in title for tok in game_hint.split()):
        score += 8
    if "official" in channel:
        score -= 6

    return max(0, min(100, score))


def _yt_dlp_bin() -> str | None:
    return shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")


def _yt_dlp_cmd() -> list[str] | None:
    """
    Resolve runnable yt-dlp command.
    Prefer system binary, fallback to `python -m yt_dlp`.
    """
    bin_path = _yt_dlp_bin()
    if bin_path:
        return [bin_path]
    # Fallback for environments where only pip module is installed.
    return [sys.executable, "-m", "yt_dlp"]


def _ytdlp_available() -> bool:
    return _yt_dlp_cmd() is not None


# Preset search URLs per source
_SEARCH_TEMPLATES: dict[str, str] = {
    "youtube": "ytsearch{limit}:{query}",
    "tiktok": "https://www.tiktok.com/search?q={query}",
}


def _clamp_search_limit(limit: int, *, cap: int = 50) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    return max(1, min(n, cap))


def _youtube_item_video_id(item: dict[str, Any]) -> str:
    """Безопасно достать videoId из ответа search.list (id может быть dict или реже строкой)."""
    rid = item.get("id")
    if isinstance(rid, dict):
        return str(rid.get("videoId", "") or "").strip()
    if isinstance(rid, str):
        return rid.strip()
    return ""


def _extract_thumbnail(entry: dict[str, Any]) -> str:
    """Лучшая превью из entry yt-dlp: сначала прямое поле, потом thumbnails[]."""
    t = entry.get("thumbnail")
    if t:
        return str(t)
    thumbs = entry.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        best = max(thumbs, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), default={})
        url = best.get("url")
        if url:
            return str(url)
    return ""


def _parse_entry(entry: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Преобразовать один JSON-объект yt-dlp в карточку видео."""
    if not isinstance(entry, dict):
        return None
    vid = str(entry.get("id") or entry.get("display_id") or "").strip()
    if not vid:
        return None
    raw_url = str(entry.get("webpage_url") or entry.get("url") or "")
    video_url = _to_youtube_shorts_url(raw_url, vid) if source == "youtube" else raw_url
    return {
        "id": vid,
        "title": str(entry.get("title") or "").strip(),
        "url": video_url,
        "thumbnail": _extract_thumbnail(entry),
        "duration": int(entry.get("duration") or 0),
        "view_count": int(entry.get("view_count") or 0),
        "like_count": int(entry.get("like_count") or 0),
        "comment_count": int(entry.get("comment_count") or 0),
        "upload_date": _normalize_yt_upload_date(entry.get("upload_date")),
        "channel": str(entry.get("channel") or entry.get("uploader") or ""),
        "channel_url": str(entry.get("channel_url") or entry.get("uploader_url") or ""),
        "source": source,
    }


async def _yt_dlp_search(
    ytdlp_cmd: list[str],
    url: str,
    source: str,
    *,
    full_meta: bool = True,
    timeout_sec: float = 90,
) -> list[dict[str, Any]]:
    """
    Один проход yt-dlp → список карточек (может быть пустым).

    full_meta=True (по умолчанию): без --flat-playlist — даёт likes, comments,
    upload_date, channel_url за счёт ~3-4 сек на 5 роликов.
    full_meta=False: быстрый flat-режим (1.5 сек), но без лайков и дат.
    """
    cmd = [
        *ytdlp_cmd,
        "--dump-json",
        "--no-download",
        "--no-warnings",
        "--quiet",
    ]
    if not full_meta:
        cmd.append("--flat-playlist")
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    results: list[dict[str, Any]] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            card = _parse_entry(entry, source)
            if card:
                results.append(card)
        except json.JSONDecodeError:
            continue
    return results


# Старое имя — обратная совместимость
async def _yt_dlp_flat_search(
    ytdlp_cmd: list[str],
    url: str,
    source: str,
    *,
    timeout_sec: float = 60,
) -> list[dict[str, Any]]:
    return await _yt_dlp_search(ytdlp_cmd, url, source, full_meta=True, timeout_sec=timeout_sec)


def _dedup_and_sort(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Убрать дубли по id, отсортировать по просмотрам desc, обрезать до limit."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for r in results:
        vid = str(r.get("id") or "").strip()
        if not vid or vid in seen:
            continue
        seen.add(vid)
        unique.append(r)
    unique.sort(key=lambda x: int(x.get("view_count") or 0), reverse=True)
    return unique[:limit]


async def search_videos(
    niche: str,
    source: str = "youtube",
    period_days: int = 7,
    limit: int = 10,
    region: str | None = "KR",
    *,
    shorts_only: bool = False,
    shorts_max_duration: int = 60,
    fetch_multiplier: int = 1,
) -> list[dict[str, Any]]:
    """
    Returns a list of video dicts sorted by view_count desc:
    {id, title, url, thumbnail, duration, view_count, like_count,
     comment_count, upload_date, channel, channel_url, source}

    region=None / пустой / GLOBAL — без regionCode в YouTube API (широкая выдача).
    shorts_only — после поиска оставить только ролики 1…shorts_max_duration сек (Shorts).
    fetch_multiplier — сколько кандидатов запросить до фильтра Shorts (для арбитраж-скана).
    """
    limit = _clamp_search_limit(limit, cap=50)
    want = limit
    mult = max(1, min(8, int(fetch_multiplier or 1)))
    fetch_n = min(50, max(want, want * mult)) if shorts_only else want
    api_n = min(25, fetch_n)

    if source == "youtube":
        yt = await _search_youtube_api(
            niche=niche, period_days=period_days, limit=api_n, region=region, shorts_only=shorts_only
        )
        # Use YouTube API results only when they're non-empty.
        # If the API is unavailable (403, quota exceeded, no key) → fall through to yt-dlp.
        if yt:
            if shorts_only:
                yt = _filter_youtube_shorts(yt, max_duration_sec=shorts_max_duration)
            return _dedup_and_sort(yt, want)
    if not _ytdlp_available():
        raise RuntimeError("yt-dlp не установлен или недоступен в PATH")

    ytdlp_cmd = _yt_dlp_cmd()
    if not ytdlp_cmd:
        raise RuntimeError("yt-dlp недоступен")
    raw_niche = (niche or "").strip()
    if source == "youtube":
        if not raw_niche:
            urls_try = [f"ytsearch{fetch_n}:shorts"]
        else:
            urls_try = [
                f"ytsearch{fetch_n}:{raw_niche} shorts",
                f"ytsearch{fetch_n}:{raw_niche} #shorts",
                f"ytsearch{fetch_n}:{raw_niche}",
            ]
    else:
        urls_try = [f"ytsearch{fetch_n}:{raw_niche or niche}"]

    merged: list[dict[str, Any]] = []
    try:
        for url in urls_try:
            try:
                batch = await _yt_dlp_search(ytdlp_cmd, url, source, full_meta=True, timeout_sec=90)
            except asyncio.TimeoutError:
                logger.warning("yt-dlp search timed out for URL: %s", url)
                continue
            if batch:
                merged.extend(batch)
    except Exception as exc:
        logger.exception("yt-dlp search error: %s", exc)
        raise RuntimeError(f"yt-dlp: ошибка поиска: {exc}") from exc

    if not merged:
        raise RuntimeError(
            "yt-dlp не вернул ни одного результата. "
            "Смягчите запрос (другие слова, на латинице) или проверьте, что yt-dlp обновлён и не блокируется сетью."
        )

    merged = _dedup_and_sort(merged, min(50, max(len(merged), want)))
    if shorts_only:
        short_list = _filter_youtube_shorts(merged, max_duration_sec=shorts_max_duration)
        if short_list:
            merged = short_list
        else:
            logger.warning(
                "yt-dlp: по запросу «%s» не найдено роликов ≤%ss (Shorts) — показаны лучшие по просмотрам без фильтра длительности",
                raw_niche[:80],
                shorts_max_duration,
            )
    return _dedup_and_sort(merged, want)


async def _search_youtube_api(
    niche: str,
    period_days: int = 7,
    limit: int = 10,
    region: str | None = "KR",
    *,
    shorts_only: bool = False,
) -> list[dict[str, Any]]:
    api_key = (os.environ.get("YOUTUBE_API_KEY") or "").strip()
    if not api_key:
        return []

    global_region = _is_global_region(region)
    region_code = (str(region or "").strip().upper() or "KR") if not global_region else ""
    lang = "en" if global_region else _REGION_LANG.get(region_code, "ko")
    limit = _clamp_search_limit(limit, cap=25)
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=max(1, period_days))
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    query = (niche or "").strip()
    normalized_query = re.sub(r"\s+", " ", query)
    query_variants = [q for q in [normalized_query, f"{normalized_query} shorts", normalized_query.replace("shorts", "").strip()] if q]
    if not query_variants:
        return []

    # Multi-pass: сначала короткие (Shorts), при shorts_only не расширяемся на long.
    passes = [
        {"order": "viewCount", "videoDuration": "short", "publishedAfter": published_after},
        {"order": "relevance", "videoDuration": "short", "publishedAfter": published_after},
    ]
    if not shorts_only:
        passes.append({"order": "relevance", "videoDuration": "any", "publishedAfter": None})
    timeout = aiohttp.ClientTimeout(total=20, connect=8)
    items: list[Any] = []
    stats_map: dict[str, dict[str, Any]] = {}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for q in query_variants:
                if items:
                    break
                for p in passes:
                    params: dict[str, str] = {
                        "key": api_key,
                        "part": "snippet",
                        "q": q,
                        "type": "video",
                        "maxResults": str(limit),
                        "order": p["order"],
                    }
                    if not global_region:
                        params["regionCode"] = region_code
                        params["relevanceLanguage"] = lang
                    else:
                        params["relevanceLanguage"] = "en"
                    if p["videoDuration"] != "any":
                        params["videoDuration"] = p["videoDuration"]
                    if p["publishedAfter"]:
                        params["publishedAfter"] = p["publishedAfter"]
                    async with session.get(YOUTUBE_SEARCH_URL, params=params) as resp:
                        if resp.status != 200:
                            logger.warning("YouTube search HTTP %s", resp.status)
                            continue
                        payload = await resp.json()
                    items = payload.get("items", []) if isinstance(payload, dict) else []
                    if items:
                        break

            video_ids = [_youtube_item_video_id(i) for i in items if isinstance(i, dict)]
            video_ids = [v for v in video_ids if v]
            if video_ids:
                v_params = {
                    "key": api_key,
                    "part": "statistics,contentDetails",
                    "id": ",".join(video_ids[:50]),
                    "maxResults": "50",
                }
                async with session.get(YOUTUBE_VIDEOS_URL, params=v_params) as v_resp:
                    if v_resp.status == 200:
                        v_payload = await v_resp.json()
                        for vi in v_payload.get("items", []):
                            vid = str(vi.get("id") or "")
                            stats_map[vid] = vi
    except Exception as exc:
        logger.warning("youtube api search failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for item in items:
        snippet = item.get("snippet", {}) if isinstance(item, dict) else {}
        vid = _youtube_item_video_id(item) if isinstance(item, dict) else ""
        if not vid:
            continue
        vi = stats_map.get(vid, {})
        statistics = vi.get("statistics", {}) if isinstance(vi, dict) else {}
        content_details = vi.get("contentDetails", {}) if isinstance(vi, dict) else {}
        channel_id = str(snippet.get("channelId") or "")
        out.append(
            {
                "id": vid,
                "title": str(snippet.get("title") or ""),
                "url": f"https://www.youtube.com/shorts/{vid}",
                "thumbnail": str((snippet.get("thumbnails", {}).get("high", {}) or {}).get("url", "")),
                "duration": _parse_iso_duration(str(content_details.get("duration") or "")),
                "view_count": int(statistics.get("viewCount", 0) or 0),
                "like_count": int(statistics.get("likeCount", 0) or 0),
                "comment_count": int(statistics.get("commentCount", 0) or 0),
                "upload_date": str(snippet.get("publishedAt") or ""),
                "channel": str(snippet.get("channelTitle") or ""),
                "channel_url": f"https://www.youtube.com/channel/{channel_id}" if channel_id else "",
                "source": "youtube",
                "region": "GLOBAL" if global_region else region_code,
            }
        )
    return out[:limit]


async def download_video(url: str, uploads_dir: Path | None = None) -> dict[str, Any]:
    """
    Скачивание через yt-dlp с приоритетом контейнера **MP4** (H.264/AAC где возможно).

    Используется сортировка форматов под mp4, merge в mp4 и --remux-video mp4
    (нужен **ffmpeg** в PATH). Итоговое имя файла по возможности — .mp4.
    """
    if not _ytdlp_available():
        return {"status": "error", "error": "yt-dlp не установлен"}

    out_dir = uploads_dir or _UPLOADS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ytdlp_cmd = _yt_dlp_cmd()
    if not ytdlp_cmd:
        return {"status": "error", "error": "yt-dlp не установлен"}

    output_tmpl = str(out_dir / "%(id)s.%(ext)s")
    cmd = [
        *ytdlp_cmd,
        "--no-warnings",
        "--quiet",
        "--print", "after_move:filepath",
        # Сначала отдаём приоритет уже mp4-потокам; иначе лучшее видео+аудио и склейка в mp4.
        "-S", "ext:mp4",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        # Дожимает контейнер до mp4 (копирование или лёгкий remux через ffmpeg).
        "--remux-video", "mp4",
        "-o", output_tmpl,
        url,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        return {"status": "error", "error": "Таймаут при скачивании"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        return {"status": "error", "error": err or "yt-dlp вернул ошибку"}

    out_text = stdout.decode("utf-8", errors="replace")
    for line in reversed([ln.strip() for ln in out_text.splitlines() if ln.strip()]):
        p = Path(line)
        if p.is_file():
            p2, fname = finalize_downloaded_video_path(p)
            return {"status": "ok", "path": str(p2), "filename": fname}

    return {"status": "error", "error": "Файл не найден после скачивания"}


async def scan_arbitrage_videos(
    games: list[str] | None = None,
    region: str | None = None,
    period_days: int = 7,
    limit_per_query: int = 5,
    *,
    shorts_only: bool = True,
    fetch_multiplier: int = 5,
    watchlist_channels: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Search for arbitrage-style gaming videos across all registered game patterns.

    По умолчанию: **только YouTube Shorts** (≤60 с), **без привязки к региону** (region=None).
    Запросы под типичные заливы — см. ARBITRAGE_GAME_PATTERNS.

    Runs all per-game queries in parallel, deduplicates by video ID, sorts
    by view_count descending.

    Returns: {game_key: [video, …], …}
    Each video gets extra fields: game (key) + game_label.
    """
    target_games = games or list(ARBITRAGE_GAME_PATTERNS.keys())
    output: dict[str, list[dict[str, Any]]] = {}
    reg = None if _is_global_region(region) else (str(region or "").strip().upper() or None)
    watchlist_norm = _normalize_watchlist_entries(watchlist_channels)

    for game_key in target_games:
        patterns = ARBITRAGE_GAME_PATTERNS.get(game_key)
        if not patterns:
            output[game_key] = []
            continue

        tasks = [
            search_videos(
                niche=q,
                source="youtube",
                period_days=period_days,
                limit=limit_per_query,
                region=reg,
                shorts_only=shorts_only,
                fetch_multiplier=fetch_multiplier,
            )
            for q in patterns
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        # Deduplicate: keep the record with the highest view_count
        seen: dict[str, dict[str, Any]] = {}
        for batch in raw:
            if isinstance(batch, BaseException):
                logger.debug("arbitrage scan %s batch error: %s", game_key, batch)
                continue
            for video in batch:
                vid_key = str(video.get("id") or video.get("url") or "")
                if not vid_key:
                    continue
                if vid_key not in seen or (video.get("view_count") or 0) > (seen[vid_key].get("view_count") or 0):
                    wl_match = _watchlist_match(video, watchlist_norm)
                    arb_score = _arb_relevance_score(video, game_key, patterns)
                    if wl_match:
                        arb_score = min(100, arb_score + 25)
                    seen[vid_key] = {
                        **video,
                        "game": game_key,
                        "game_label": ARBITRAGE_GAME_LABELS.get(game_key, game_key),
                        "arb_score": arb_score,
                        "watchlist_hit": bool(wl_match),
                        "watchlist_match": wl_match or "",
                    }

        output[game_key] = sorted(
            seen.values(),
            key=lambda v: (
                int(v.get("watchlist_hit") is True),
                int(v.get("arb_score") or 0),
                int(v.get("view_count") or 0),
            ),
            reverse=True,
        )[:limit_per_query * 3]

    return output


def get_queued_videos(uploads_dir: Path | None = None) -> list[dict[str, Any]]:
    """
    Returns list of downloaded videos available for uniqualizer.
    """
    d = uploads_dir or _UPLOADS_DIR
    if not d.exists():
        return []

    videos = []
    for f in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".avi"):
            stat = f.stat()
            videos.append({
                "filename": f.name,
                "path": str(f),
                "size_mb": round(stat.st_size / 1_048_576, 1),
                "modified": stat.st_mtime,
            })

    return videos[:50]


def enrich_video_risk(
    video: dict[str, Any],
    *,
    query_patterns: list[str] | None = None,
    watchlist_hit: bool = False,
) -> dict[str, Any]:
    """
    Lightweight risk scoring for research results.
    Returns original video dict enriched with normalized risk fields.
    """
    out = dict(video)
    title = str(video.get("title") or "").lower()
    desc = str(video.get("description") or "").lower()
    channel = str(video.get("channel") or "").lower()
    text = f"{title}\n{desc}\n{channel}"

    signal_map: dict[str, int] = {}

    def _add(signal: str, pts: int) -> None:
        signal_map[signal] = signal_map.get(signal, 0) + pts

    high_markers = (
        "x100",
        "x500",
        "jackpot",
        "big win",
        "signal",
        "predictor",
        "promo code",
        "промокод",
        "бонус",
        "бонус в профиле",
        "схема заработка",
        "легкие деньги",
        "лёгкие деньги",
        "забери бонус",
        "ссылка в описании",
        "link in bio",
        "check profile",
        "no deposit bonus",
        "aviator",
        "casino",
        "slots",
    )
    medium_markers = ("cashout", "win", "strategy", "bonus", "gambling")

    for k in high_markers:
        if k in text:
            _add(f"kw:{k}", 12)
    for k in medium_markers:
        if k in text:
            _add(f"kw:{k}", 6)

    if "review" in text or "обзор" in text or "explanation" in text:
        _add("context:review", -12)
    if "no links" in text or "без ссылки" in text:
        _add("context:no_links", -10)

    if watchlist_hit:
        _add("watchlist_hit", 18)

    qp = [str(x or "").strip().lower() for x in (query_patterns or []) if str(x or "").strip()]
    if qp:
        q_hits = 0
        for q in qp:
            toks = [t for t in q.split() if len(t) >= 4]
            if any(t in text for t in toks):
                q_hits += 1
        if q_hits:
            _add("query_match", min(15, q_hits * 4))

    ubt_mask_score = min(100, sum(signal_map.values()))
    risk_score = int(max(0, min(100, ubt_mask_score)))
    if risk_score >= 65:
        tier = "high"
    elif risk_score >= 35:
        tier = "medium"
    else:
        tier = "low"

    confidence = 0.45 + min(0.5, (len(signal_map) * 0.08))
    confidence = float(max(0.0, min(0.99, confidence)))
    out["risk_score"] = risk_score
    out["risk_tier"] = tier
    out["risk_confidence"] = round(confidence, 3)
    out["risk_signals"] = list(signal_map.keys())
    out["risk_signal_map"] = signal_map
    out["ubt_mask_score"] = ubt_mask_score
    out["ubt_flags"] = [k for k in signal_map.keys() if signal_map.get(k, 0) >= 10]
    out["ubt_marker"] = risk_score >= 65
    out["ubt_suspected"] = risk_score >= 35
    return out


