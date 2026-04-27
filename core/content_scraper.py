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

# Legacy game labels kept for backward compat on old results
ARBITRAGE_GAME_LABELS: dict[str, str] = {
    "tower_rust":    "Tower Rust",
    "mine_drop":     "Mine Drop",
    "aviator":       "Avia Master",
    "ice_fishing":   "Ice Fishing",
    "lucky_jet":     "Lucky Jet",
    "spaceman":      "Spaceman",
    "plinko":        "Plinko X",
    "dice_duel":     "Dice Duel",
    "penalty_kick":  "Penalty Kick",
    "hilo":          "Hi-Lo",
    "coinflip":      "Coin Flip",
    "wheel":         "Fortune Wheel",
}

ARBITRAGE_GAME_COLORS: dict[str, str] = {
    "tower_rust":    "#F59E0B",
    "mine_drop":     "#EF4444",
    "aviator":       "#3B82F6",
    "ice_fishing":   "#06B6D4",
    "lucky_jet":     "#10B981",
    "spaceman":      "#8B5CF6",
    "plinko":        "#F97316",
    "dice_duel":     "#EC4899",
    "penalty_kick":  "#84CC16",
    "hilo":          "#6366F1",
    "coinflip":      "#FBBF24",
    "wheel":         "#14B8A6",
}

ARBITRAGE_GAME_PATTERNS: dict[str, list[str]] = {
    # ── Tower Rust ──────────────────────────────────────────────────────────────
    "tower_rust": [
        "tower game big win shorts",
        "tower rust win shorts strategy",
        "tower crash game x100 shorts",
        "towers gambling cashout win",
        "tower game quick win shorts",
        "타워 게임 대박 shorts",
        "tower game hack win shorts",
        "tower cashout reaction shorts",
        "tower game promo code shorts",
        "1win tower big win shorts",
    ],
    # ── Mine Drop ───────────────────────────────────────────────────────────────
    "mine_drop": [
        "mines game big win shorts",
        "mines predictor win shorts",
        "mine drop x100 cashout shorts",
        "mines strategy big win shorts",
        "mine game jackpot win shorts",
        "마인 게임 대박 shorts",
        "mines crash win shorts",
        "mines quick win shorts",
        "stake mines big win shorts",
        "1win mines predictor shorts",
        "mines signal free win shorts",
    ],
    # ── Avia Master / Aviator ───────────────────────────────────────────────────
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
        "aviator predictor signal shorts",
        "에비에이터 대박 shorts",
        "เกม aviator โบนัส shorts",
    ],
    # ── Ice Fishing ─────────────────────────────────────────────────────────────
    "ice_fishing": [
        "ice fishing game big win shorts",
        "ice fishing slot max win shorts",
        "ice fishing crash win shorts",
        "ice fishing quick win shorts",
        "ice fishing x100 cashout shorts",
        "아이스 피싱 대박 shorts",
        "ice fishing gambling win shorts",
        "ice fishing bonus buy shorts",
        "1win ice fishing big win shorts",
    ],
    # ── Lucky Jet ───────────────────────────────────────────────────────────────
    "lucky_jet": [
        "lucky jet big win shorts",
        "lucky jet x100 cashout shorts",
        "lucky jet strategy win shorts",
        "lucky jet signal predictor shorts",
        "lucky jet 1win win shorts",
        "러키젯 대박 shorts",
        "lucky jet hack win shorts",
        "лаки джет большой выигрыш shorts",
        "лаки джет сигнал shorts",
        "lucky jet promo free bonus shorts",
        "jetx big win cashout shorts",
        "jetx crash win shorts",
    ],
    # ── Spaceman ────────────────────────────────────────────────────────────────
    "spaceman": [
        "spaceman game big win shorts",
        "spaceman crash x100 shorts",
        "spaceman pragmatic big win shorts",
        "spaceman signal strategy shorts",
        "spaceman cashout win shorts",
        "스페이스맨 대박 shorts",
        "spaceman bonus buy win shorts",
        "спейсмен большой выигрыш shorts",
        "spaceman 1win win shorts",
        "spaceman predictor signal shorts",
    ],
    # ── Plinko X ────────────────────────────────────────────────────────────────
    "plinko": [
        "plinko game big win shorts",
        "plinko x max win shorts",
        "plinko jackpot win shorts",
        "plinko strategy hack win shorts",
        "plinko 1win big win shorts",
        "플링코 대박 shorts",
        "plinko ball win cashout shorts",
        "플링코 게임 대박 shorts",
        "плинко большой выигрыш shorts",
        "plinko signal win free shorts",
    ],
    # ── Dice Duel ───────────────────────────────────────────────────────────────
    "dice_duel": [
        "dice game big win shorts",
        "dice duel win cashout shorts",
        "dice 1win big win shorts",
        "주사위 게임 대박 shorts",
        "dice predictor win shorts",
        "dice x100 strategy win shorts",
        "dice gambling win shorts",
        "เกม dice โบนัส shorts",
        "кости казино выигрыш shorts",
    ],
    # ── Penalty Kick ────────────────────────────────────────────────────────────
    "penalty_kick": [
        "penalty shootout game win shorts",
        "penalty kick online big win shorts",
        "penalty 1win win cashout shorts",
        "페널티 킥 게임 대박 shorts",
        "penalty game strategy win shorts",
        "penalty game jackpot shorts",
        "penalty kick predictor win shorts",
        "เกมเตะ penalty โบนัส shorts",
    ],
    # ── Hi-Lo ───────────────────────────────────────────────────────────────────
    "hilo": [
        "hi lo card game big win shorts",
        "hilo game win cashout shorts",
        "hilo strategy x100 win shorts",
        "hi lo 1win big win shorts",
        "하이로우 게임 대박 shorts",
        "hilo predictor signal shorts",
        "hilo hack win strategy shorts",
        "hi lo bonus free win shorts",
    ],
    # ── Coin Flip ───────────────────────────────────────────────────────────────
    "coinflip": [
        "coin flip game big win shorts",
        "coinflip casino win shorts",
        "coinflip x100 cashout shorts",
        "동전 게임 대박 shorts",
        "coinflip predictor win shorts",
        "coin flip 1win win shorts",
        "coinflip jackpot shorts",
    ],
    # ── Fortune Wheel ───────────────────────────────────────────────────────────
    "wheel": [
        "fortune wheel big win shorts",
        "wheel of fortune casino win shorts",
        "spin wheel jackpot shorts",
        "wheel game x100 win shorts",
        "럭키 휠 대박 shorts",
        "wheel predictor win signal shorts",
        "wheel 1win cashout shorts",
        "колесо фортуны выигрыш shorts",
        "spin win bonus free shorts",
    ],
}

# ── UBT link-masking CTA patterns ─────────────────────────────────────────────
# Типичные фразы, которыми арбитражники маскируют ссылки на оффер.
# Русские + английские + корейские + тайские варианты.
UBT_MASKING_PATTERNS: tuple[str, ...] = (
    # RU — профиль / шапка
    "ссылка в профиле", "ссылка в шапке", "ссылка в описании", "ссылка в имени",
    "ссылка на игру", "ссылка на казино", "ссылка в комментарии",
    "игра в профиле", "игра в шапке", "игра в описании", "игра в имени",
    "жми на ник", "тыкни на ник", "нажми на ник", "жми на аватар",
    "тыкни на аватар", "нажми на аватар", "заходи в профиль", "перейди в профиль",
    "смотри профиль", "профиль", "шапка профиля",
    "бонус в профиле", "бонус в шапке", "бонус в описании",
    "промокод в профиле", "промокод в шапке", "промо в шапке",
    # RU — регистрация / депозит
    "первый депозит", "первый депо", "без депозита", "бездепозитный",
    "фриспины", "фри спины", "бесплатные спины",
    "забери бонус", "получи бонус", "забрать бонус", "активировать бонус",
    "регистрируйся", "регайся", "зарегистрироваться", "создай аккаунт",
    "пополни счёт", "пополни баланс", "внеси депозит",
    "ссылка для регистрации", "регистрация по ссылке",
    # EN — profile / bio
    "link in bio", "link in profile", "link in description", "link in name",
    "game in bio", "casino in bio", "check profile", "see profile",
    "profile link", "bio link", "click nick", "tap avatar", "tap profile",
    "go to profile", "visit profile", "open profile",
    "register via link", "sign up link", "bonus link",
    # EN — deposit / bonus
    "no deposit bonus", "free spins", "first deposit bonus",
    "claim bonus", "get bonus", "grab bonus", "free bonus",
    "promo code", "promocode", "exclusive bonus",
    # KO — 링크
    "프로필 링크", "프로필에서", "링크 클릭", "닉네임 클릭",
    "바이오 링크", "설명란 링크",
    # TH — ลิงก์
    "ลิงก์ในโปรไฟล์", "ดูโปรไฟล์", "กดที่ชื่อ", "รับโบนัส", "สมัครสมาชิก",
    # VI — liên kết
    "link trong bio", "xem profile", "nhấn vào tên", "đăng ký",
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
    "money_reaction":   "Шок-реакция",
    "secret_method":    "Секретный метод",
    "new_app":          "Новое приложение",
    "multiplier":       "Мультипликатор",
    "lifestyle":        "Пассивный доход",
    "urgency":          "Срочность",
    "withdrawal_proof": "Вывод / Скрин",
    "phone_screen":     "Экран телефона",
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
}

STEALTH_SCAN_PATTERNS: dict[str, list[str]] = {
    # ── Категория 1: Шок-реакция на деньги ────────────────────────────────────
    # Человек реагирует на «что-то» — без называния чего именно.
    # Типичная маска: лицо с открытым ртом + цифры на экране.
    "money_reaction": [
        # RU
        "заработал за 5 минут шок shorts",
        "не мог поверить сколько заработал shorts",
        "мой доход сегодня реакция shorts",
        "шокирующий заработок shorts",
        "сколько я заработал shorts",
        "реакция на выигрыш shorts",
        "не верил пока сам не попробовал shorts",
        # EN
        "earned in 5 minutes reaction shorts",
        "cant believe how much i made shorts",
        "shocking income today shorts",
        "made money fast reaction shorts",
        "my reaction to winning shorts",
        # KO
        "5분에 돈 벌었어 shorts",
        "믿을 수 없는 수입 shorts",
        "충격적인 수익 반응 shorts",
        # TH
        "หาเงินได้ใน 5 นาที ตกใจมาก shorts",
        "ทำเงินได้เยอะมาก ช็อคมาก shorts",
        # VI
        "kiếm được tiền trong 5 phút shorts",
    ],

    # ── Категория 2: Секретный метод ──────────────────────────────────────────
    # «Секрет/метод/схема» — без называния продукта.
    # Маска: мотивашка + CTA «ссылка в профиле».
    "secret_method": [
        # RU
        "секрет заработка который скрывают shorts",
        "метод который от тебя скрывают shorts",
        "схема заработка 2026 shorts",
        "способ заработать дома shorts",
        "этот метод изменил мою жизнь shorts",
        "лайфхак для заработка который работает shorts",
        "то что не показывают по телевизору shorts",
        # EN
        "secret method to make money shorts",
        "method they hide from you shorts",
        "money trick that works 2026 shorts",
        "this works nobody tells you shorts",
        "secret hack they dont want you to know shorts",
        # KO
        "돈 버는 비밀 방법 shorts",
        "숨겨진 수익 방법 shorts",
        "아무도 알려주지 않는 돈 버는 법 shorts",
        # TH
        "วิธีลับหาเงิน shorts",
        "ความลับที่ทำให้รวย shorts",
        # VI
        "bi mat kiem tien shorts",
        "phuong phap ho giau giau shorts",
    ],

    # ── Категория 3: Новое приложение ─────────────────────────────────────────
    # «Попробовал приложение» — продукт не называется.
    # Маска: загружает «приложение» → показывает «результат» → «ссылка в шапке».
    "new_app": [
        # RU
        "новое приложение которое реально платит shorts",
        "попробовал приложение результат шокировал shorts",
        "это приложение реально платит 2026 shorts",
        "заработок с телефона новое приложение shorts",
        "нашёл приложение которое даёт деньги shorts",
        "приложение которое все скачивают shorts",
        # EN
        "new app that actually pays real money shorts",
        "tried this app shocking results shorts",
        "earn money from phone new app 2026 shorts",
        "app pays real money no joke shorts",
        "found app that gives money shorts",
        # KO
        "돈 버는 앱 발견했어 shorts",
        "이 앱 실제로 돈 나옴 shorts",
        "새 앱 진짜 돈 됨 shorts",
        # TH
        "แอปหาเงินได้จริง shorts",
        "ลองแอปใหม่ ได้เงินจริง shorts",
        # VI
        "app kiem tien that su shorts",
        "thu app moi ket qua soc shorts",
    ],

    # ── Категория 4: Мультипликатор ───────────────────────────────────────────
    # x47, ×100 — множитель без называния игры.
    # Маска: экран с цифрой + шок-фейс + «жми на ник».
    "multiplier": [
        # RU
        "умножил деньги за минуту shorts",
        "x100 за 5 минут реакция shorts",
        "поднял деньги shorts",
        "в 100 раз больше shorts",
        "умножил вклад шок shorts",
        "поставил 100 получил shorts",
        # EN
        "multiplied my money shorts reaction",
        "x100 in one minute shorts",
        "turned 100 into 10000 shorts",
        "money multiplied insane reaction shorts",
        "bet small win big reaction shorts",
        # KO
        "100배로 불렸어 shorts",
        "돈 100배 수익 반응 shorts",
        "배팅 소액으로 대박 shorts",
        # TH
        "เพิ่มเงิน 100 เท่า shorts",
        "x100 ใน 1 นาที ตกใจ shorts",
        # VI
        "nhan tien 100 lan shorts",
        "x100 trong 1 phut phan ung shorts",
    ],

    # ── Категория 5: Пассивный доход / лайфстайл ──────────────────────────────
    # «Как я зарабатываю не работая» — без конкретики.
    # Маска: flex-контент + люкс + «подробнее в профиле».
    "lifestyle": [
        # RU
        "как я зарабатываю не работая shorts",
        "мой пассивный доход shorts",
        "заработок без вложений реально shorts",
        "сколько зарабатываю в день shorts",
        "как живут те кто знает shorts",
        "мой доход в день покажу shorts",
        # EN
        "how i earn without working shorts",
        "my passive income revealed shorts",
        "earn without investment real shorts",
        "how much i make per day shorts",
        "living off passive income shorts",
        # KO
        "일 안하고 돈 버는 방법 shorts",
        "하루 수입 공개 shorts",
        "패시브 인컴 공개 shorts",
        # TH
        "รายได้โดยไม่ต้องทำงาน shorts",
        "รายได้ต่อวัน เปิดเผย shorts",
        # VI
        "kiem tien khong can lam viec shorts",
        "thu nhap tho dong moi ngay shorts",
    ],

    # ── Категория 6: Срочность / пока не удалили ──────────────────────────────
    # «Это скоро закроют» — создаёт FOMO без называния продукта.
    # Маска: countdown + urgency copy + тап на профиль.
    "urgency": [
        # RU
        "успей пока не закрыли shorts",
        "работает только сегодня shorts",
        "это скоро удалят shorts",
        "пока не заблокировали shorts",
        "осталось мало мест shorts",
        "только для первых shorts",
        "смотри пока не удалили shorts",
        # EN
        "hurry before they close this shorts",
        "works only today limited shorts",
        "they will delete this soon shorts",
        "limited spots available shorts",
        "before it gets blocked act now shorts",
        # KO
        "곧 사라질 방법 shorts",
        "지금 아니면 늦어 shorts",
        "곧 막힐 예정 shorts",
        # TH
        "รีบก่อนปิด shorts",
        "ทำได้แค่วันนี้เท่านั้น shorts",
        # VI
        "lam ngay truoc khi bi xoa shorts",
        "con han che cho shorts",
    ],

    # ── Категория 7: Вывод / скрин / доказательство ───────────────────────────
    # «Я вывел деньги — вот скрин» — без названия источника.
    # Маска: скриншот транзакции + «как? ссылка в описании».
    "withdrawal_proof": [
        # RU
        "вывод денег доказательство shorts",
        "скрин вывода реальный shorts",
        "доказательство выплаты shorts",
        "я вывел деньги shorts",
        "реальный вывод покажу shorts",
        "скриншот выплаты shorts",
        # EN
        "withdrawal proof real shorts",
        "payment proof legit shorts",
        "real withdrawal money shorts",
        "proof of payout shorts",
        "showing my cashout proof shorts",
        # KO
        "출금 인증 실제 shorts",
        "입금 증거 shorts",
        "출금 스크린샷 shorts",
        # TH
        "หลักฐานการถอนเงินจริง shorts",
        "สกรีนช็อตการถอน shorts",
        # VI
        "bang chung rut tien that shorts",
        "screenshot rut tien shorts",
    ],

    # ── Категория 8: Экран телефона ───────────────────────────────────────────
    # «Смотри что у меня на экране» — показывает UI без называния продукта.
    # Маска: POV + экран + тыкает пальцем + «ссылка в шапке».
    "phone_screen": [
        # RU
        "показываю как зарабатываю телефон shorts",
        "смотри что у меня на телефоне shorts",
        "экран телефона заработок shorts",
        "телефон приносит деньги shorts",
        "результат на экране телефона shorts",
        "смотри что показывает телефон shorts",
        # EN
        "showing my phone screen earnings shorts",
        "watch my phone screen money shorts",
        "phone screen shows income shorts",
        "pov phone earning money shorts",
        "my phone makes money watch shorts",
        # KO
        "폰 화면으로 돈 버는 거 보여줄게 shorts",
        "핸드폰 화면 수익 shorts",
        # TH
        "แสดงหน้าจอโทรศัพท์รายได้ shorts",
        "หน้าจอโทรศัพท์ทำเงินได้ shorts",
        # VI
        "xem man hinh dien thoai kiem tien shorts",
        "dien thoai lam ra tien shorts",
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

    Returns: {category_key: [video, ...], ...}
    """
    target_cats = categories or list(STEALTH_SCAN_PATTERNS.keys())
    output: dict[str, list[dict[str, Any]]] = {}
    reg = None if _is_global_region(region) else (str(region or "").strip().upper() or None)
    watchlist_norm = _normalize_watchlist_entries(watchlist_channels)

    for cat_key in target_cats:
        queries = STEALTH_SCAN_PATTERNS.get(cat_key)
        if not queries:
            output[cat_key] = []
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
            for q in queries
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        seen: dict[str, dict[str, Any]] = {}
        for batch in raw:
            if isinstance(batch, BaseException):
                logger.debug("stealth scan %s batch error: %s", cat_key, batch)
                continue
            for video in batch:
                vid_key = str(video.get("id") or video.get("url") or "")
                if not vid_key:
                    continue
                if vid_key not in seen or (video.get("view_count") or 0) > (seen[vid_key].get("view_count") or 0):
                    wl_match = _watchlist_match(video, watchlist_norm)
                    # Full enrichment with stealth signals
                    enriched = enrich_video_risk(video, watchlist_hit=bool(wl_match))
                    enriched["category"] = cat_key
                    enriched["category_label"] = STEALTH_CATEGORY_LABELS.get(cat_key, cat_key)
                    enriched["arb_score"] = enriched.get("risk_score", 0)
                    enriched["watchlist_hit"] = bool(wl_match)
                    enriched["watchlist_match"] = wl_match or ""
                    seen[vid_key] = enriched

        # Sort: watchlist first, then risk_score desc, then views desc
        output[cat_key] = sorted(
            seen.values(),
            key=lambda v: (
                int(v.get("watchlist_hit") is True),
                int(v.get("risk_score") or 0),
                int(v.get("view_count") or 0),
            ),
            reverse=True,
        )[:limit_per_query * 4]

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
    """Return the best-matching offer niche or None if no match."""
    best: str | None = None
    best_hits = 0
    for niche, patterns in OFFER_NICHE_PATTERNS.items():
        hits = sum(1 for p in patterns if p in text)
        if hits > best_hits:
            best_hits = hits
            best = niche
    return best if best_hits >= 1 else None


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

    # ── 6. YouTube Shorts duration signal ───────────────────────────────────
    if 0 < duration <= 60:
        _add("duration:shorts", 8)
    elif duration > 120:
        _add("duration:long", -8)

    # ── 7. Engagement anomaly ────────────────────────────────────────────────
    # Very high ER on Shorts is suspicious (bot engagement or viral arbitrage)
    if views > 0:
        er = (likes + comments) / views * 100
        if er > 15:
            _add("engagement:anomaly_high", 10)
        elif er > 8:
            _add("engagement:high", 5)

    # ── 8. View velocity signals ─────────────────────────────────────────────
    if views >= 5_000_000:
        _add("views:viral", 8)
    elif views >= 1_000_000:
        _add("views:million", 5)
    elif views >= 100_000:
        _add("views:100k", 3)

    # ── 9. Channel name signals ──────────────────────────────────────────────
    # Generic/anonymous channel names are a weak UBT signal
    generic_words = ("shorts", "official", "channel", "videos", "clips", "best")
    if not channel or all(w in channel for w in generic_words[:1]):
        _add("channel:generic", 4)
    if "official" in channel or "gaming" in channel.lower():
        _add("channel:branded", -5)

    # ── 10. Negative context (reduces score) ────────────────────────────────
    if "review" in text or "обзор" in text or "tutorial" in text:
        _add("ctx:review", -10)
    if "no links" in text or "без ссылки" in text or "not sponsored" in text:
        _add("ctx:no_links", -12)
    if "official" in text and ("youtube" in text or "channel" in text):
        _add("ctx:official_channel", -8)

    # ── 11. Watchlist boost ──────────────────────────────────────────────────
    if watchlist_hit:
        _add("watchlist_hit", 20)

    # ── 12. Query pattern match ──────────────────────────────────────────────
    qp = [str(x or "").strip().lower() for x in (query_patterns or []) if str(x or "").strip()]
    if qp:
        q_hits = 0
        for q in qp:
            toks = [t for t in q.split() if len(t) >= 4]
            if any(t in text for t in toks):
                q_hits += 1
        if q_hits:
            _add("query_match", min(16, q_hits * 4))

    # ── Niche classification ─────────────────────────────────────────────────
    niche = _classify_offer_niche(text)

    # ── 13. Stealth behavioral signals (2026 masking style) ──────────────────
    stealth_pts, stealth_flags = _score_stealth_signals(video)
    for sf in stealth_flags:
        _add(f"stealth:{sf}", 0)          # register flag without double-adding
    # Add stealth score as a single block to avoid double-counting
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

    # Confidence: more distinct signal types = more confident
    n_positive = sum(1 for v in signal_map.values() if v > 0)
    confidence = 0.30 + min(0.65, n_positive * 0.07)
    confidence = float(max(0.0, min(0.98, confidence)))

    out["risk_score"] = risk_score
    out["risk_tier"] = tier
    out["risk_confidence"] = round(confidence, 3)
    out["risk_signals"] = list(signal_map.keys())
    out["risk_signal_map"] = signal_map
    out["ubt_mask_score"] = risk_score
    out["ubt_flags"] = [k for k in signal_map if signal_map.get(k, 0) >= 10]
    out["ubt_marker"] = risk_score >= 65
    out["ubt_suspected"] = risk_score >= 35
    out["ubt_niche"] = niche
    out["ubt_shorteners"] = shorteners_found
    out["ubt_masking_hits"] = [p for p in UBT_MASKING_PATTERNS if p in text]
    return out


