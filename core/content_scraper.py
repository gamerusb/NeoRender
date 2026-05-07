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

# ── Stealth UBT scan patterns (2026) ─────────────────────────────────────────
# Арбитражники больше не называют ролики именами игр — YouTube блокирует.
# Вместо этого они маскируются под реакции, «секреты», «новые приложения» и тд.
# Поиск ведётся по ПОВЕДЕНЧЕСКИМ паттернам — что говорит, как показывает,
# какие слова триггерят интерес без называния продукта.
# Каждая категория → тип маскировки → RU + EN + KO + TH + VI запросы.

# ── Game catalogue (2026) ─────────────────────────────────────────────────────
# Platforms: 1win · Mostbet · Pin-Up · Betwinner · BC.game · Stake
# Each key maps to: display label, hex colour, search-query patterns

ARBITRAGE_GAME_LABELS: dict[str, str] = {
    # ── Crash-genre ───────────────────────────────────────────────────────────
    "aviator":          "Aviator",
    "lucky_jet":        "Lucky Jet",
    "spaceman":         "Spaceman",
    "jetx":             "JetX / JetX2",
    "rocket_queen":     "Rocket Queen",
    "zeppelin":         "Zeppelin",
    "balloon":          "Balloon",
    "space_xy":         "Space XY",
    "jumper":           "Jumper",
    # ── Tower / Build ─────────────────────────────────────────────────────────
    "tower_rush":       "Tower Rush",
    "tower_rust":       "Tower Rust",          # legacy key kept
    # ── Mine / Grid ──────────────────────────────────────────────────────────
    "mine_drop":        "Mine Drop",
    # ── Fishing ───────────────────────────────────────────────────────────────
    "ice_fishing":      "Ice Fishing",
    "ice_fishing_evo":  "Ice Fishing Evolution",
    # ── Sport crash ───────────────────────────────────────────────────────────
    "penalty_kick":     "Penalty Kick",
    "goal":             "Goal (Football)",
    "cricket_x":        "Cricket X",
    # ── Binary / Card ─────────────────────────────────────────────────────────
    "inout":            "InOut",
    "hilo":             "Hi-Lo",
    "coinflip":         "Coin Flip",
    # ── Misc ──────────────────────────────────────────────────────────────────
    "plinko":           "Plinko X",
    "dice_duel":        "Dice Duel",
    "wheel":            "Fortune Wheel",
    "candy":            "Candy Blitz",
}

ARBITRAGE_GAME_COLORS: dict[str, str] = {
    "aviator":          "#3B82F6",
    "lucky_jet":        "#10B981",
    "spaceman":         "#8B5CF6",
    "jetx":             "#6366F1",
    "rocket_queen":     "#EC4899",
    "zeppelin":         "#F97316",
    "balloon":          "#06B6D4",
    "space_xy":         "#14B8A6",
    "jumper":           "#84CC16",
    "tower_rush":       "#D97706",
    "tower_rust":       "#F59E0B",
    "mine_drop":        "#EF4444",
    "ice_fishing":      "#06B6D4",
    "ice_fishing_evo":  "#0EA5E9",
    "penalty_kick":     "#84CC16",
    "goal":             "#22C55E",
    "cricket_x":        "#A3E635",
    "inout":            "#F43F5E",
    "hilo":             "#6366F1",
    "coinflip":         "#FBBF24",
    "plinko":           "#F97316",
    "dice_duel":        "#EC4899",
    "wheel":            "#14B8A6",
    "candy":            "#FB7185",
}

ARBITRAGE_GAME_PATTERNS: dict[str, list[str]] = {

    # ═══════════════════════════════════════════════════════════════════════════
    # CRASH-GENRE  (multiplier-based games that end on crash/cashout)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Aviator (Spribe — oldest, still dominant globally) ─────────────────────
    "aviator": [
        "aviator game big win shorts",
        "aviator crash x100 cashout shorts",
        "aviator predictor signal shorts",
        "aviator strategy 1win shorts",
        "авиатор большой выигрыш шортс",
        "авиатор сигнал предиктор шортс",
        "에비에이터 대박 shorts",
        "에비에이터 신호 전략 shorts",
        "เกม aviator โบนัส shorts",
        "aviatrix win shorts strategy",
        "aviator hack bonus code shorts",
        "avia master win reaction shorts",
    ],

    # ── Lucky Jet (1win exclusive, huge KR/RU/VN) ─────────────────────────────
    "lucky_jet": [
        "lucky jet big win shorts",
        "lucky jet x100 cashout shorts",
        "lucky jet strategy predictor shorts",
        "lucky jet 1win signal shorts",
        "лаки джет большой выигрыш шортс",
        "лаки джет сигнал предиктор шортс",
        "러키젯 대박 shorts",
        "러키젯 신호 전략 shorts",
        "lucky jet promo bonus shorts",
        "lucky jet hack reaction shorts",
        "jetx big win cashout shorts",
    ],

    # ── Spaceman (Pragmatic Play — growing fast in SEA/KR) ────────────────────
    "spaceman": [
        "spaceman big win x100 shorts",
        "spaceman strategy cashout shorts",
        "spaceman predictor signal shorts",
        "spaceman bonus buy win shorts",
        "спейсмен большой выигрыш шортс",
        "스페이스맨 대박 shorts",
        "스페이스맨 신호 전략 shorts",
        "spaceman pragmatic win shorts",
        "spaceman 1win cashout shorts",
        "spaceman crash reaction shorts",
    ],

    # ── JetX / JetX2 (SmartSoft — Mostbet flagship, 2025-2026 surge) ──────────
    "jetx": [
        "jetx game big win shorts",
        "jetx2 strategy cashout shorts",
        "jetx2 x100 win reaction shorts",
        "jetx mostbet big win shorts",
        "jetx predictor signal shorts",
        "젯엑스 대박 shorts",
        "젯엑스2 전략 신호 shorts",
        "jetx прогноз выигрыш шортс",
        "jetx win free promo shorts",
        "jet x2 crash cashout shorts",
    ],

    # ── Rocket Queen (Pin-Up flagship, 2026) ───────────────────────────────────
    "rocket_queen": [
        "rocket queen game win shorts",
        "rocket queen cashout x100 shorts",
        "rocket queen strategy pin up shorts",
        "rocket queen big win reaction shorts",
        "로켓 퀸 대박 shorts",
        "로켓 퀸 전략 캐시아웃 shorts",
        "rocket queen выигрыш шортс",
        "rocket queen signal predictor shorts",
        "rocket queen pinup win shorts",
        "rocket crash game win shorts",
    ],

    # ── Zeppelin (Spribe/BGaming, hugely popular in RU/BR/TR) ─────────────────
    "zeppelin": [
        "zeppelin game big win shorts",
        "zeppelin crash cashout shorts",
        "zeppelin strategy x100 win shorts",
        "zeppelin predictor signal shorts",
        "цеппелин большой выигрыш шортс",
        "제플린 게임 대박 shorts",
        "제플린 전략 shorts",
        "zeppelin mostbet win shorts",
        "zeppelin 1win big win shorts",
        "zeppelin hack bonus win shorts",
    ],

    # ── Balloon (Spribe, balloon crash — growing TH/ID/VN) ────────────────────
    "balloon": [
        "balloon game big win shorts",
        "balloon crash x100 cashout shorts",
        "balloon strategy win shorts",
        "balloon game 1win win shorts",
        "풍선 게임 대박 shorts",
        "balloon выигрыш шортс",
        "balloon predictor signal shorts",
        "เกม balloon โบนัส shorts",
        "game balon menang besar shorts",
        "balloon mostbet cashout shorts",
    ],

    # ── Space XY (BGaming — growing KR/TH/ID) ─────────────────────────────────
    "space_xy": [
        "space xy big win shorts",
        "space xy cashout x100 shorts",
        "space xy strategy win shorts",
        "space xy predictor signal shorts",
        "스페이스 xy 대박 shorts",
        "space xy выигрыш шортс",
        "space xy bgaming win shorts",
        "เกม space xy ได้เงิน shorts",
        "space xy 1win big win shorts",
        "space xy free bonus win shorts",
    ],

    # ── Jumper (SmartSoft, 2025-2026 new release) ──────────────────────────────
    "jumper": [
        "jumper game big win shorts",
        "jumper crash cashout win shorts",
        "jumper game strategy x100 shorts",
        "jumper 1win big win shorts",
        "점퍼 게임 대박 shorts",
        "점퍼 전략 캐시아웃 shorts",
        "jumper выигрыш шортс",
        "jumper smartsoft win shorts",
        "เกม jumper ได้เงิน shorts",
        "jumper game win reaction shorts",
        "jump game cashout strategy shorts",
    ],

    # ═══════════════════════════════════════════════════════════════════════════
    # TOWER / BUILD GENRE
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Tower Rush (1win/Mostbet, 2025-2026 explosion) ─────────────────────────
    "tower_rush": [
        "tower rush big win shorts",
        "tower rush strategy cashout shorts",
        "tower rush x100 win shorts",
        "tower rush 1win big win shorts",
        "타워 러시 대박 shorts",
        "타워 러시 전략 신호 shorts",
        "tower rush выигрыш шортс",
        "tower rush predictor signal shorts",
        "tower rush promo code win shorts",
        "타워 게임 대박 방법 shorts",
        "tower rush mostbet cashout shorts",
        "tower rush reaction win shorts",
    ],

    # ── Tower Rust (legacy name, same game pattern) ────────────────────────────
    "tower_rust": [
        "tower rust win shorts strategy",
        "tower game big win cashout shorts",
        "tower crash game x100 shorts",
        "tower game promo code win shorts",
        "타워 게임 대박 shorts",
        "tower cashout reaction shorts",
        "1win tower big win shorts",
    ],

    # ═══════════════════════════════════════════════════════════════════════════
    # FISHING GENRE
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Ice Fishing (1win classic) ─────────────────────────────────────────────
    "ice_fishing": [
        "ice fishing big win shorts",
        "ice fishing cashout strategy shorts",
        "ice fishing x100 win shorts",
        "ice fishing 1win big win shorts",
        "아이스 피싱 대박 shorts",
        "ice fishing выигрыш шортс",
        "ice fishing predictor signal shorts",
        "ice fishing bonus buy shorts",
    ],

    # ── Ice Fishing Evolution (Evolution Gaming, 2025 launch) ──────────────────
    "ice_fishing_evo": [
        "ice fishing evolution big win shorts",
        "ice fishing evolution bonus buy shorts",
        "ice fishing evolution max win shorts",
        "ice fishing evolution live win shorts",
        "아이스 피싱 에볼루션 대박 shorts",
        "아이스 피싱 에볼루션 보너스 shorts",
        "ice fishing evolution выигрыш шортс",
        "ice fishing evolution cashout shorts",
        "evolution ice fishing win reaction shorts",
        "ice fishing evo strategy shorts",
    ],

    # ═══════════════════════════════════════════════════════════════════════════
    # MINE / GRID GENRE
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Mine Drop / Mines ─────────────────────────────────────────────────────
    "mine_drop": [
        "mines game big win shorts",
        "mines predictor strategy shorts",
        "mine drop x100 cashout shorts",
        "mines 1win big win shorts",
        "마인 게임 대박 shorts",
        "mines выигрыш шортс",
        "stake mines big win shorts",
        "mines signal hack win shorts",
        "mine game jackpot cashout shorts",
        "mines bonus win reaction shorts",
    ],

    # ═══════════════════════════════════════════════════════════════════════════
    # SPORT CRASH GENRE
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Penalty Kick / Penalty Shootout ───────────────────────────────────────
    "penalty_kick": [
        "penalty kick game big win shorts",
        "penalty shootout cashout strategy shorts",
        "penalty 1win big win shorts",
        "페널티 킥 게임 대박 shorts",
        "penalty kick выигрыш шортс",
        "penalty kick predictor win shorts",
        "penalty game jackpot cashout shorts",
        "เกมเตะ penalty โบนัส shorts",
    ],

    # ── Goal — Football crash (SmartSoft, dominant KR/TH/VN) ─────────────────
    "goal": [
        "goal game big win shorts",
        "goal crash cashout strategy shorts",
        "goal football game x100 win shorts",
        "goal 1win big win shorts",
        "골 게임 대박 shorts",
        "골 크래시 전략 신호 shorts",
        "goal game выигрыш шортс",
        "goal smartsoft win shorts",
        "เกม goal ได้เงิน shorts",
        "goal game win reaction shorts",
        "goal crash signal predictor shorts",
    ],

    # ── Cricket X (1win/Mostbet, dominant IN/BD/PK) ────────────────────────────
    "cricket_x": [
        "cricket x big win shorts",
        "cricket x cashout strategy shorts",
        "cricket x x100 win shorts",
        "cricket x 1win big win shorts",
        "cricket x predictor signal shorts",
        "cricket x game win reaction shorts",
        "cricket crash game win shorts",
        "क्रिकेट एक्स बड़ी जीत shorts",
        "cricket x বড় জয় shorts",
    ],

    # ═══════════════════════════════════════════════════════════════════════════
    # BINARY / PREDICTION GENRE
    # ═══════════════════════════════════════════════════════════════════════════

    # ── InOut / In-Out (1win/Mostbet, binary prediction) ──────────────────────
    "inout": [
        "inout game big win shorts",
        "in out game strategy cashout shorts",
        "inout x100 win reaction shorts",
        "inout 1win big win shorts",
        "인아웃 게임 대박 shorts",
        "인아웃 전략 캐시아웃 shorts",
        "inout выигрыш шортс",
        "in out predictor signal shorts",
        "inout mostbet win shorts",
        "inout game hack bonus shorts",
    ],

    # ── Hi-Lo (1win/Mostbet card game) ───────────────────────────────────────
    "hilo": [
        "hi lo card game big win shorts",
        "hilo cashout strategy shorts",
        "hilo x100 win shorts",
        "hilo 1win big win shorts",
        "하이로우 게임 대박 shorts",
        "hilo predictor signal shorts",
        "hi lo выигрыш шортс",
        "hilo hack bonus win shorts",
    ],

    # ── Coin Flip ─────────────────────────────────────────────────────────────
    "coinflip": [
        "coin flip game big win shorts",
        "coinflip cashout x100 shorts",
        "coinflip 1win win shorts",
        "동전 게임 대박 shorts",
        "coinflip predictor win shorts",
        "coinflip выигрыш шортс",
        "coin flip jackpot shorts",
    ],

    # ═══════════════════════════════════════════════════════════════════════════
    # MISC
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Plinko X ─────────────────────────────────────────────────────────────
    "plinko": [
        "plinko game big win shorts",
        "plinko x max win cashout shorts",
        "plinko jackpot win shorts",
        "plinko 1win big win shorts",
        "플링코 대박 shorts",
        "plinko выигрыш шортс",
        "plinko strategy signal win shorts",
        "plinko ball cashout shorts",
    ],

    # ── Dice Duel ────────────────────────────────────────────────────────────
    "dice_duel": [
        "dice game big win shorts",
        "dice duel cashout strategy shorts",
        "dice x100 win shorts",
        "주사위 게임 대박 shorts",
        "dice predictor win shorts",
        "dice выигрыш шортс",
        "dice gambling jackpot shorts",
    ],

    # ── Fortune Wheel ────────────────────────────────────────────────────────
    "wheel": [
        "fortune wheel big win shorts",
        "wheel casino cashout jackpot shorts",
        "wheel x100 win shorts",
        "럭키 휠 대박 shorts",
        "wheel predictor win signal shorts",
        "колесо фортуны выигрыш шортс",
        "spin win bonus shorts",
    ],

    # ── Candy Blitz (crash-candy genre, growing 2026) ─────────────────────────
    "candy": [
        "candy blitz big win shorts",
        "candy game cashout x100 shorts",
        "candy blitz bonus buy max win shorts",
        "candy crash game win shorts",
        "캔디 게임 대박 shorts",
        "candy game выигрыш шортс",
        "candy blitz strategy win shorts",
        "candy blitz 1win cashout shorts",
    ],
}

# ── UBT link-masking CTA patterns ─────────────────────────────────────────────
# Типичные фразы, которыми арбитражники маскируют ссылки на оффер.
# Русские + английские + корейские + тайские варианты.
UBT_MASKING_PATTERNS: tuple[str, ...] = (
    # ── RU — профиль / шапка (classic, still dominant) ───────────────────────
    "ссылка в профиле", "ссылка в шапке", "ссылка в описании", "ссылка в имени",
    "ссылка на игру", "ссылка на казино", "ссылка в комментарии",
    "игра в профиле", "игра в шапке", "игра в описании", "игра в имени",
    "жми на ник", "тыкни на ник", "нажми на ник", "жми на аватар",
    "тыкни на аватар", "нажми на аватар", "заходи в профиль", "перейди в профиль",
    "смотри профиль", "шапка профиля",
    "бонус в профиле", "бонус в шапке", "бонус в описании",
    "промокод в профиле", "промокод в шапке", "промо в шапке",
    # ── RU — Telegram (2025-2026 dominant channel, replaces direct links) ──────
    "телеграм в профиле", "телеграм в шапке", "телеграм в описании",
    "тг в профиле", "тг в шапке", "тг ссылка", "тг бот",
    "пиши в телеграм", "напиши в тг", "напиши мне в лс",
    "телеграм бот бонус", "телеграм канал игра", "тг канал казино",
    "все в тг", "жми в тг", "тг ссылка в шапке",
    # ── RU — QR-код (2026 new — прямо в кадре, без кликабельных ссылок) ───────
    "qr код в видео", "сканируй qr", "qr в кадре", "отсканируй код",
    "qr код бонус", "qr регистрация", "qr ссылка",
    # ── RU — «Это приложение» / без названия ─────────────────────────────────
    "это приложение платит", "это приложение дало", "такое приложение нашёл",
    "нашёл игру", "эта игра платит", "название в профиле", "игра без названия",
    # ── RU — регистрация / депозит ────────────────────────────────────────────
    "первый депозит", "первый депо", "без депозита", "бездепозитный",
    "фриспины", "фри спины", "бесплатные спины",
    "забери бонус", "получи бонус", "забрать бонус", "активировать бонус",
    "регистрируйся", "регайся", "зарегистрироваться", "создай аккаунт",
    "пополни счёт", "пополни баланс", "внеси депозит",
    "ссылка для регистрации", "регистрация по ссылке",
    # ── EN — profile / bio ────────────────────────────────────────────────────
    "link in bio", "link in profile", "link in description", "link in name",
    "game in bio", "casino in bio", "check profile", "see profile",
    "profile link", "bio link", "click nick", "tap avatar", "tap profile",
    "go to profile", "visit profile", "open profile",
    "register via link", "sign up link", "bonus link",
    # ── EN — Telegram (2025-2026 dominant) ───────────────────────────────────
    "telegram in bio", "telegram in profile", "telegram link", "tg link",
    "dm me for link", "dm for bonus", "message me for link",
    "telegram bot bonus", "join telegram", "telegram channel casino",
    "find me on telegram", "tg bot link",
    # ── EN — QR code ─────────────────────────────────────────────────────────
    "scan the qr", "qr code in video", "scan qr for bonus",
    "qr code register", "scan to play",
    # ── EN — «This app/game» nameless ────────────────────────────────────────
    "this app pays", "found this app", "this game actually pays",
    "game name in bio", "app name in profile", "found this game",
    "this app is legit", "download link in bio",
    # ── EN — deposit / bonus ─────────────────────────────────────────────────
    "no deposit bonus", "free spins", "first deposit bonus",
    "claim bonus", "get bonus", "grab bonus", "free bonus",
    "promo code", "promocode", "exclusive bonus",
    # ── KO — 링크 ─────────────────────────────────────────────────────────────
    "프로필 링크", "프로필에서", "링크 클릭", "닉네임 클릭",
    "바이오 링크", "설명란 링크",
    # ── KO — 텔레그램 (2026 dominant in KR market) ───────────────────────────
    "텔레그램 링크", "텔레그램 프로필", "텔레그램 메시지", "tg 링크",
    "텔레그램 봇 보너스", "텔레그램 채널", "dm 주세요", "디엠 주세요",
    # ── KO — QR / 앱 이름 숨김 ───────────────────────────────────────────────
    "qr 코드 스캔", "qr 코드 영상에", "이 앱 돈 나와", "게임 이름 프로필에",
    "이 앱 찾았어", "이 게임 진짜야",
    # ── TH — ลิงก์ ───────────────────────────────────────────────────────────
    "ลิงก์ในโปรไฟล์", "ดูโปรไฟล์", "กดที่ชื่อ", "รับโบนัส", "สมัครสมาชิก",
    "เทเลแกรมลิงก์", "ไลน์ลิงก์", "สแกน qr รับโบนัส",
    # ── VI — liên kết ────────────────────────────────────────────────────────
    "link trong bio", "xem profile", "nhấn vào tên", "đăng ký",
    "link telegram", "nhắn tin cho tôi",
    # ── ID — tautan ──────────────────────────────────────────────────────────
    "link di bio", "cek profil", "klik nama", "daftar sekarang",
    "link telegram di bio", "dm untuk link",
)

# ── Link-shortener domains ─────────────────────────────────────────────────────
LINK_SHORTENER_DOMAINS: frozenset[str] = frozenset({
    "bit.ly", "tinyurl.com", "short.io", "t.ly", "rb.gy", "ow.ly",
    "is.gd", "buff.ly", "adf.ly", "linktr.ee", "lit.link",
    "beacons.ai", "bio.link", "direct.me", "taplink.cc",
    "milkshake.app", "lnkd.in", "snip.ly", "cutt.ly",
    "smarturl.it", "lnk.to", "fanlink.to", "shorturl.at",
    "tiny.cc", "t.co", "shorte.st", "bc.vc",
})

# ── Niche / offer classification ──────────────────────────────────────────────
OFFER_NICHE_PATTERNS: dict[str, tuple[str, ...]] = {
    "casino": (
        "казино", "casino", "слоты", "slots", "рулетка", "roulette",
        "покер", "poker", "джекпот", "jackpot", "фриспины", "free spin",
        "ставки", "betting", "букмекер", "bookie", "gambling",
        "1win", "mostbet", "pin up", "melbet", "winbet",
    ),
    "crash": (
        "авиатор", "aviator", "лаки джет", "lucky jet", "spaceman",
        "jetx", "crash game", "x100", "x50", "x200", "cashout",
        "краш", "crash", "withdraw", "cashout reaction",
    ),
    "crypto": (
        "крипта", "криптовалюта", "crypto", "bitcoin", "биткоин",
        "ethereum", "eth", "binance", "bybit", "окекс", "okex",
        "nft", "defi", "p2e", "play to earn", "инвестиции", "invest",
        "памп", "pump", "заработок на крипте",
    ),
    "nutra": (
        "похудение", "диета", "diet", "weight loss", "кето", "keto",
        "таблетки", "pills", "суперсредство", "результат за",
        "минус кг", "похудел", "стройная", "flat belly",
    ),
    "apps": (
        "скачай приложение", "download app", "install", "установи",
        "бесплатно скачать", "free download", "apk", "play store",
        "app store", "новое приложение", "new app",
    ),
    "betting": (
        "ставка", "bet", "прогноз", "прогнозы", "матч", "match",
        "коэффициент", "odds", "экспресс", "accumulator", "tipster",
        "winner prediction", "sure bet",
    ),
}

ARBITRAGE_STYLE_KEYWORDS: tuple[str, ...] = (
    "shorts", "#shorts",
    "big win", "quick win", "x100", "x50", "x200",
    "cashout", "jackpot", "crash", "predictor",
    "strategy", "signal", "hack",
    "1win", "mostbet", "pinup", "pin-up",
    "free spins", "bonus", "promo", "no deposit",
    "выигрыш", "大勝", "대박",
)

# ── Stealth behavioral categories (2026) ──────────────────────────────────────
# Реальные поисковые запросы 2026 — по поведению/маскировке, не по именам игр.
# Арбитражники снимают «реакцию», «секретный метод», «новое приложение» — без
# упоминания казино/краша в заголовке. YouTube видит обычный контент.

STEALTH_CATEGORY_LABELS: dict[str, str] = {
    # ── Classic 8 ──────────────────────────────────────────────────────────────
    "money_reaction":   "Шок-реакция",
    "secret_method":    "Секретный метод",
    "new_app":          "Новое приложение",
    "multiplier":       "Мультипликатор",
    "lifestyle":        "Пассивный доход",
    "urgency":          "Срочность",
    "withdrawal_proof": "Вывод / Скрин",
    "phone_screen":     "Экран телефона",
    # ── 2026 additions ────────────────────────────────────────────────────────
    "telegram_funnel":  "Telegram-воронка",
    "qr_code_mask":     "QR-маскировка",
    "challenge_format": "Челлендж / Day-N",
    "ai_hack":          "AI-лайфхак",
    "tutorial_mask":    "Псевдообучение",
}

STEALTH_CATEGORY_COLORS: dict[str, str] = {
    "money_reaction":   "#10B981",
    "secret_method":    "#8B5CF6",
    "new_app":          "#3B82F6",
    "multiplier":       "#EF4444",
    "lifestyle":        "#F59E0B",
    "urgency":          "#F97316",
    "withdrawal_proof": "#06B6D4",
    "phone_screen":     "#EC4899",
    "telegram_funnel":  "#2CA5E0",
    "qr_code_mask":     "#F43F5E",
    "challenge_format": "#A78BFA",
    "ai_hack":          "#34D399",
    "tutorial_mask":    "#FB923C",
}

STEALTH_SCAN_PATTERNS: dict[str, list[str]] = {
    # ── Категория 1: Шок-реакция на деньги ────────────────────────────────────
    # Реальные форматы 2026: стримерские нарезки (split-screen: реакция сверху,
    # игра снизу), лицо с открытым ртом + цифры. Казино в заголовке никогда.
    "money_reaction": [
        # RU — реальные форматы с форумов
        "реакция стримера большой выигрыш шортс",
        "не поверил сколько заработал шортс",
        "мой доход сегодня покажу шортс",
        "стример не ожидал такого шортс",
        # EN
        "streamer reaction big win shorts",
        "cant believe how much i made shorts",
        "my income today shocking shorts",
        # KO
        "스트리머 반응 수익 shorts",
        "믿을 수 없는 수입 shorts",
        # TH
        "สตรีมเมอร์ ได้เงิน ตกใจ shorts",
        # ID
        "streamer reaksi menang banyak shorts",
    ],

    # ── Категория 2: Секретный метод / тактика ────────────────────────────────
    # Форум-инсайт 2026: "Эта тактика работает 3 из 5 раз", "Вот почему
    # букмекеры боятся этот способ" — интрига без называния вертикали.
    "secret_method": [
        # RU — форумные паттерны
        "эта тактика работает 3 из 5 раз шортс",
        "вот почему этого боятся шортс",
        "схема которую скрывают шортс",
        "лайфхак который реально работает шортс",
        # EN
        "this tactic works every time shorts",
        "secret method they dont want you to know shorts",
        "money hack that actually works shorts",
        # KO
        "숨겨진 돈 버는 전략 shorts",
        "아무도 안 알려주는 방법 shorts",
        # TH
        "เคล็ดลับลับหาเงิน shorts",
        # ID
        "trik rahasia cuan terbukti shorts",
    ],

    # ── Категория 3: Приложение / промокод ────────────────────────────────────
    # Форум-инсайт 2026: промокод в кадре — главный формат без ссылок.
    # "Скачал приложение", "промокод в видео", "бонус в кадре".
    "new_app": [
        # RU — промокод-формат (главный тренд 2026)
        "промокод бонус в видео шортс",
        "это приложение легально платит шортс",
        "скачал приложение результат шокировал шортс",
        "приложение дало бонус шортс",
        # EN
        "promo code bonus in video shorts",
        "app that actually pays no joke shorts",
        "downloaded app shocking result shorts",
        # KO
        "앱 다운로드 결과 충격 shorts",
        "이 앱 진짜 돈 나옴 shorts",
        # TH
        "แอปให้โบนัส shorts ได้จริง",
        # ID
        "aplikasi bonus terbukti shorts",
    ],

    # ── Категория 4: Мультипликатор ───────────────────────────────────────────
    # x47, x100 — без называния игры. Маска: экран с цифрой + шок-фейс.
    "multiplier": [
        # RU
        "поставил 1000 получил шортс реакция",
        "умножил деньги за минуту шортс",
        "x100 реальная реакция шортс",
        "в 100 раз больше за 5 минут шортс",
        # EN
        "x100 real reaction shorts",
        "turned 100 into 10000 reaction shorts",
        "multiplied money insane reaction shorts",
        # KO
        "100배 수익 반응 shorts",
        "배팅 소액 대박 shorts",
        # TH
        "x100 ใน 1 นาที ตกใจมาก shorts",
        # ID
        "x100 dalam 1 menit reaksi shorts",
    ],

    # ── Категория 5: Лайфстайл / нейтральный аккаунт ─────────────────────────
    # Форум-инсайт 2026: аккаунт создаётся на нейтральной теме — мотивация,
    # нарезки фильмов, факты — гемблинг-контент вкрапляется незаметно.
    "lifestyle": [
        # RU — нейтральный лайфстайл / мотивация
        "начал с 1000 рублей история шортс",
        "изменил жизнь за месяц деньги шортс",
        "сколько зарабатываю в день покажу шортс",
        "мой пассивный доход 2026 шортс",
        # EN
        "started with 100 dollars story shorts",
        "changed my life with money shorts",
        "how much i make per day reveal shorts",
        # KO
        "한달에 얼마 버나 공개 shorts",
        "삶이 바뀐 수익 이야기 shorts",
        # TH
        "เริ่มต้นจาก 1000 บาท ชีวิตเปลี่ยน shorts",
        # ID
        "mulai dari nol sekarang cuan shorts",
    ],

    # ── Категория 6: Срочность / FOMO ─────────────────────────────────────────
    # «Это скоро закроют / удалят» — создаёт FOMO без называния продукта.
    "urgency": [
        # RU
        "успей пока не закрыли шортс",
        "это скоро удалят смотри шортс",
        "работает только сегодня шортс",
        "пока не заблокировали смотри шортс",
        # EN
        "hurry before they remove this shorts",
        "watch before deleted shorts",
        "works only today grab now shorts",
        # KO
        "곧 사라질 방법 보세요 shorts",
        "지금 아니면 늦어 shorts",
        # TH
        "รีบดูก่อนโดนลบ shorts",
        # ID
        "segera sebelum dihapus shorts",
    ],

    # ── Категория 7: Вывод / скрин ────────────────────────────────────────────
    # Форум-инсайт 2026: скриншот транзакции + «начал с 1000» = главное
    # доказательство без называния источника.
    "withdrawal_proof": [
        # RU
        "вывел деньги скрин шортс",
        "начал с 1000 рублей вывод шортс",
        "доказательство выплаты реально шортс",
        "скриншот транзакции шортс",
        # EN
        "proof of payout real shorts",
        "started 100 dollars withdrawal proof shorts",
        "showing my cashout screenshot shorts",
        # KO
        "출금 인증 실제 shorts",
        "출금 스크린샷 공개 shorts",
        # TH
        "หลักฐานการถอนเงินจริง shorts",
        # ID
        "bukti withdraw nyata shorts",
    ],

    # ── Категория 8: Экран телефона / POV ─────────────────────────────────────
    # «Смотри что у меня на экране» — POV-формат, UI без называния продукта.
    "phone_screen": [
        # RU
        "показываю экран телефона заработок шортс",
        "смотри что у меня на телефоне шортс",
        "телефон приносит деньги шортс",
        "повтори за мной экран шортс",
        # EN
        "pov my phone making money shorts",
        "showing phone screen earnings shorts",
        "watch my phone screen income shorts",
        # KO
        "폰 화면 수익 보여줄게 shorts",
        "핸드폰으로 돈 버는 법 shorts",
        # TH
        "แสดงหน้าจอโทรศัพท์รายได้ shorts",
        # ID
        "lihat layar hp penghasil uang shorts",
    ],

    # ── 2026: Категория 9 — Telegram-воронка ──────────────────────────────────
    # Арбитражники убрали прямые ссылки → гонят в Telegram-бот/канал.
    # В видео: «всё в тг», QR на Telegram, «напиши мне».
    "telegram_funnel": [
        # RU
        "телеграм ссылка в шапке шортс",
        "пиши в тг получи бонус шортс",
        "тг бот бонус игра шортс",
        "телеграм канал заработок шортс",
        # EN
        "telegram link in bio bonus shorts",
        "dm me for game link shorts",
        "join telegram for bonus code shorts",
        "telegram bot casino bonus shorts",
        # KO
        "텔레그램 링크 보너스 shorts",
        "텔레그램 채널 게임 shorts",
        # TH
        "telegram ลิงก์โบนัส shorts",
        # ID
        "telegram link bonus game shorts",
    ],

    # ── 2026: Категория 10 — QR-код прямо в кадре ─────────────────────────────
    # Новая техника 2026: QR-код в субтитрах/оверлее — YouTube не видит URL.
    "qr_code_mask": [
        # RU
        "отсканируй qr получи бонус шортс",
        "qr код в видео регистрация шортс",
        "сканируй код бонус игра шортс",
        # EN
        "scan qr code bonus register shorts",
        "qr code in video get bonus shorts",
        "scan to get free bonus shorts",
        # KO
        "qr 코드 스캔 보너스 shorts",
        "영상 속 qr 코드 게임 shorts",
        # TH
        "สแกน qr รับโบนัส shorts",
    ],

    # ── 2026: Категория 11 — Челлендж / Day-N серия ───────────────────────────
    # «День 1 / День 30 испытания» без называния игры. Серийность = подписчики.
    "challenge_format": [
        # RU
        "день 1 испытание заработок шортс",
        "30 дней с этим приложением шортс",
        "день 7 результат показываю шортс",
        "начал с нуля день 1 шортс",
        # EN
        "day 1 challenge app earnings shorts",
        "30 day challenge making money shorts",
        "day 7 results this app shorts",
        "started from zero day one shorts",
        # KO
        "1일차 챌린지 수익 shorts",
        "30일 이 앱으로 shorts",
        # TH
        "วันที่ 1 ทดลองทำเงิน shorts",
        # ID
        "hari 1 challenge penghasilan shorts",
    ],

    # ── 2026: Категория 12 — AI-лайфхак-маскировка ────────────────────────────
    # «AI подобрал стратегию», «ChatGPT нашёл способ» — хайп на AI для маскировки.
    "ai_hack": [
        # RU
        "ai нашёл стратегию выигрыша шортс",
        "chatgpt дал метод заработка шортс",
        "искусственный интеллект выиграл шортс",
        "нейросеть предсказала победу шортс",
        # EN
        "ai found winning strategy shorts",
        "chatgpt helped me win shorts",
        "ai prediction big win shorts",
        "used ai to beat the game shorts",
        # KO
        "ai 전략으로 대박 났어 shorts",
        "챗gpt 게임 전략 대박 shorts",
        # TH
        "ai หาวิธีชนะ shorts",
    ],

    # ── 2026: Категория 13 — Псевдообучение (туториал-маска) ──────────────────
    # Ролик выглядит как обучение игре/инвестиции, но в описании — оффер.
    "tutorial_mask": [
        # RU
        "как работает эта игра покажу шортс",
        "объясняю стратегию выигрыша шортс",
        "разбор как выигрывать стабильно шортс",
        "гайд по игре заработок шортс",
        # EN
        "how this game actually works shorts",
        "tutorial how to win consistently shorts",
        "explaining my winning strategy shorts",
        "guide make money this game shorts",
        # KO
        "이 게임 하는 법 알려줄게 shorts",
        "전략 설명 대박 나는 법 shorts",
        # TH
        "วิธีเล่นเกมนี้ให้ได้เงิน shorts",
        # ID
        "tutorial cara menang game ini shorts",
    ],
}

# ── Stealth title / description intent signals ────────────────────────────────
# Слова в заголовке / описании без прямых названий игр или казино.
# Это то, что реально написано в замаскированных роликах.

STEALTH_TITLE_SIGNALS: dict[str, tuple[str, ...]] = {
    "money_urgency": (
        # RU
        "заработал за", "сделал за", "поднял за", "получил за",
        "мой доход", "мой заработок", "сколько я заработал", "сколько я сделал",
        "пассивный доход", "без вложений",
        # EN
        "earned in", "made in", "profit in", "my income", "my earnings", "i made",
        # KO
        "수입", "벌었어", "수익",
        # TH
        "รายได้", "หาเงินได้",
    ),
    "mystery_hook": (
        # RU
        "секрет", "скрывают", "не знают", "только для", "не расскажут",
        "метод", "способ", "схема", "лайфхак", "никто не скажет",
        # EN
        "secret", "method", "hack", "they dont want", "hidden",
        "revealed", "nobody tells", "they hide",
        # KO
        "비밀", "숨겨진", "비법",
        # TH
        "วิธีลับ", "ความลับ",
        # VI
        "bi mat", "phuong phap",
    ),
    "urgency_words": (
        # RU
        "успей", "пока не удалили", "пока работает", "только сегодня",
        "осталось мало", "скоро закроют", "пока не заблокировали",
        # EN
        "hurry", "limited time", "before they delete",
        "while it works", "last chance", "act now", "limited",
        # KO
        "곧 사라질", "지금 바로", "곧 막힐",
        # TH
        "รีบก่อน", "วันนี้เท่านั้น",
        # VI
        "lam ngay", "truoc khi bi xoa",
    ),
    "proof_words": (
        # RU
        "доказательство", "скрин", "вывод", "скриншот", "реальный вывод",
        "я вывел", "показываю вывод",
        # EN
        "proof", "withdrawal", "payment proof", "screenshot",
        "real money", "legit", "verified", "cashout proof",
        # KO
        "출금", "인증", "증거",
        # TH
        "หลักฐาน", "สกรีนช็อต",
        # VI
        "bang chung", "rut tien",
    ),
    "reaction_words": (
        # RU
        "шок", "шокирован", "не мог поверить", "реакция", "не верил",
        # EN
        "shocked", "unbelievable", "reaction", "cant believe", "omg",
        # KO
        "믿을 수 없어", "충격", "반응",
        # TH
        "ตกใจ", "ไม่น่าเชื่อ",
    ),
    "app_words": (
        # RU
        "приложение", "апп", "скачай", "установи", "нашёл приложение",
        # EN
        "app", "download", "install", "application", "found app",
        # KO
        "앱", "다운로드", "어플",
        # TH
        "แอป", "ดาวน์โหลด",
        # VI
        "ung dung", "tai ve",
    ),
    # ── 2026 new signals ──────────────────────────────────────────────────────
    "telegram_words": (
        # RU
        "телеграм", "тг", "tg", "telegram",
        # EN
        "telegram", "tg link", "dm me", "message me",
        # KO
        "텔레그램", "tg 링크", "디엠",
        # TH
        "เทเลแกรม",
        # ID
        "telegram", "dm saya",
    ),
    "qr_words": (
        "qr", "qr код", "qr code", "scan", "сканируй", "скан",
        "qr 코드", "สแกน qr",
    ),
    "challenge_words": (
        # RU
        "день 1", "день 7", "день 30", "испытание", "челлендж",
        "начал с нуля", "каждый день",
        # EN
        "day 1", "day 7", "day 30", "challenge", "started from zero",
        "every day", "daily challenge",
        # KO
        "1일차", "7일차", "30일", "챌린지",
        # TH
        "วันที่ 1", "วันที่ 30", "ทดลอง",
    ),
    "ai_words": (
        # RU
        "ai", "нейросеть", "chatgpt", "искусственный интеллект", "предсказал",
        # EN
        "ai", "chatgpt", "neural", "ai prediction", "ai strategy",
        # KO
        "ai", "인공지능", "챗gpt",
        # TH
        "ai", "ปัญญาประดิษฐ์",
    ),
    "nameless_game": (
        # RU — говорит «это» без называния
        "это приложение", "эта игра", "такой способ", "нашёл это",
        "название в профиле", "игра без названия",
        # EN
        "this app", "this game", "found this", "game name in bio",
        "no name just results", "this thing actually works",
        # KO
        "이 앱", "이 게임", "이름은 프로필에",
        # TH
        "แอปนี้", "เกมนี้",
    ),
}


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


# ── UBT seed queries (холодная аудитория, примитивные крючки, Shorts) ───────
# Не названия игр — широкие теги + формат. Комбинации отдаются в ytsearch…

UBT_SEED_BROAD_TAGS: tuple[str, ...] = (
    "#баг",
    "#темка",
    "#заработок",
    "#проверка",
    "#честно",
    "#реакция",
    "#секрет",
    "#способ",
    "#сплит",
    "#развод",
    "темка",
    "проверка баг",
    "честная темка",
)

UBT_SEED_FORMAT_TOKENS: tuple[str, ...] = (
    "shorts",
    "#shorts",
    "#шортс",
    "шортс",
    "#Shorts",
)


def generate_search_seeds(
    *,
    extra_broad_tags: tuple[str, ...] | None = None,
    max_seeds: int = 36,
) -> list[str]:
    """
    Стартовые запросы для yt-dlp: [широкий тег] + [формат Shorts].
    Дубликаты убираются, порядок стабильный.
    """
    tags = list(extra_broad_tags) if extra_broad_tags else list(UBT_SEED_BROAD_TAGS)
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        t = str(tag or "").strip()
        if not t:
            continue
        for fmt in UBT_SEED_FORMAT_TOKENS:
            q = f"{t} {fmt}".strip()
            if q not in seen:
                seen.add(q)
                out.append(q)
        q2 = f"{t} #shorts".strip()
        if q2 not in seen:
            seen.add(q2)
            out.append(q2)
    return out[: max(1, int(max_seeds))]


def _video_upload_datetime(video: dict[str, Any]) -> datetime | None:
    """Разбор upload_date: ISO (API), YYYY-MM-DD… (нормализация), YYYYMMDD (yt-dlp)."""
    raw = video.get("upload_date")
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if "T" in s:
        try:
            ss = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ss)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                12,
                0,
                0,
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    digits = re.sub(r"\D", "", s)[:8]
    if len(digits) == 8 and digits.isdigit():
        try:
            return datetime(
                int(digits[:4]),
                int(digits[4:6]),
                int(digits[6:8]),
                12,
                0,
                0,
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    return None


def filter_videos_by_upload_recency(
    videos: list[dict[str, Any]],
    *,
    max_age_hours: float = 48.0,
    min_age_hours: float = 0.0,
    drop_if_unknown_date: bool = True,
) -> list[dict[str, Any]]:
    """
    Оставить ролики, загруженные в окне [now - max_age_hours, now - min_age_hours].
    Для UBT-арбитража: «свежак» 24–48 ч → выставьте max_age_hours=48 (и при нужде min_age_hours=24).
    """
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for v in videos:
        dt = _video_upload_datetime(v)
        if dt is None:
            if not drop_if_unknown_date:
                out.append(v)
            continue
        age_h = (now - dt).total_seconds() / 3600.0
        if age_h < float(min_age_hours) or age_h > float(max_age_hours):
            continue
        out.append(v)
    return out


def _effective_recent_max_hours(
    shorts_only: bool,
    recent_max_hours: float | None,
) -> float | None:
    """Приоритет: явный аргумент → NEORENDER_SEARCH_RECENT_HOURS → для Shorts дефолт 48 ч."""
    if recent_max_hours is not None:
        return recent_max_hours if recent_max_hours > 0 else None
    env_raw = (os.environ.get("NEORENDER_SEARCH_RECENT_HOURS") or "").strip()
    if env_raw:
        try:
            v = float(env_raw)
            return v if v > 0 else None
        except ValueError:
            pass
    return 48.0 if shorts_only else None


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
    """Heuristic relevance score for arbitrage-style uploads (0..100).

    Checks title + description + tags (not just title).
    """
    title    = str(video.get("title") or "").lower()
    desc     = str(video.get("description") or "").lower()
    channel  = str(video.get("channel") or "").lower()
    tags_raw = video.get("tags") or []
    tags     = " ".join(str(t) for t in tags_raw).lower() if tags_raw else ""
    full_text = f"{title}\n{desc}\n{tags}"

    views    = int(video.get("view_count") or 0)
    duration = int(video.get("duration") or 0)
    score = 0

    # Duration: Shorts ≤60 s = strong signal
    if 0 < duration <= 60:
        score += 25
    elif duration > 120:
        score -= 8

    # Query pattern hits (check full_text, not just title)
    query_hits = 0
    for q in game_queries:
        qn = str(q or "").strip().lower()
        if not qn:
            continue
        tokens = [t for t in qn.split() if len(t) >= 4]
        if any(t in full_text for t in tokens):
            query_hits += 1
    score += min(28, query_hits * 4)

    # Arbitrage keyword hits in title (highest weight) and desc (lower weight)
    kw_title = sum(1 for kw in ARBITRAGE_STYLE_KEYWORDS if kw in title)
    kw_desc  = sum(1 for kw in ARBITRAGE_STYLE_KEYWORDS if kw in desc)
    score += min(24, kw_title * 6)
    score += min(12, kw_desc * 3)

    # UBT masking phrases in description / channel name
    mask_hits = sum(1 for p in UBT_MASKING_PATTERNS if p in full_text)
    score += min(20, mask_hits * 8)

    # Link shortener found in text
    if _detect_link_shorteners(full_text):
        score += 14

    # View count: popular arb content clusters at 100K–10M
    if views >= 5_000_000:
        score += 10
    elif views >= 1_000_000:
        score += 8
    elif views >= 100_000:
        score += 5
    elif views >= 10_000:
        score += 2

    # Game name presence in title
    game_hint = game_key.replace("_", " ")
    if any(tok in title for tok in game_hint.split() if len(tok) >= 4):
        score += 8

    # Negative signals
    if "official" in channel or "official" in title:
        score -= 8
    if "tutorial" in title or "review" in title or "обзор" in title:
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

# ── Scan result TTL cache ──────────────────────────────────────────────────────
# Хранит результаты scan_arbitrage_videos / scan_stealth_videos на 10 минут.
# Ключ = хэш параметров; значение = (timestamp, result).
import time as _time_module
_SCAN_CACHE: dict[str, tuple[float, Any]] = {}
_SCAN_TTL = 600  # seconds


def _scan_cache_key(**kwargs: Any) -> str:
    import hashlib
    raw = json.dumps(kwargs, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def _scan_cache_get(key: str) -> Any | None:
    entry = _SCAN_CACHE.get(key)
    if entry and (_time_module.monotonic() - entry[0]) < _SCAN_TTL:
        return entry[1]
    _SCAN_CACHE.pop(key, None)
    return None


def _scan_cache_set(key: str, value: Any) -> None:
    # Evict stale entries to bound memory (keep last 50 entries)
    if len(_SCAN_CACHE) >= 50:
        oldest = min(_SCAN_CACHE, key=lambda k: _SCAN_CACHE[k][0])
        _SCAN_CACHE.pop(oldest, None)
    _SCAN_CACHE[key] = (_time_module.monotonic(), value)


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
    """Преобразовать один JSON-объект yt-dlp в карточку видео.

    Включает description, tags и channel_follower_count чтобы enrich_video_risk
    имел полные данные для скоринга (ранее эти поля терялись).
    """
    if not isinstance(entry, dict):
        return None
    vid = str(entry.get("id") or entry.get("display_id") or "").strip()
    if not vid:
        return None
    raw_url = str(entry.get("webpage_url") or entry.get("url") or "")
    video_url = _to_youtube_shorts_url(raw_url, vid) if source == "youtube" else raw_url

    # tags: yt-dlp returns list of str
    raw_tags = entry.get("tags")
    tags: list[str] = [str(t) for t in raw_tags if t] if isinstance(raw_tags, list) else []

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
        # Enrichment fields — used by enrich_video_risk / _score_stealth_signals
        "description": str(entry.get("description") or "").strip(),
        "tags": tags,
        "channel_follower_count": int(
            entry.get("channel_follower_count")
            or entry.get("uploader_follower_count")
            or 0
        ),
        "source": source,
        # Аудио-трек (если yt-dlp вернул — для trending audio детектора)
        "track": str(entry.get("track") or "").strip(),
        "artist": str(entry.get("artist") or entry.get("creator") or "").strip(),
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
    use_ubt_seed_queries: bool = True,
    recent_max_hours: float | None = None,
) -> list[dict[str, Any]]:
    """
    Returns a list of video dicts sorted by view_count desc:
    {id, title, url, thumbnail, duration, view_count, like_count,
     comment_count, upload_date, channel, channel_url, source}

    region=None / пустой / GLOBAL — без regionCode в YouTube API (широкая выдача).
    shorts_only — после поиска оставить только ролики 1…shorts_max_duration сек (Shorts).
    fetch_multiplier — сколько кандидатов запросить до фильтра Shorts (для арбитраж-скана).
    use_ubt_seed_queries — комбинированные теги Shorts (generate_search_seeds) в yt-dlp пути.
    recent_max_hours — отсечь ролики старше N часов по upload_date (для UBT обычно 48; None = см. env / Shorts).
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
            rh_api = _effective_recent_max_hours(shorts_only, recent_max_hours)
            if rh_api is not None:
                yt = filter_videos_by_upload_recency(yt, max_age_hours=rh_api, drop_if_unknown_date=True)
            return _dedup_and_sort(yt, want)
    if not _ytdlp_available():
        raise RuntimeError("yt-dlp не установлен или недоступен в PATH")

    ytdlp_cmd = _yt_dlp_cmd()
    if not ytdlp_cmd:
        raise RuntimeError("yt-dlp недоступен")
    raw_niche = (niche or "").strip()
    # scan_mode: fetch_multiplier > 1 signals a regular search; for scans we
    # pass fetch_multiplier=1 which means we only try the first URL variant
    # (avoids 3× timeout cascade when YouTube is rate-limiting yt-dlp).
    scan_mode = (fetch_multiplier == 1)
    ubt_seeds = generate_search_seeds() if use_ubt_seed_queries else []
    if source == "youtube":
        if use_ubt_seed_queries and ubt_seeds:
            if not raw_niche:
                if scan_mode:
                    urls_try = [f"ytsearch{fetch_n}:{q}" for q in ubt_seeds[:6]]
                else:
                    urls_try = [f"ytsearch{fetch_n}:{q}" for q in ubt_seeds[:12]]
            elif scan_mode:
                urls_try = [f"ytsearch{fetch_n}:{raw_niche} shorts"]
                urls_try += [f"ytsearch{fetch_n}:{q}" for q in ubt_seeds[:4]]
            else:
                urls_try = [
                    f"ytsearch{fetch_n}:{raw_niche} shorts",
                    f"ytsearch{fetch_n}:{raw_niche} #shorts",
                    f"ytsearch{fetch_n}:{raw_niche}",
                ]
                urls_try += [f"ytsearch{fetch_n}:{q}" for q in ubt_seeds[:10]]
        elif not raw_niche:
            urls_try = [f"ytsearch{fetch_n}:shorts"]
        elif scan_mode:
            # Fast path: single query variant + lower timeout
            urls_try = [f"ytsearch{fetch_n}:{raw_niche} shorts"]
        else:
            urls_try = [
                f"ytsearch{fetch_n}:{raw_niche} shorts",
                f"ytsearch{fetch_n}:{raw_niche} #shorts",
                f"ytsearch{fetch_n}:{raw_niche}",
            ]
    else:
        urls_try = [f"ytsearch{fetch_n}:{raw_niche or niche}"]

    ytdlp_timeout = 25.0 if scan_mode else 90.0

    merged: list[dict[str, Any]] = []
    try:
        for url in urls_try:
            try:
                batch = await _yt_dlp_search(ytdlp_cmd, url, source, full_meta=True, timeout_sec=ytdlp_timeout)
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
    rh = _effective_recent_max_hours(shorts_only, recent_max_hours)
    if rh is not None and source == "youtube":
        before_n = len(merged)
        merged = filter_videos_by_upload_recency(merged, max_age_hours=rh, drop_if_unknown_date=False)
        if before_n and not merged:
            logger.warning(
                "search_videos: после фильтра свежести (≤%.0f ч) не осталось роликов с известной датой (было %d)",
                rh,
                before_n,
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
                # snippet добавлен чтобы получить description + tags — нужно для UBT-скоринга
                v_params = {
                    "key": api_key,
                    "part": "snippet,statistics,contentDetails",
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

    def _best_thumbnail(thumbs: dict) -> str:
        for quality in ("maxres", "standard", "high", "medium", "default"):
            url = (thumbs.get(quality) or {}).get("url", "")
            if url:
                return str(url)
        return ""

    out: list[dict[str, Any]] = []
    for item in items:
        search_snippet = item.get("snippet", {}) if isinstance(item, dict) else {}
        vid = _youtube_item_video_id(item) if isinstance(item, dict) else ""
        if not vid:
            continue
        vi = stats_map.get(vid, {})
        # videos.list also returns snippet (with description + tags + thumbnails)
        full_snippet    = vi.get("snippet", {}) if isinstance(vi, dict) else {}
        statistics      = vi.get("statistics", {}) if isinstance(vi, dict) else {}
        content_details = vi.get("contentDetails", {}) if isinstance(vi, dict) else {}

        # Prefer full snippet (from videos.list) over search snippet (no description)
        best_snippet = full_snippet if full_snippet else search_snippet
        channel_id   = str(best_snippet.get("channelId") or search_snippet.get("channelId") or "")

        # tags from videos.list snippet
        raw_tags = full_snippet.get("tags") or []
        tags: list[str] = [str(t) for t in raw_tags if t] if isinstance(raw_tags, list) else []

        out.append(
            {
                "id": vid,
                "title": str(best_snippet.get("title") or ""),
                "url": f"https://www.youtube.com/shorts/{vid}",
                "thumbnail": _best_thumbnail(best_snippet.get("thumbnails") or {}),
                "duration": _parse_iso_duration(str(content_details.get("duration") or "")),
                "view_count": int(statistics.get("viewCount", 0) or 0),
                "like_count": int(statistics.get("likeCount", 0) or 0),
                "comment_count": int(statistics.get("commentCount", 0) or 0),
                "upload_date": str(best_snippet.get("publishedAt") or ""),
                "channel": str(best_snippet.get("channelTitle") or ""),
                "channel_url": f"https://www.youtube.com/channel/{channel_id}" if channel_id else "",
                # Enrichment fields (aligned with _parse_entry)
                "description": str(full_snippet.get("description") or "").strip(),
                "tags": tags,
                "channel_follower_count": 0,   # not available from search API
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

    v2 (2026):
    - Все игры сканируются параллельно (не последовательно) через общий семафор.
    - Результаты кэшируются на 10 минут (TTL cache).
    - Кросс-игровая дедупликация: одно видео попадает только в игру с наибольшим
      arb_score (убирает дубли между похожими crash-играми).
    - Скоринг через enrich_video_risk (единый механизм со scan_stealth_videos).

    Returns: {game_key: [video, …], …}
    """
    target_games = games or list(ARBITRAGE_GAME_PATTERNS.keys())
    reg = None if _is_global_region(region) else (str(region or "").strip().upper() or None)
    watchlist_norm = _normalize_watchlist_entries(watchlist_channels)

    # TTL cache check
    cache_key = _scan_cache_key(
        fn="arb", games=sorted(target_games), region=reg,
        period_days=period_days, limit_per_query=limit_per_query,
        shorts_only=shorts_only,
    )
    cached = _scan_cache_get(cache_key)
    if cached is not None:
        logger.debug("scan_arbitrage_videos: cache hit")
        return cached

    # Semaphore: limit concurrent yt-dlp subprocesses
    sem = asyncio.Semaphore(8)
    # Top queries per game (keep scan time bounded)
    MAX_Q_PER_GAME = 6

    async def _one_query(q: str, game_key: str) -> list[dict[str, Any]]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    search_videos(
                        niche=q, source="youtube",
                        period_days=period_days, limit=limit_per_query,
                        region=reg, shorts_only=shorts_only,
                        fetch_multiplier=fetch_multiplier,
                    ),
                    timeout=30.0,
                )
            except Exception as exc:
                logger.debug("arb scan %s %r: %s", game_key, q[:50], exc)
                return []

    async def _one_game(game_key: str) -> tuple[str, list[dict[str, Any]]]:
        patterns = (ARBITRAGE_GAME_PATTERNS.get(game_key) or [])[:MAX_Q_PER_GAME]
        if not patterns:
            return game_key, []
        batches = await asyncio.gather(*[_one_query(q, game_key) for q in patterns])
        seen: dict[str, dict[str, Any]] = {}
        for batch in batches:
            for video in batch:
                vid_key = str(video.get("id") or video.get("url") or "")
                if not vid_key:
                    continue
                wl_match = _watchlist_match(video, watchlist_norm)
                # Use unified risk scorer for consistent scores across both scan types
                enriched = enrich_video_risk(video, query_patterns=patterns, watchlist_hit=bool(wl_match))
                arb_score = enriched.get("risk_score", 0)
                if vid_key not in seen or arb_score > (seen[vid_key].get("arb_score") or 0):
                    seen[vid_key] = {
                        **enriched,
                        "game": game_key,
                        "game_label": ARBITRAGE_GAME_LABELS.get(game_key, game_key),
                        "arb_score": arb_score,
                        "watchlist_hit": bool(wl_match),
                        "watchlist_match": wl_match or "",
                    }
        sorted_results = sorted(
            seen.values(),
            key=lambda v: (
                int(v.get("watchlist_hit") is True),
                int(v.get("arb_score") or 0),
                int(v.get("view_count") or 0),
            ),
            reverse=True,
        )[:limit_per_query * 3]
        return game_key, sorted_results

    # Run ALL games in parallel (bounded by semaphore + 180 s overall cap)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_one_game(k) for k in target_games], return_exceptions=True),
            timeout=180.0,
        )
    except asyncio.TimeoutError:
        logger.warning("scan_arbitrage_videos: 180 s timeout — returning partial results")
        results = []

    output: dict[str, list[dict[str, Any]]] = {k: [] for k in target_games}
    # Cross-game dedup: each video ID goes only to the game with the highest arb_score
    global_seen: dict[str, str] = {}   # vid_id → game_key with best score
    all_game_results: dict[str, dict[str, dict[str, Any]]] = {}
    for item in results:
        if isinstance(item, BaseException):
            logger.debug("arb scan game error: %s", item)
            continue
        game_key, game_vids = item
        all_game_results[game_key] = {}
        for v in game_vids:
            vid_id = str(v.get("id") or "")
            if not vid_id:
                continue
            score = int(v.get("arb_score") or 0)
            if vid_id not in global_seen:
                global_seen[vid_id] = game_key
            else:
                prev_game = global_seen[vid_id]
                prev_score = int(
                    all_game_results.get(prev_game, {}).get(vid_id, {}).get("arb_score") or 0
                )
                if score > prev_score:
                    # Move to better-scoring game
                    all_game_results.get(prev_game, {}).pop(vid_id, None)
                    global_seen[vid_id] = game_key
                else:
                    continue  # skip — already claimed by a better-scoring game
            all_game_results[game_key][vid_id] = v

    for game_key, vid_map in all_game_results.items():
        output[game_key] = sorted(
            vid_map.values(),
            key=lambda v: (
                int(v.get("watchlist_hit") is True),
                int(v.get("arb_score") or 0),
                int(v.get("view_count") or 0),
            ),
            reverse=True,
        )[:limit_per_query * 3]

    _scan_cache_set(cache_key, output)
    return output


async def scan_stealth_videos(
    categories: list[str] | None = None,
    region: str | None = None,
    period_days: int = 7,
    limit_per_query: int = 4,
    *,
    shorts_only: bool = True,
    fetch_multiplier: int = 5,
    watchlist_channels: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    2026 UBT stealth scan — finds arbitrage videos that DON'T mention game
    or casino names in the title (YouTube would block them).

    Instead searches by behavioral patterns: shock-reaction, secret-method,
    new-app, multiplier, lifestyle, urgency, withdrawal-proof, phone-screen.

    Each result is enriched with stealth behavioral score + UBT flags.

    Performance notes:
    - All categories run concurrently (not sequentially).
    - A semaphore (max 6 concurrent yt-dlp processes) prevents overload.
    - Only top 4 queries per category are used to keep runtime bounded.
    - Each yt-dlp call has a hard 25 s timeout (scan mode).
    - The whole scan is capped at 120 s with asyncio.wait_for.

    Returns: {category_key: [video, ...], ...}

    v2 (2026):
    - 13 categories including Telegram funnel, QR masking, Challenge format,
      AI hack and Tutorial masking.
    - Language-aware query rotation: queries are re-sorted to prioritise the
      target region's language so cap of 4 per category covers the right market.
    - TTL cache (10 min) to avoid redundant yt-dlp runs on repeated scans.
    """
    # TTL cache check
    target_cats = categories or list(STEALTH_SCAN_PATTERNS.keys())
    reg = None if _is_global_region(region) else (str(region or "").strip().upper() or None)

    cache_key = _scan_cache_key(
        fn="stealth", cats=sorted(target_cats), region=reg,
        period_days=period_days, limit_per_query=limit_per_query,
        shorts_only=shorts_only,
    )
    cached = _scan_cache_get(cache_key)
    if cached is not None:
        logger.debug("scan_stealth_videos: cache hit")
        return cached

    sem = asyncio.Semaphore(6)
    watchlist_norm = _normalize_watchlist_entries(watchlist_channels)
    effective_multiplier = 1
    MAX_QUERIES_PER_CAT = 4

    # Language priority map: region → preferred lang markers in query strings
    _LANG_PRIORITY: dict[str, tuple[str, ...]] = {
        "KR": ("shorts", "ko", "한국", "대박", "шортс"),
        "TH": ("shorts", "th", "โบนัส", "ได้เงิน", "ko"),
        "VN": ("shorts", "vi", "đăng ký", "kiếm tiền", "en"),
        "ID": ("shorts", "id", "penghasilan", "menang", "en"),
        "RU": ("шортс", "ru", "шок", "выигрыш", "shorts"),
        "JP": ("shorts", "ja", "稼げる", "en"),
    }

    def _prioritize_queries(queries: list[str], top_n: int) -> list[str]:
        """Re-sort queries to put the region-relevant language first."""
        if reg is None:
            return queries[:top_n]
        markers = _LANG_PRIORITY.get(reg, ("shorts", "en"))
        def _priority(q: str) -> int:
            ql = q.lower()
            for i, m in enumerate(markers):
                if m in ql:
                    return i
            return len(markers)
        return sorted(queries, key=_priority)[:top_n]

    async def _run_one_query(q: str) -> list[dict[str, Any]]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    search_videos(
                        niche=q,
                        source="youtube",
                        period_days=period_days,
                        limit=limit_per_query,
                        region=reg,
                        shorts_only=shorts_only,
                        fetch_multiplier=effective_multiplier,
                    ),
                    timeout=25.0,
                )
            except (asyncio.TimeoutError, Exception) as exc:
                logger.debug("stealth scan query %r error: %s", q[:60], exc)
                return []

    async def _run_one_category(cat_key: str) -> tuple[str, list[dict[str, Any]]]:
        all_queries = STEALTH_SCAN_PATTERNS.get(cat_key) or []
        queries = _prioritize_queries(all_queries, MAX_QUERIES_PER_CAT)
        if not queries:
            return cat_key, []
        batches = await asyncio.gather(*[_run_one_query(q) for q in queries])
        seen: dict[str, dict[str, Any]] = {}
        for batch in batches:
            for video in batch:
                vid_key = str(video.get("id") or video.get("url") or "")
                if not vid_key:
                    continue
                if vid_key not in seen or (video.get("view_count") or 0) > (seen[vid_key].get("view_count") or 0):
                    wl_match = _watchlist_match(video, watchlist_norm)
                    enriched = enrich_video_risk(video, watchlist_hit=bool(wl_match))
                    enriched["category"] = cat_key
                    enriched["category_label"] = STEALTH_CATEGORY_LABELS.get(cat_key, cat_key)
                    enriched["arb_score"] = enriched.get("risk_score", 0)
                    enriched["watchlist_hit"] = bool(wl_match)
                    enriched["watchlist_match"] = wl_match or ""
                    seen[vid_key] = enriched
        sorted_results = sorted(
            seen.values(),
            key=lambda v: (
                int(v.get("watchlist_hit") is True),
                int(v.get("risk_score") or 0),
                int(v.get("view_count") or 0),
            ),
            reverse=True,
        )[:limit_per_query * 4]
        return cat_key, sorted_results

    try:
        cat_results = await asyncio.wait_for(
            asyncio.gather(*[_run_one_category(k) for k in target_cats], return_exceptions=True),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.warning("scan_stealth_videos: 120 s overall timeout — returning partial results")
        cat_results = []

    output: dict[str, list[dict[str, Any]]] = {k: [] for k in target_cats}
    for item in cat_results:
        if isinstance(item, BaseException):
            logger.debug("stealth scan category error: %s", item)
            continue
        cat_key, results = item
        output[cat_key] = results

    _scan_cache_set(cache_key, output)
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


def _detect_link_shorteners(text: str) -> list[str]:
    """Return list of link-shortener domains found in text."""
    found = []
    for domain in LINK_SHORTENER_DOMAINS:
        if domain in text:
            found.append(domain)
    return found


def _score_stealth_signals(video: dict[str, Any]) -> tuple[int, list[str]]:
    """
    Detect stealth UBT masking — the 2026 approach where arbitrageurs
    never mention game/casino names in the title.

    Checks:
      - Empty / emoji-only description (strongest signal)
      - 'Подробнее в профиле' / 'ссылка в шапке' in desc or title
      - Title intent keywords (urgency, mystery, proof, multiplier, app)
      - Emoji density in title
      - Multiplier patterns (x47, ×100, etc.)
      - Money amount hooks (50к, 500$)
      - Channel subscriber-to-view anomaly (new channel, viral views)

    Returns (score_delta: int, flags: list[str]).
    """
    import re
    import unicodedata as _ud

    title      = str(video.get("title") or "").lower()
    desc_raw   = str(video.get("description") or "").strip()
    desc       = desc_raw.lower()
    views      = int(video.get("view_count") or 0)
    subs       = int(video.get("channel_follower_count") or 0)

    score: int = 0
    flags: list[str] = []

    # ── 1. Description pattern — strongest stealth signal ────────────────────
    if not desc_raw:
        score += 20
        flags.append("desc:empty")
    else:
        non_emoji = [
            c for c in desc_raw
            if _ud.category(c) not in ("So", "Sm", "Po", "Sk")
            and c not in " \n\t👇🔥💰💸✅🎯🤑💎🏆⬇️👆"
        ]
        if len(non_emoji) < 6 and len(desc_raw) < 40:
            score += 16
            flags.append("desc:emoji_only")
        elif len(desc_raw) < 40:
            score += 8
            flags.append("desc:minimal")

    # ── 2. Explicit profile-link CTA in description / title ──────────────────
    profile_cta_phrases = (
        "в профиле", "в шапке", "жми на ник", "смотри профиль",
        "in bio", "in profile", "check profile", "link in bio",
        "프로필에서", "프로필 링크", "ลิงก์ในโปรไฟล์", "link trong bio",
    )
    for phrase in profile_cta_phrases:
        if phrase in desc or phrase in title:
            score += 18
            flags.append(f"cta:{phrase[:24]}")
            break  # one is enough

    # ── 3. Title stealth intent signals ──────────────────────────────────────
    category_pts = {
        "money_urgency": 10,
        "mystery_hook":  13,
        "urgency_words": 15,
        "proof_words":   12,
        "reaction_words": 8,
        "app_words":      7,
    }
    for cat, patterns in STEALTH_TITLE_SIGNALS.items():
        hits = sum(1 for p in patterns if p in title)
        if hits:
            pts = min(category_pts.get(cat, 8) * hits, 22)
            score += pts
            flags.append(f"title:{cat}:{hits}")

    # ── 4. Emoji density in title ─────────────────────────────────────────────
    emoji_count = sum(
        1 for c in title
        if _ud.category(c) in ("So", "Sm") or 0x1F300 <= ord(c) <= 0x1FAFF
    )
    if emoji_count >= 5:
        score += 14
        flags.append(f"title:emoji_{emoji_count}")
    elif emoji_count >= 3:
        score += 7
        flags.append(f"title:emoji_{emoji_count}")

    # ── 5. Multiplier hook (x47, ×100, 100x, x100) ───────────────────────────
    mult = re.search(r"[x×X]\s*(\d{2,4})|\b(\d{2,4})\s*[xX×]", title)
    if mult:
        score += 17
        flags.append(f"title:mult_{mult.group().strip()}")

    # ── 6. Money amount hook (50к, 500$, 1000 рублей) ────────────────────────
    money = re.search(
        r"(\d[\d\s,\.]*)\s*(к\b|k\b|тыс|тысяч|\$|руб|₽|won|₩|usd|euro|€)",
        title, re.IGNORECASE,
    )
    if money:
        score += 12
        flags.append("title:money_amount")

    # ── 7. Channel subscriber-to-view anomaly ────────────────────────────────
    if subs > 0 and views > 0:
        ratio = views / subs
        if ratio > 300:
            score += 18
            flags.append(f"ch:viral_ratio_{int(ratio)}x")
        elif ratio > 80:
            score += 10
            flags.append("ch:high_ratio")
    # New channel with no/few subs but significant views
    if views > 50_000 and subs < 300:
        score += 14
        flags.append("ch:new_viral")
    elif views > 10_000 and subs < 100:
        score += 8
        flags.append("ch:micro_viral")

    return score, flags


def _classify_offer_niche(text: str) -> str | None:
    """Return primary offer niche or None (kept for backward compat)."""
    niches = _classify_offer_niches(text)
    return niches[0] if niches else None


def _classify_offer_niches(text: str) -> list[str]:
    """Return ALL matching offer niches sorted by hit count descending.

    Multi-niche result (e.g. ['crash', 'casino']) is a stronger arb signal
    than a single niche — the scorer adds +8 for cross-vertical content.
    """
    scored: list[tuple[int, str]] = []
    for niche, patterns in OFFER_NICHE_PATTERNS.items():
        hits = sum(1 for p in patterns if p in text)
        if hits >= 1:
            scored.append((hits, niche))
    scored.sort(reverse=True)
    return [n for _, n in scored]


def enrich_video_risk(
    video: dict[str, Any],
    *,
    query_patterns: list[str] | None = None,
    watchlist_hit: bool = False,
) -> dict[str, Any]:
    """
    Full UBT risk scoring — checks title, description, tags, channel name,
    link-masking CTAs, link shorteners, niche signals, and engagement anomalies.

    Returns original video dict enriched with risk/UBT fields.
    """
    out = dict(video)
    title   = str(video.get("title") or "").lower()
    desc    = str(video.get("description") or "").lower()
    channel = str(video.get("channel") or "").lower()
    tags_raw = video.get("tags") or []
    tags    = " ".join(str(t) for t in tags_raw).lower() if tags_raw else ""
    text    = f"{title}\n{desc}\n{channel}\n{tags}"

    duration = int(video.get("duration") or 0)
    views    = int(video.get("view_count") or 0)
    likes    = int(video.get("like_count") or 0)
    comments = int(video.get("comment_count") or 0)

    signal_map: dict[str, int] = {}

    def _add(signal: str, pts: int) -> None:
        signal_map[signal] = signal_map.get(signal, 0) + pts

    # ── 1. UBT link-masking CTA patterns ────────────────────────────────────
    # Strongest signals — explicit masking phrases
    for phrase in UBT_MASKING_PATTERNS:
        if phrase in text:
            pts = 18 if len(phrase) >= 12 else 12
            _add(f"mask:{phrase[:30]}", pts)

    # ── 2. High-value game / offer keywords ─────────────────────────────────
    high_kw = (
        "x100", "x200", "x500", "x50", "jackpot", "big win", "max win",
        "signal", "predictor", "promo code", "промокод",
        "no deposit bonus", "бездепозитный", "free spin", "фриспины",
        "схема заработка", "легкие деньги", "лёгкие деньги",
        "aviator", "aviatrix", "авиатор",
        "lucky jet", "лаки джет", "spaceman", "спейсмен",
        "plinko", "плинко", "crashgame", "crash game",
        "casino", "казино", "slot", "слоты",
        "1win", "mostbet", "melbet", "pin-up", "pinup", "betandyou",
        "stake", "bc.game",
    )
    for k in high_kw:
        if k in text:
            _add(f"kw:{k}", 12)

    # ── 3. Medium-value signals ──────────────────────────────────────────────
    medium_kw = (
        "cashout", "win", "strategy", "bonus", "gambling",
        "выигрыш", "выиграл", "заработок", "прибыль",
        "hack", "cheat", "trick", "секрет",
    )
    for k in medium_kw:
        if k in text:
            _add(f"kw:{k}", 5)

    # ── 4. Hashtag UBT signals ───────────────────────────────────────────────
    ubt_hashtags = (
        "#casino", "#slots", "#bigwin", "#jackpot", "#freecoins",
        "#bonus", "#freespins", "#crashgame", "#aviator", "#luckyjet",
        "#1win", "#mostbet", "#shorts", "#대박", "#выигрыш",
    )
    for ht in ubt_hashtags:
        if ht in text or ht.lstrip("#") in text:
            _add(f"ht:{ht}", 6)

    # ── 5. Link shortener detection ─────────────────────────────────────────
    shorteners_found = _detect_link_shorteners(text)
    for sd in shorteners_found:
        _add(f"shortener:{sd}", 14)

    # Быстрая проверка: есть ли URL, которые стоит раскрутить (без HTTP)
    try:
        from core.funnel_resolver import has_resolvable_urls as _has_resolvable
        _needs_funnel = _has_resolvable(str(video.get("description") or "") + " " + tags)
    except ImportError:
        _needs_funnel = bool(shorteners_found)

    # ── 6. YouTube Shorts duration signal ───────────────────────────────────
    if 0 < duration <= 60:
        _add("duration:shorts", 8)
    elif duration > 120:
        _add("duration:long", -8)

    # ── 7. Engagement anomaly ────────────────────────────────────────────────
    if views > 0:
        er = (likes + comments) / views * 100
        if er > 15:
            _add("engagement:anomaly_high", 10)
        elif er > 8:
            _add("engagement:high", 5)

    # ── 8. Temporal velocity — key 2026 signal ───────────────────────────────
    # Views per day since upload is a stronger signal than raw view count.
    # A Short with 300K views in 2 days is far more suspicious than 300K in 3 months.
    upload_str = str(video.get("upload_date") or "")
    _velocity_days: int = 0
    if upload_str:
        try:
            from datetime import datetime as _dt, timezone as _tz
            # Supports both ISO 8601 (from API) and YYYY-MM-DD (from yt-dlp normalised)
            _udate = _dt.fromisoformat(upload_str.replace("Z", "+00:00").split("T")[0])
            _udate = _udate.replace(tzinfo=_tz.utc) if _udate.tzinfo is None else _udate
            _velocity_days = max(1, (_dt.now(_tz.utc) - _udate).days)
        except Exception:
            _velocity_days = 0

    if _velocity_days > 0 and views > 0:
        vd = views / _velocity_days          # views per day
        if vd > 500_000:
            _add("velocity:explosive", 20)   # eg 1M views in 2 days
        elif vd > 100_000:
            _add("velocity:very_fast", 14)
        elif vd > 30_000:
            _add("velocity:fast", 8)
        elif vd > 5_000:
            _add("velocity:moderate", 3)
    elif views >= 5_000_000:
        _add("views:viral", 8)               # fallback when no date
    elif views >= 1_000_000:
        _add("views:million", 5)
    elif views >= 100_000:
        _add("views:100k", 3)

    # ── 9. Channel name signals ──────────────────────────────────────────────
    generic_words = ("shorts", "official", "channel", "videos", "clips", "best")
    if not channel or all(w in channel for w in generic_words[:1]):
        _add("channel:generic", 4)
    if "official" in channel or "gaming" in channel.lower():
        _add("channel:branded", -5)

    # ── 10. Telegram / QR / 2026 masking signals ────────────────────────────
    # These patterns are now in UBT_MASKING_PATTERNS but also checked directly
    # for dedicated signal flags (higher weight when telegram is the ONLY CTA).
    tg_phrases = ("telegram", "телеграм", "тг", "tg link", "텔레그램", "เทเลแกรม")
    tg_hits = sum(1 for p in tg_phrases if p in text)
    if tg_hits >= 2:
        _add("cta:telegram_heavy", 18)
    elif tg_hits == 1:
        _add("cta:telegram", 10)

    qr_phrases = ("qr", "scan", "сканируй", "qr 코드", "สแกน")
    if sum(1 for p in qr_phrases if p in text) >= 2:
        _add("cta:qr_code", 15)

    # ── 11. Negative context ─────────────────────────────────────────────────
    if "review" in text or "обзор" in text:
        _add("ctx:review", -10)
    if "no links" in text or "без ссылки" in text or "not sponsored" in text:
        _add("ctx:no_links", -12)
    if "official" in text and ("youtube" in text or "channel" in text):
        _add("ctx:official_channel", -8)

    # ── 12. Watchlist boost ──────────────────────────────────────────────────
    if watchlist_hit:
        _add("watchlist_hit", 20)

    # ── 13. Query pattern match ──────────────────────────────────────────────
    qp = [str(x or "").strip().lower() for x in (query_patterns or []) if str(x or "").strip()]
    if qp:
        q_hits = 0
        for q in qp:
            toks = [t for t in q.split() if len(t) >= 4]
            if any(t in text for t in toks):
                q_hits += 1
        if q_hits:
            _add("query_match", min(16, q_hits * 4))

    # ── Niche classification (multi-niche) ───────────────────────────────────
    niches = _classify_offer_niches(text)   # list, not single string
    niche  = niches[0] if niches else None  # primary niche for compat
    if len(niches) >= 2:
        _add("niche:multi_vertical", 8)     # cross-vertical = strong arb signal

    # ── 14. Stealth behavioral signals (2026 masking style) ──────────────────
    stealth_pts, stealth_flags = _score_stealth_signals(video)
    for sf in stealth_flags:
        _add(f"stealth:{sf}", 0)
    if stealth_pts > 0:
        _add("stealth:behavioral", stealth_pts)

    # ── Final scoring ────────────────────────────────────────────────────────
    raw_score = sum(signal_map.values())
    risk_score = int(max(0, min(100, raw_score)))

    if risk_score >= 65:
        tier = "high"
    elif risk_score >= 35:
        tier = "medium"
    else:
        tier = "low"

    # Confidence weighted by signal strength (not just count)
    weighted_pos = sum(max(0, v) for v in signal_map.values())
    confidence = 0.25 + min(0.70, weighted_pos / 140)
    confidence = float(max(0.0, min(0.98, confidence)))

    out["risk_score"]         = risk_score
    out["risk_tier"]          = tier
    out["risk_confidence"]    = round(confidence, 3)
    out["risk_signals"]       = list(signal_map.keys())
    out["risk_signal_map"]    = signal_map
    out["ubt_mask_score"]     = risk_score
    out["ubt_flags"]          = [k for k in signal_map if signal_map.get(k, 0) >= 10]
    out["ubt_marker"]         = risk_score >= 65
    out["ubt_suspected"]      = risk_score >= 35
    out["ubt_niche"]          = niche
    out["ubt_niches"]         = niches
    out["ubt_shorteners"]      = shorteners_found
    out["ubt_masking_hits"]    = [p for p in UBT_MASKING_PATTERNS if p in text]
    out["upload_velocity_dpd"] = round(views / _velocity_days, 1) if _velocity_days > 0 and views > 0 else None
    out["needs_funnel_resolve"] = _needs_funnel
    return out


async def get_trending_audio(
    niche: str,
    top_n: int = 20,
    region: str | None = "KR",
    *,
    shorts_only: bool = True,
) -> dict[str, Any]:
    """
    Анализирует топ-N Shorts по нише и возвращает рейтинг трендовых аудио-треков.

    YouTube Shorts активно буститет видео на трендовые звуки — реиспользование
    трендового трека увеличивает вероятность попадания в рекомендации.

    Возвращает
    ----------
    {
      "status": "ok",
      "trending": [
        {"track": "...", "artist": "...", "count": N, "example_views": M},
        ...
      ],
      "videos_analyzed": N,
      "niche": "..."
    }
    """
    try:
        videos = await search_videos(
            niche=niche,
            source="youtube",
            period_days=14,
            limit=top_n,
            region=region,
            shorts_only=shorts_only,
            fetch_multiplier=2,
        )
    except Exception as exc:
        logger.warning("get_trending_audio: search failed: %s", exc)
        return {"status": "error", "message": str(exc), "trending": [], "videos_analyzed": 0}

    # Агрегируем треки
    from collections import defaultdict
    track_counts: dict[str, int] = defaultdict(int)
    track_artists: dict[str, str] = {}
    track_max_views: dict[str, int] = defaultdict(int)

    for v in videos:
        track = str(v.get("track") or "").strip()
        artist = str(v.get("artist") or "").strip()
        views = int(v.get("view_count") or 0)
        if not track:
            continue
        key = track.lower()
        track_counts[key] += 1
        if key not in track_artists and artist:
            track_artists[key] = artist
        if views > track_max_views[key]:
            track_max_views[key] = views

    # Сортируем по количеству использований, затем по просмотрам
    sorted_tracks = sorted(
        track_counts.keys(),
        key=lambda k: (track_counts[k], track_max_views[k]),
        reverse=True,
    )

    trending = []
    for key in sorted_tracks[:5]:
        # Восстанавливаем оригинальное написание
        original_track = next(
            (str(v.get("track") or "") for v in videos
             if str(v.get("track") or "").strip().lower() == key),
            key,
        )
        trending.append({
            "track": original_track,
            "artist": track_artists.get(key, ""),
            "count": track_counts[key],
            "example_views": track_max_views[key],
        })

    return {
        "status": "ok",
        "trending": trending,
        "videos_analyzed": len(videos),
        "niche": niche,
    }



