"""
media_scanner.py — Мультимодальный анализатор видео.

Архитектура: asyncio.Queue + ThreadPoolExecutor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  submit(video_id, url)                ← возвращает Future сразу
        │
        ▼ asyncio.Queue
  _worker_loop  (asyncio Task)
        ├── _get_stream_urls()         ← asyncio subprocess (yt-dlp)
        ├── _gather_frames()           ← asyncio subprocess (ffmpeg pipe) × N
        ├── _extract_audio_bytes()     ← asyncio subprocess (ffmpeg pipe)
        ├── loop.run_in_executor()     ← ThreadPoolExecutor
        │       ├── _analyze_frames_sync()   OpenCV + cv2.QRCodeDetector
        │       └── _transcribe_audio_sync() faster-whisper
        └── set_result(MediaScanResult)

Оптимизация трафика:
  • Видео НЕ скачивается целиком.
  • Кадры: ffmpeg -ss {t} -vframes 1 → ~50-150 KB на кадр.
  • Аудио: ffmpeg -t 60 → первые 60 с, f32le 16kHz → ~3.8 MB.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Опциональные зависимости ──────────────────────────────────────────────────
try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False
    logger.warning("media_scanner: cv2 не установлен — visual scan отключён")

try:
    from faster_whisper import WhisperModel as _WhisperModel
    _WHISPER_OK = True
except ImportError:
    _WHISPER_OK = False
    logger.warning("media_scanner: faster-whisper не установлен — audio scan отключён")

try:
    import easyocr  # noqa: F401
    _EASYOCR_OK = True
except ImportError:
    _EASYOCR_OK = False
    logger.warning("media_scanner: easyocr не установлен — OCR-триггеры отключены")

# ── Конфиг (переопределяется через env) ──────────────────────────────────────
_FRAME_W = 640
_FRAME_H = 360
_AUDIO_SR = 16_000
_AUDIO_MAX_SEC = int(os.environ.get("MEDIA_SCAN_AUDIO_SEC", "55"))
_WHISPER_MODEL  = os.environ.get("WHISPER_MODEL_SIZE", "base")
_SCAN_WORKERS   = int(os.environ.get("MEDIA_SCAN_WORKERS", "2"))
_SCAN_THREADS   = int(os.environ.get("MEDIA_SCAN_THREADS", "4"))

# Триггерные фразы для аудио (произнесённые CTA без текста в описании)
_AUDIO_TRIGGERS: tuple[str, ...] = (
    # RU — профиль/шапка
    "ссылка в профиле", "ссылка в шапке", "ссылка в описании",
    "жми на ник", "нажми на ник", "тыкни на ник",
    "жми на аватар", "нажми на аватар", "тыкни на аватар",
    "заходи в профиль", "смотри профиль",
    # RU — бонус/регистрация
    "забирай бонус", "забери бонус", "получи бонус",
    "забирай фриспины", "бесплатные спины", "фриспины",
    "первый депозит", "без депозита", "бездепозитный",
    "промокод", "промо код", "бонусный код",
    "регистрируйся", "зарегайся", "создай аккаунт",
    "пополни счёт", "пополни баланс",
    # RU — Telegram
    "переходи в телеграм", "пиши в телеграм", "напиши в тг",
    "телеграм в профиле", "тг ссылка",
    # RU — QR/приложение
    "сканируй qr", "отсканируй код", "qr в кадре",
    "нашёл игру", "это приложение", "название в профиле",
    # EN — profile/bio
    "link in bio", "link in profile", "check my bio",
    "click the link", "tap the link", "go to profile",
    # EN — bonus
    "claim your bonus", "get your bonus", "free spins",
    "no deposit", "promo code", "bonus code",
    "register now", "sign up now", "create account",
    # EN — Telegram
    "join my telegram", "dm me for the link", "message me",
    # EN — QR/app
    "scan the qr", "scan the code", "found this app",
    "this app pays", "link in description",
    # KO
    "프로필 링크", "링크 클릭", "보너스 받아", "텔레그램",
    "가입하세요", "클릭하세요",
    # TH
    "ลิงก์ในโปรไฟล์", "รับโบนัส", "สแกน qr", "สมัครสมาชิก",
)


# ── UBT / гемблинг: OCR-словари (интерфейс игры, не названия слотов) ──────────

OCR_MULTIPLIER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|[\s(\[])[xх]\s*\d+(?:[.,]\d+)?\b", re.IGNORECASE),
    re.compile(r"\b\d+[.,]\d+\s*[xх]\b", re.IGNORECASE),
)

OCR_BUTTON_WORDS_RU: tuple[str, ...] = (
    "забрать", "забери", "ставка", "мин", "макс", "баланс",
    "вывод", "играть", "автоставка",
)
OCR_BUTTON_WORDS_EN: tuple[str, ...] = (
    "cashout", "bet", "min", "max", "balance", "withdraw", "play", "auto",
)
OCR_CTA_WORDS: tuple[str, ...] = (
    "промик", "промокод", "промо", "телега", "телеграм", "tg", "telegram",
)

OCR_GAMBLING_COMBO_TAKE: tuple[str, ...] = ("забрать", "cashout", "забери")


_easyocr_reader: Any | None = None
_easyocr_lock = threading.Lock()


def _get_easyocr_reader() -> Any | None:
    """Lazy EasyOCR (ru+en), GPU off — вызывать из executor-потоков."""
    global _easyocr_reader
    if not _EASYOCR_OK:
        return None
    if _easyocr_reader is not None:
        return _easyocr_reader
    with _easyocr_lock:
        if _easyocr_reader is not None:
            return _easyocr_reader
        try:
            import easyocr as _eo

            _easyocr_reader = _eo.Reader(["ru", "en"], gpu=False, verbose=False)
        except Exception as exc:
            logger.warning("easyocr init failed: %s", exc)
            return None
    return _easyocr_reader


def analyze_frame_text(frame: np.ndarray, *, has_split_screen: bool = False) -> dict[str, Any]:
    """
    OCR кадра (EasyOCR): множители x2, кнопки слотов/краша, призывы TG/промо.
    Возвращает совпадения и флаг «жёсткий гемблинг»: множитель + «Забрать» на сплит-скрине.
    """
    out: dict[str, Any] = {
        "matches": [],
        "has_multiplier": False,
        "has_button_word": False,
        "has_cta": False,
        "is_gambling_combo": False,
        "raw_text_sample": "",
    }
    if frame is None or frame.size == 0:
        return out
    reader = _get_easyocr_reader()
    if reader is None:
        return out
    try:
        lines = reader.readtext(frame, detail=0, paragraph=True)
    except Exception as exc:
        logger.debug("analyze_frame_text OCR: %s", exc)
        return out
    if isinstance(lines, str):
        blob = lines.lower()
    else:
        blob = " ".join(str(x) for x in lines).lower()
    out["raw_text_sample"] = blob[:400]

    matched: list[str] = []
    for rx in OCR_MULTIPLIER_PATTERNS:
        if rx.search(blob):
            out["has_multiplier"] = True
            m = rx.search(blob)
            if m:
                matched.append(f"mult:{m.group(0).strip()[:20]}")
            break

    for w in OCR_BUTTON_WORDS_RU + OCR_BUTTON_WORDS_EN:
        if len(w) >= 3 and w in blob:
            out["has_button_word"] = True
            matched.append(f"btn:{w}")
            break

    for w in OCR_CTA_WORDS:
        if w in blob:
            out["has_cta"] = True
            matched.append(f"cta:{w}")
            break

    take_hit = any(t in blob for t in OCR_GAMBLING_COMBO_TAKE)
    if out["has_multiplier"] and take_hit and has_split_screen:
        out["is_gambling_combo"] = True
        matched.append("combo:mult+take+split")

    out["matches"] = matched[:24]
    return out


def _detect_arrow_hooks_bgr(frame: np.ndarray) -> bool:
    """Крупные красные / жёлтые стрелки (контуры на HSV-масках)."""
    if not _CV2_OK or frame is None or frame.size == 0:
        return False
    h, w = frame.shape[:2]
    if h < 16 or w < 16:
        return False
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Красный в два диапазона hue
    m1 = cv2.inRange(hsv, (0, 70, 70), (10, 255, 255))
    m2 = cv2.inRange(hsv, (170, 70, 70), (180, 255, 255))
    red = cv2.bitwise_or(m1, m2)
    yellow = cv2.inRange(hsv, (18, 80, 80), (38, 255, 255))
    area_min = max(800, int(h * w * 0.004))
    for mask in (red, yellow):
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            a = float(cv2.contourArea(c))
            if a < area_min:
                continue
            peri = cv2.arcLength(c, True)
            if peri < 1:
                continue
            approx = cv2.approxPolyDP(c, 0.04 * peri, True)
            if len(approx) < 3 or len(approx) > 14:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            ar = bw / float(bh + 1e-6)
            if 0.15 <= ar <= 6.0 and a > area_min:
                return True
    return False


def _detect_bank_top_strip_bgr(frame: np.ndarray) -> bool:
    """Верхняя полоса «пополнение счёта»: светлый фон + зелёные цифры/валюта."""
    if not _CV2_OK or frame is None or frame.size == 0:
        return False
    h, w = frame.shape[:2]
    strip_h = max(8, int(h * 0.20))
    top = frame[:strip_h, :]
    gray = cv2.cvtColor(top, cv2.COLOR_BGR2GRAY)
    if float(gray.mean()) < 145:
        return False
    hsv = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (35, 50, 50), (95, 255, 255))
    if (green > 0).mean() > 0.008:
        reader = _get_easyocr_reader()
        if reader is not None:
            try:
                txt = " ".join(reader.readtext(top, detail=0, paragraph=True))
                t = str(txt).lower()
                for sym in ("₽", "₸", "₴", "$", "€", "р.", "тг", "kzt", "uah"):
                    if sym in txt or sym in t:
                        return True
            except Exception:
                pass
        # без символа валюты — но явный «банковский» зелёный текст на белом
        if (green > 0).mean() > 0.035:
            return True
    return False


def detect_visual_hooks(video_frames: list[np.ndarray]) -> dict[str, Any]:
    """
    Примитивные визуальные крючки по всем кадрам: стрелки, полоса «баланс/банк» сверху.
    """
    agg: dict[str, Any] = {
        "has_arrow": False,
        "has_bank_strip": False,
        "arrow_frames": 0,
        "bank_frames": 0,
        "hook_labels": [],
    }
    for fr in video_frames:
        if fr is None or fr.size == 0:
            continue
        if _detect_arrow_hooks_bgr(fr):
            agg["arrow_frames"] += 1
            agg["has_arrow"] = True
        if _detect_bank_top_strip_bgr(fr):
            agg["bank_frames"] += 1
            agg["has_bank_strip"] = True
    if agg["has_arrow"]:
        agg["hook_labels"].append("visual:arrow")
    if agg["has_bank_strip"]:
        agg["hook_labels"].append("visual:bank_strip")
    return agg


# ── Dataclasses результатов ───────────────────────────────────────────────────

@dataclasses.dataclass
class VisualScanResult:
    has_split_screen: bool = False
    has_qr_code: bool = False
    qr_codes: list[str] = dataclasses.field(default_factory=list)
    has_push_overlay: bool = False
    frames_analyzed: int = 0
    confidence: float = 0.0
    # UBT: OCR + примитивные визуальные крючки
    ocr_hit_labels: list[str] = dataclasses.field(default_factory=list)
    visual_hook_labels: list[str] = dataclasses.field(default_factory=list)
    video_risk: str = "low"  # low | medium | high
    ocr_gambling_combo: bool = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class AudioScanResult:
    transcript: str = ""
    trigger_phrases: list[str] = dataclasses.field(default_factory=list)
    language_detected: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class MediaScanResult:
    video_id: str = ""
    video_url: str = ""
    visual: VisualScanResult = dataclasses.field(default_factory=VisualScanResult)
    audio: AudioScanResult = dataclasses.field(default_factory=AudioScanResult)
    media_score: int = 0
    media_flags: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None
    scan_duration_sec: float = 0.0
    scanned_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        return d


@dataclasses.dataclass
class _ScanJob:
    video_id: str
    url: str
    duration: float
    future: asyncio.Future[MediaScanResult]


# ── Singleton Whisper (thread-safe) ───────────────────────────────────────────

_whisper_instance: Any | None = None
_whisper_lock = threading.Lock()


def _load_whisper_sync() -> Any | None:
    """
    Загружает модель Whisper. Блокирующий → вызывать через executor.
    Thread-safe через threading.Lock.
    """
    global _whisper_instance
    if _whisper_instance is not None:
        return _whisper_instance
    if not _WHISPER_OK:
        return None
    with _whisper_lock:
        if _whisper_instance is not None:   # double-check
            return _whisper_instance
        try:
            logger.info("faster-whisper: загрузка модели '%s'…", _WHISPER_MODEL)
            _whisper_instance = _WhisperModel(
                _WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
                num_workers=1,
            )
            logger.info("faster-whisper: модель '%s' готова", _WHISPER_MODEL)
        except Exception as exc:
            logger.error("faster-whisper: не удалось загрузить модель: %s", exc)
            return None
    return _whisper_instance


# ── Путь к yt-dlp ─────────────────────────────────────────────────────────────

def _ytdlp() -> str | None:
    return shutil.which("yt-dlp") or shutil.which("yt_dlp")


# ── Получение URL потоков через yt-dlp ────────────────────────────────────────

async def _get_stream_urls(video_url: str) -> tuple[str, str, float]:
    """
    Возвращает (video_stream_url, audio_stream_url, duration_sec).
    Использует два параллельных вызова yt-dlp --get-url.
    Не скачивает видео — только парсит манифест.
    """
    ytdlp = _ytdlp()
    if not ytdlp:
        return "", "", 0.0

    # Общие флаги
    base = [ytdlp, "--get-url", "--no-playlist", "--no-warnings", "--no-check-certificate"]

    async def _run(fmt: str) -> str:
        cmd = [*base, "-f", fmt, video_url]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25.0)
            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            # yt-dlp --get-url может вернуть несколько строк (video+audio раздельно);
            # нам нужна первая непустая
            return next((ln.strip() for ln in lines if ln.strip().startswith("http")), "")
        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("_get_stream_urls fmt=%s: %s", fmt, exc)
            return ""

    # Видео до 480p (меньше данных при seek) и лучшее аудио
    video_url_result, audio_url_result = await asyncio.gather(
        _run("best[height<=480][ext=mp4]/best[height<=480]/best"),
        _run("bestaudio/best"),
    )

    # Длительность: берём из ffprobe по video-URL если он получен
    duration = 0.0
    url_for_probe = video_url_result or audio_url_result
    if url_for_probe:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                url_for_probe,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            duration = float(stdout.decode().strip() or "0")
        except Exception:
            pass

    return video_url_result, audio_url_result, duration


# ── Извлечение кадров через ffmpeg pipe ───────────────────────────────────────

_FRAME_BYTES = _FRAME_W * _FRAME_H * 3   # 691 200 байт в BGR24


async def _extract_one_frame(stream_url: str, seek_sec: float) -> bytes:
    """
    Одиночный кадр в позиции seek_sec → raw BGR24 bytes (640×360).
    Скачивается только минимальный сегмент потока за счёт -ss до -i.
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seek_sec:.2f}",       # seek ДО открытия потока (быстро)
        "-i", stream_url,
        "-vframes", "1",
        "-vf", f"scale={_FRAME_W}:{_FRAME_H}",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=18.0)
        if len(stdout) == _FRAME_BYTES:
            return stdout
    except (asyncio.TimeoutError, Exception) as exc:
        logger.debug("frame @%.1fs: %s", seek_sec, exc)
    return b""


async def _gather_frames(stream_url: str, duration: float) -> list[bytes]:
    """
    Извлекает кадры в 5 позициях параллельно:
      0.5s, 25%, 50%, 90%, последние 2.5 сек.
    Последние позиции — для QR-кодов (их часто ставят в конце).
    """
    if not stream_url:
        return []
    d = max(duration, 6.0)
    positions = sorted(set([
        0.5,
        round(d * 0.25, 1),
        round(d * 0.50, 1),
        round(d * 0.90, 1),
        max(0.5, round(d - 2.5, 1)),
    ]))
    raw_results = await asyncio.gather(
        *[_extract_one_frame(stream_url, p) for p in positions],
        return_exceptions=True,
    )
    return [r for r in raw_results if isinstance(r, bytes) and r]


# ── Извлечение аудио через ffmpeg pipe ────────────────────────────────────────

async def _extract_audio_bytes(audio_url: str) -> bytes:
    """
    Скачивает первые _AUDIO_MAX_SEC секунд аудио как float32 PCM 16kHz mono.
    55 сек × 16000 × 4 байт ≈ 3.52 MB — не скачивается всё видео.
    """
    if not audio_url:
        return b""
    cmd = [
        "ffmpeg", "-y",
        "-i", audio_url,
        "-t", str(_AUDIO_MAX_SEC),
        "-f", "f32le",
        "-ar", str(_AUDIO_SR),
        "-ac", "1",
        "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=50.0)
        return stdout
    except (asyncio.TimeoutError, Exception) as exc:
        logger.debug("audio extract: %s", exc)
        return b""


# ── CPU-bound анализ (в ThreadPoolExecutor) ───────────────────────────────────

def _analyze_frames_sync(raw_frames: list[bytes]) -> VisualScanResult:
    """
    OpenCV анализ кадров:
      • Split-screen: сильная горизонтальная линия в средней полосе (Sobel Y).
      • Push-overlay: широкий белый прямоугольник в верхних 20% кадра.
      • QR-коды: cv2.QRCodeDetector на каждом кадре.
      • UBT: EasyOCR (множители, кнопки, TG) + стрелки / полоса «банк» (detect_visual_hooks).
    Блокирующий — вызывать через executor.
    """
    result = VisualScanResult()
    if not raw_frames or not _CV2_OK:
        return result

    split_votes = 0
    push_votes = 0
    qr_detector = cv2.QRCodeDetector()
    ocr_labels_ordered: list[str] = []
    frame_arrays: list[np.ndarray] = []

    for raw in raw_frames:
        if len(raw) != _FRAME_BYTES:
            continue
        try:
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(_FRAME_H, _FRAME_W, 3)
            result.frames_analyzed += 1
            frame_arrays.append(frame)

            # ── QR-детект ─────────────────────────────────────────────────────
            data, _, _ = qr_detector.detectAndDecode(frame)
            if data and data.strip():
                code = data.strip()
                if code not in result.qr_codes:
                    result.qr_codes.append(code)

            # ── Split-screen детект ───────────────────────────────────────────
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            sobel_y = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)
            row_sums = np.abs(sobel_y).sum(axis=1)
            mean_val = row_sums.mean()
            frame_split = False

            if mean_val > 0:
                band_s = int(_FRAME_H * 0.35)
                band_e = int(_FRAME_H * 0.65)
                band = row_sums[band_s:band_e]
                peak = float(band.max())
                narrow = int((band > mean_val * 2.0).sum()) <= 14
                if peak > mean_val * 3.5 and narrow:
                    split_votes += 1
                    frame_split = True

            # ── Push-notification overlay (верхние 20% кадра) ────────────────
            top_h = int(_FRAME_H * 0.20)
            top_region = frame[:top_h, :, :]
            gray_top = cv2.cvtColor(top_region, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray_top, 210, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if w > _FRAME_W * 0.65 and h < _FRAME_H * 0.18 and w * h > 6_000:
                    push_votes += 1
                    break

            # ── OCR (UBT-триггеры) ────────────────────────────────────────────
            ocr_info = analyze_frame_text(frame, has_split_screen=frame_split)
            if ocr_info.get("is_gambling_combo"):
                result.ocr_gambling_combo = True
            for m in ocr_info.get("matches") or []:
                if m and m not in ocr_labels_ordered:
                    ocr_labels_ordered.append(m)

        except Exception as exc:
            logger.debug("frame analysis error: %s", exc)

    hooks = detect_visual_hooks(frame_arrays) if frame_arrays else {"hook_labels": []}
    result.visual_hook_labels = list(hooks.get("hook_labels") or [])
    result.ocr_hit_labels = ocr_labels_ordered[:40]

    n = result.frames_analyzed
    if n > 0:
        result.has_split_screen = split_votes >= max(1, n // 2)
        result.has_push_overlay = push_votes >= 1
        result.has_qr_code = bool(result.qr_codes)

        ocr_meaningful = any(
            x.startswith(("mult:", "btn:", "cta:", "combo:")) for x in result.ocr_hit_labels
        )
        vis_meaningful = bool(result.visual_hook_labels)

        if result.ocr_gambling_combo:
            result.video_risk = "high"
        elif ocr_meaningful and vis_meaningful:
            result.video_risk = "high"
        elif ocr_meaningful or vis_meaningful:
            result.video_risk = "medium"
        else:
            result.video_risk = "low"

        pos = (
            int(result.has_split_screen) * 30
            + int(result.has_qr_code) * 35
            + int(result.has_push_overlay) * 20
            + int(result.video_risk == "high") * 25
            + int(result.video_risk == "medium") * 12
        )
        result.confidence = min(0.95, 0.20 + (pos / 120) * 0.60 + n * 0.04)

    return result


def _transcribe_audio_sync(audio_bytes: bytes) -> AudioScanResult:
    """
    faster-whisper транскрипция → поиск триггерных фраз.
    Блокирующий — вызывать через executor.
    """
    result = AudioScanResult()
    if not audio_bytes or not _WHISPER_OK:
        return result

    model = _load_whisper_sync()
    if model is None:
        return result

    expected_min = _AUDIO_SR * 2 * 4   # минимум 2 секунды
    if len(audio_bytes) < expected_min:
        return result

    try:
        audio_arr = np.frombuffer(audio_bytes, dtype=np.float32)

        segments_gen, info = model.transcribe(
            audio_arr,
            language=None,          # авто-определение
            beam_size=1,            # greedy — быстро
            best_of=1,
            temperature=0.0,
            vad_filter=True,        # пропуск тишины
            vad_parameters={"min_silence_duration_ms": 400},
        )

        result.language_detected = str(info.language or "")
        parts: list[str] = []
        for seg in segments_gen:
            parts.append(seg.text.strip())

        full = " ".join(parts).lower().strip()
        result.transcript = full[:3000]

        found: list[str] = []
        for phrase in _AUDIO_TRIGGERS:
            if phrase in full and phrase not in found:
                found.append(phrase)
        result.trigger_phrases = found

        if found:
            result.confidence = min(0.95, 0.40 + len(found) * 0.12)
        elif full:
            result.confidence = 0.10   # транскрипт есть, триггеров нет

    except Exception as exc:
        logger.warning("_transcribe_audio_sync: %s", exc)

    return result


# ── Финальный скоринг ─────────────────────────────────────────────────────────

def _compute_media_score(visual: VisualScanResult, audio: AudioScanResult) -> tuple[int, list[str]]:
    score = 0
    flags: list[str] = []

    if visual.video_risk == "high":
        score += 40
        flags.append("risk:video_high")
    elif visual.video_risk == "medium":
        score += 18
        flags.append("risk:video_medium")

    if visual.ocr_gambling_combo:
        score += 35
        flags.append("ocr:gambling_combo")

    for lab in visual.ocr_hit_labels[:10]:
        score += 6
        flags.append(f"ocr:{lab[:50]}")

    for lab in visual.visual_hook_labels[:6]:
        score += 8
        flags.append(lab[:60])

    if visual.has_split_screen:
        score += 28
        flags.append("visual:split_screen")
    if visual.has_qr_code:
        score += 35
        for code in visual.qr_codes[:3]:
            flags.append(f"visual:qr:{code[:60]}")
    if visual.has_push_overlay:
        score += 20
        flags.append("visual:push_overlay")

    for phrase in audio.trigger_phrases[:6]:
        score += 18
        flags.append(f"audio:{phrase[:35]}")

    return min(100, score), flags


# ── Оркестратор одного задания ────────────────────────────────────────────────

async def _run_job(job: _ScanJob, executor: ThreadPoolExecutor) -> MediaScanResult:
    t0 = time.monotonic()
    result = MediaScanResult(video_id=job.video_id, video_url=job.url)

    try:
        loop = asyncio.get_running_loop()

        # 1. URL потоков (IO)
        video_stream, audio_stream, duration = await _get_stream_urls(job.url)
        if not video_stream and not audio_stream:
            result.error = "yt-dlp не вернул URL потока"
            return result

        effective_duration = duration or job.duration or 60.0

        # 2. Параллельно: кадры + аудио (IO)
        frames_task = asyncio.create_task(
            _gather_frames(video_stream, effective_duration)
        )
        audio_task = asyncio.create_task(
            _extract_audio_bytes(audio_stream)
        )
        raw_frames, audio_bytes = await asyncio.gather(frames_task, audio_task)

        # 3. CPU-анализ в ThreadPoolExecutor (не блочит event loop)
        visual, audio = await asyncio.gather(
            loop.run_in_executor(executor, _analyze_frames_sync, raw_frames),
            loop.run_in_executor(executor, _transcribe_audio_sync, audio_bytes),
        )

        result.visual = visual
        result.audio  = audio
        result.media_score, result.media_flags = _compute_media_score(visual, audio)

    except Exception as exc:
        logger.exception("media_scanner job %s: %s", job.video_id, exc)
        result.error = f"{type(exc).__name__}: {str(exc)[:250]}"

    result.scan_duration_sec = round(time.monotonic() - t0, 2)
    logger.info(
        "media_scan %s: score=%d flags=%s dur=%.1fs err=%s",
        job.video_id, result.media_score, result.media_flags,
        result.scan_duration_sec, result.error,
    )
    return result


# ── Очередь сканирования ──────────────────────────────────────────────────────

class MediaScanQueue:
    """
    Глобальная очередь медиа-сканирования.
    Используй get_media_scan_queue() вместо прямого создания.
    """

    def __init__(
        self,
        num_workers: int = _SCAN_WORKERS,
        thread_pool_size: int = _SCAN_THREADS,
    ) -> None:
        self._queue: asyncio.Queue[_ScanJob] = asyncio.Queue(maxsize=100)
        self._futures: dict[str, asyncio.Future[MediaScanResult]] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=thread_pool_size,
            thread_name_prefix="media_scan",
        )
        self._workers: list[asyncio.Task[None]] = []
        self._num_workers = num_workers
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        # Предзагрузка Whisper в фоне (первая загрузка ~5-30с в зависимости от кэша)
        # run_in_executor возвращает Future, create_task ждёт корутину → оборачиваем
        loop = asyncio.get_running_loop()

        async def _preload_whisper() -> None:
            await loop.run_in_executor(self._executor, _load_whisper_sync)

        asyncio.create_task(_preload_whisper(), name="whisper-preload")
        for i in range(self._num_workers):
            t = asyncio.create_task(
                self._worker_loop(i), name=f"media-scan-{i}"
            )
            self._workers.append(t)
        logger.info("MediaScanQueue started (%d workers, %d threads)", self._num_workers, _SCAN_THREADS)

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._executor.shutdown(wait=False)
        self._started = False
        logger.info("MediaScanQueue stopped")

    async def submit(
        self,
        video_id: str,
        url: str,
        duration: float = 0.0,
    ) -> asyncio.Future[MediaScanResult]:
        """
        Ставит задачу в очередь.
        • Если этот video_id уже в работе → возвращает существующий Future.
        • Если результат готов → тот же Future (можно снова await-ить).
        • Не блокирует — возвращает сразу.
        """
        if not self._started:
            await self.start()

        # Переиспользуем незавершённый Future
        existing = self._futures.get(video_id)
        if existing is not None and not existing.done():
            return existing

        loop = asyncio.get_running_loop()
        future: asyncio.Future[MediaScanResult] = loop.create_future()
        self._futures[video_id] = future

        job = _ScanJob(video_id=video_id, url=url, duration=duration, future=future)
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            future.set_exception(RuntimeError("Media scan queue is full (max 100 jobs)"))

        return future

    def get_result(self, video_id: str) -> MediaScanResult | None:
        """Синхронная проверка готового результата (для poll-эндпоинта)."""
        fut = self._futures.get(video_id)
        if fut is None or not fut.done() or fut.cancelled():
            return None
        try:
            return fut.result()
        except Exception:
            return None

    def is_pending(self, video_id: str) -> bool:
        fut = self._futures.get(video_id)
        return fut is not None and not fut.done()

    def queue_size(self) -> int:
        return self._queue.qsize()

    async def _worker_loop(self, worker_id: int) -> None:
        logger.debug("media-scan worker-%d started", worker_id)
        while True:
            try:
                job: _ScanJob = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("worker-%d queue.get: %s", worker_id, exc)
                continue

            try:
                scan_result = await _run_job(job, self._executor)
                if not job.future.done():
                    job.future.set_result(scan_result)
            except Exception as exc:
                logger.exception("worker-%d job %s: %s", worker_id, job.video_id, exc)
                if not job.future.done():
                    job.future.set_exception(exc)
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

        logger.debug("media-scan worker-%d stopped", worker_id)


# ── Singleton ─────────────────────────────────────────────────────────────────

_queue_instance: MediaScanQueue | None = None
_queue_init_lock = asyncio.Lock()


def get_media_scan_queue() -> MediaScanQueue:
    """Возвращает (или создаёт) глобальную очередь сканирования."""
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = MediaScanQueue()
    return _queue_instance
