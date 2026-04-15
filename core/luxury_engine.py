"""
Uniqualizer / Luxury Engine — реальные пресеты обработки + шаблоны монтажа.

Пресеты (standard / soft / deep / ultra):
  Реальные FFmpeg-параметры: saturation, contrast, brightness, atempo,
  CRF/CQ кодека, битрейт аудио. Не декоративные — реально разные.

Шаблоны монтажа (default / reaction / news / story / ugc):
  Разная структура filter_complex на один проход FFmpeg.

Субтитры:
  Короткий CTA-текст — временный .ass + фильтр subtitles= (libass), стабильно для кириллицы.
  Эмодзи — отдельный шрифт (Segoe UI Emoji / Noto Color Emoji) без обводки, иначе libass рисует их как контурный текст.
  PlayResX/Y в .ass совпадают с итоговым кадром — иначе размер шрифта в ASS масштабируется нелинейно относительно «пикселей» в UI.
  Опционально: папка core/fonts/ или NEORENDER_FONTS_DIR — subtitles:fontsdir= для .ttf/.otf (Pretendard и т.д.).
  Таймкодный SRT — вторым проходом subtitles= поверх [vout] (при необходимости).

Второй вход: картинка (PNG/JPG/…) или видео; режимы смешивания через filter blend.

Запуск FFmpeg через core.ffmpeg_runner (асинхронно, UI не блокируется).
NVENC → libx264 fallback.
NEORENDER_DISABLE_NVENC=1 — сразу CPU (libx264), если драйвер GPU ломает NVENC.
После рендера: опционально pHash vs оригинал (Pillow+ImageHash), предупреждение если слишком похоже.
Обрезка чёрного/тишины: blackdetect+silencedetect → -ss/-t на основном входе.
Аудио: NEORENDER_AUDIO_LAME_ROUNDTRIP_P — вероятность цепочки libmp3lame → AAC после рендера.
Микро-resize в фильтре: лёгкий scale «туда-обратно» для бинарного отпечатка.
Ошибки: {"status": "error", "message": "...по-русски"}.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import random
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core import ffmpeg_hardening as _hard
from core import ffmpeg_runner as _ff
from core import perceptual_video_hash as _ph

logger = logging.getLogger(__name__)

_CANCEL_MSG = "Отменено пользователем"


def _cancelled(ev: asyncio.Event | None) -> bool:
    return ev is not None and ev.is_set()

_DEFAULT_DEVICE = "Samsung SM-S928N"

# Модель в метаданных + согласованные manufacturer / QuickTime make (отпечаток «как с телефона»).
# Ключ — ровно то значение, что уходит в com.android.model / quicktime.model.
DEVICE_MODEL_FINGERPRINTS: dict[str, dict[str, str]] = {
    "Samsung SM-S928N": {
        "label": "Samsung Galaxy S24 Ultra",
        "android_manufacturer": "Samsung",
        "quicktime_make": "Samsung",
    },
    "Samsung SM-S911B": {
        "label": "Samsung Galaxy S23",
        "android_manufacturer": "Samsung",
        "quicktime_make": "Samsung",
    },
    "Google Pixel 9": {
        "label": "Google Pixel 9",
        "android_manufacturer": "Google",
        "quicktime_make": "Google",
    },
    "Google Pixel 8": {
        "label": "Google Pixel 8",
        "android_manufacturer": "Google",
        "quicktime_make": "Google",
    },
    "Google Pixel 7": {
        "label": "Google Pixel 7",
        "android_manufacturer": "Google",
        "quicktime_make": "Google",
    },
    "2211133G": {
        "label": "Xiaomi 13 (глобальная)",
        "android_manufacturer": "Xiaomi",
        "quicktime_make": "Xiaomi",
    },
    "iPhone 16 Pro": {
        "label": "Apple iPhone 16 Pro",
        "android_manufacturer": "Apple",
        "quicktime_make": "Apple",
    },
    "iPhone 15 Pro": {
        "label": "Apple iPhone 15 Pro",
        "android_manufacturer": "Apple",
        "quicktime_make": "Apple",
    },
    "iPhone 14": {
        "label": "Apple iPhone 14",
        "android_manufacturer": "Apple",
        "quicktime_make": "Apple",
    },
}


def get_device_model_presets() -> dict[str, str]:
    """Список для UI: значение модели → подпись."""
    return {model: info["label"] for model, info in DEVICE_MODEL_FINGERPRINTS.items()}


def resolve_device_fingerprint(device_model: str | None) -> tuple[str, str, str]:
    """
    Возвращает (model, com.android.manufacturer, com.apple.quicktime.make).
    Для неизвестной строки — эвристика по подстрокам, иначе как раньше Samsung.
    """
    m = str(device_model or "").strip() or _DEFAULT_DEVICE
    info = DEVICE_MODEL_FINGERPRINTS.get(m)
    if info:
        return m, info["android_manufacturer"], info["quicktime_make"]
    low = m.lower()
    if "iphone" in low or "ipad" in low:
        return m, "Apple", "Apple"
    if "pixel" in low:
        return m, "Google", "Google"
    if "xiaomi" in low or "redmi" in low or "poco" in low:
        return m, "Xiaomi", "Xiaomi"
    if "oppo" in low:
        return m, "OPPO", "OPPO"
    if "oneplus" in low or "one plus" in low:
        return m, "OnePlus", "OnePlus"
    if "huawei" in low or "honor" in low:
        return m, "HUAWEI", "HUAWEI"
    if "nothing" in low:
        return m, "Nothing", "Nothing"
    if "motorola" in low or "moto " in low:
        return m, "motorola", "motorola"
    return m, "Samsung", "Samsung"


_GEO_PROFILES: dict[str, tuple[float, float]] = {
    "busan":    (35.1796, 129.0756),
    "seoul":    (37.5665, 126.9780),
    "incheon":  (37.4563, 126.7052),
    "daegu":    (35.8714, 128.6014),
    "daejeon":  (36.3504, 127.3845),
    "gwangju":  (35.1595, 126.8526),
    "suwon":    (37.2636, 127.0286),
    "jeju":     (33.4996, 126.5312),
    "ulsan":    (35.5384, 129.3114),
    "pohang":   (36.0190, 129.3435),
}

# Подписи для UI (ключ совпадает с geo_profile / _GEO_PROFILES).
_GEO_PROFILE_LABELS: dict[str, str] = {
    "busan":   "Пусан",
    "seoul":   "Сеул",
    "incheon": "Инчхон",
    "daegu":   "Тэгу",
    "daejeon": "Тэджон",
    "gwangju": "Кванджу",
    "suwon":   "Сувон",
    "jeju":    "Чеджу",
    "ulsan":   "Ульсан",
    "pohang":  "Пхохан",
}

# ─── Реальные пресеты ────────────────────────────────────────────────────────
RENDER_PRESETS: dict[str, dict[str, Any]] = {
    "standard": {
        "label":         "Стандарт",
        "desc":          "Быстро, минимальная обработка — для быстрой проверки",
        "saturation":    (1.02, 1.12),
        "contrast":      (0.97, 1.04),
        "brightness":    (-0.03, 0.03),
        "atempo":        (0.997, 1.003),
        "crf_x264":      26,
        "preset_x264":   "veryfast",
        "cq_nvenc":      28,
        "audio_bitrate": "128k",
        "unsharp":       False,
        "zoom":          False,
    },
    "soft": {
        "label":         "Мягко",
        "desc":          "Почти как оригинал: малые правки цвета/темпа — меньше «пережатости»",
        "saturation":    (1.01, 1.06),
        "contrast":      (0.99, 1.02),
        "brightness":    (-0.02, 0.02),
        "atempo":        (0.9985, 1.0015),
        "crf_x264":      22,
        "preset_x264":   "medium",
        "cq_nvenc":      26,
        "audio_bitrate": "160k",
        "unsharp":       False,
        "zoom":          False,
    },
    "deep": {
        "label":         "Глубокий",
        "desc":          "Оптимальный баланс уникальности и качества",
        "saturation":    (1.20, 1.80),
        "contrast":      (0.95, 1.15),
        "brightness":    (-0.08, 0.08),
        "atempo":        (0.980, 1.020),
        "crf_x264":      23,
        "preset_x264":   "fast",
        "cq_nvenc":      24,
        "audio_bitrate": "192k",
        "unsharp":       True,   # лёгкое повышение чёткости
        "zoom":          False,
    },
    "ultra": {
        "label":         "Ультра",
        "desc":          "Максимальная переработка + лучшее качество рендера",
        "saturation":    (1.35, 2.00),
        "contrast":      (0.90, 1.20),
        "brightness":    (-0.10, 0.10),
        "atempo":        (0.975, 1.025),
        "crf_x264":      20,
        "preset_x264":   "slow",
        "cq_nvenc":      20,
        "audio_bitrate": "256k",
        "unsharp":       True,
        "zoom":          True,   # лёгкий зум (1.02–1.06)
    },
}

# ─── Шаблоны монтажа ─────────────────────────────────────────────────────────
# PNG: поверх видео (как водяной знак) или подложка (PNG на весь кадр, видео сверху).
OVERLAY_MODES = frozenset({"on_top", "under_video"})
# Позиция PNG при режиме on_top (центр / края).
OVERLAY_POSITIONS = frozenset(
    {"center", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right"}
)
# Стиль вшитых SRT и обводки CTA в ASS.
SUBTITLE_STYLES = frozenset({"default", "readable"})
# Режимы filter blend (полный кадр; позиция слоя не используется, кроме normal + opacity≈1).
OVERLAY_BLEND_MODES = frozenset(
    {
        "normal",
        "linekey",
        "screen",
        "darken",
        "multiply",
        "overlay",
        "hardlight",
        "softlight",
        "difference",
        "exclusion",
        "lighten",
        "addition",
    }
)
OVERLAY_BLEND_LABELS: dict[str, str] = {
    "normal":     "По умолчанию",
    "linekey":    "Белые линии (убрать черный фон)",
    "screen":     "Экран",
    "darken":     "Затемнение",
    "multiply":   "Умножение",
    "overlay":    "Перекрытие",
    "hardlight":  "Жёсткий свет",
    "softlight":  "Мягкий свет",
    "difference": "Разница",
    "exclusion":  "Исключение",
    "lighten":    "Осветление",
    "addition":   "Добавление",
}
_STATIC_OVERLAY_IMAGES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_OVERLAY_VIDEO_LIKE = frozenset({".mp4", ".mov", ".webm", ".mkv", ".avi", ".gif"})
_SUPPORTED_OVERLAY_MEDIA = _STATIC_OVERLAY_IMAGES | _OVERLAY_VIDEO_LIKE

UNIQUIZE_INTENSITIES = frozenset({"low", "med", "high"})


MONTAGE_TEMPLATES: dict[str, dict[str, str]] = {
    "default": {
        "label": "Стандарт",
        "desc":  "Один поток + прозрачный overlay",
    },
    "reaction": {
        "label": "Реакция",
        "desc":  "9:16 split-screen: оригинал сверху, зеркало снизу",
    },
    "news": {
        "label": "Новости",
        "desc":  "Нижняя плашка + текст-callout",
    },
    "story": {
        "label": "Story",
        "desc":  "Зум центра, вертикальный кроп 9:16",
    },
    "ugc": {
        "label": "UGC",
        "desc":  "Минимум фильтров, органичный стиль + виньетка",
    },
}


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def _ffmpeg_stderr_hint(err: bytes, limit: int = 400) -> str:
    """Короткая строка из stderr для сообщения пользователю (без traceback)."""
    if not err:
        return ""
    t = err.decode("utf-8", errors="replace").replace("\r", " ").strip()
    needles = (
        "error",
        "invalid",
        "failed",
        "cannot",
        "unable to",
        "could not",
        "unknown",
        "no such",
        "not found",
        "broken",
        "impossible",
        "decoder",
        "encoder",
        "codec",
        "unsupported",
        "matches no streams",
        "conversion failed",
        "divisible",
        "pixel format",
        "does not exist",
        "permission denied",
        "filter",
    )
    for line in reversed(t.split("\n")):
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if any(x in low for x in needles):
            if len(s) > limit:
                return s[: limit - 1] + "…"
            return s
    if len(t) > limit:
        return "…" + t[-limit:]
    return t


def _normalize_preset(preset: str | None) -> str:
    key = str(preset or "deep").strip().lower()
    return key if key in RENDER_PRESETS else "deep"


def _normalize_template(template: str | None) -> str:
    key = str(template or "default").strip().lower()
    return key if key in MONTAGE_TEMPLATES else "default"


def _normalize_uniqualize_intensity(intensity: str | None) -> str:
    k = str(intensity or "med").strip().lower()
    return k if k in UNIQUIZE_INTENSITIES else "med"


def _uniqualize_interval_k(intensity: str | None) -> float:
    """Множитель полуинтервала вокруг центра: low — уже разброс, high — шире."""
    return {"low": 0.62, "med": 1.0, "high": 1.38}.get(
        _normalize_uniqualize_intensity(intensity), 1.0
    )


def _scaled_uniform_interval(lo: float, hi: float, k: float) -> tuple[float, float]:
    mid = (lo + hi) / 2.0
    half = (hi - lo) / 2.0 * k
    return mid - half, mid + half


def _normalize_geo_profile(geo_profile: str | None) -> str:
    key = str(geo_profile or "busan").strip().lower()
    return key if key in _GEO_PROFILES else "busan"


def _parse_custom_geo(raw: str) -> tuple[float, float] | None:
    """
    Разбор произвольных координат вида «37.5665,126.9780» или «+37.5665+126.9780».
    Возвращает (lat, lon) или None при ошибке.
    """
    import re as _re
    raw = raw.strip().replace(" ", "")
    m = _re.match(r"^([+-]?\d+(?:\.\d+)?)[,;/]([+-]?\d+(?:\.\d+)?)$", raw)
    if m:
        try:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
        except ValueError:
            pass
    return None


def _normalize_overlay_mode(mode: str | None) -> str:
    k = str(mode or "on_top").strip().lower().replace("-", "_")
    aliases = {"behind": "under_video", "background": "under_video", "bg": "under_video", "under": "under_video"}
    k = aliases.get(k, k)
    return k if k in OVERLAY_MODES else "on_top"


def _normalize_overlay_position(pos: str | None) -> str:
    k = str(pos or "center").strip().lower()
    return k if k in OVERLAY_POSITIONS else "center"


def _normalize_subtitle_style(style: str | None) -> str:
    k = str(style or "default").strip().lower()
    aliases = {"bold": "readable", "heavy": "readable", "outline": "readable"}
    k = aliases.get(k, k)
    return k if k in SUBTITLE_STYLES else "default"


def _overlay_xy_expr(position: str) -> str:
    """Координаты для overlay при режиме on_top (PNG поверх видео)."""
    p = _normalize_overlay_position(position)
    m = 20
    if p == "top":
        return f"(main_w-overlay_w)/2:{m}"
    if p == "bottom":
        return f"(main_w-overlay_w)/2:main_h-overlay_h-{m}"
    if p == "top_left":
        return f"{m}:{m}"
    if p == "top_right":
        return f"main_w-overlay_w-{m}:{m}"
    if p == "bottom_left":
        return f"{m}:main_h-overlay_h-{m}"
    if p == "bottom_right":
        return f"main_w-overlay_w-{m}:main_h-overlay_h-{m}"
    return "(main_w-overlay_w)/2:(main_h-overlay_h)/2"


def _overlay_media_chain(
    base_tag: str,
    out_tag: str,
    overlay_mode: str,
    overlay_position: str,
    uid: int,
    blend_mode: str = "normal",
    opacity: float = 1.0,
) -> str:
    """
    Свести основное видео (base_tag) и второй вход [1:v] (картинка или видео).

    under_video: слой на весь кадр снизу, основной ролик сверху (классический overlay).
    on_top + normal + opacity≈1: геометрический watermark (позиция).
    on_top + иначе: filter blend на весь кадр (позиция игнорируется).
    """
    mode = _normalize_overlay_mode(overlay_mode)
    bm = _normalize_overlay_blend(blend_mode)
    op = max(0.0, min(1.0, float(opacity)))
    scaled = f"ovsc{uid}"
    mainc = f"ovmn{uid}"
    bg = f"ovbg{uid}"
    fg = f"ovfg{uid}"

    if mode == "under_video":
        return (
            f"[1:v][{base_tag}]scale2ref=w=iw:h=ih[{bg}][{fg}];"
            f"[{bg}][{fg}]overlay=0:0:format=auto:shortest=1[{out_tag}]"
        )

    use_blend = bm != "normal" or op < 0.995
    if not use_blend:
        xy = _overlay_xy_expr(overlay_position)
        return f"[{base_tag}][1:v]overlay={xy}:format=auto:shortest=1[{out_tag}]"

    # Спец-режим «линии»: вырезаем чёрный фон у слоя и кладём только светлые контуры.
    if bm == "linekey":
        keyed = f"ovky{uid}"
        return (
            f"[1:v][{base_tag}]scale2ref=w=iw:h=ih[{scaled}][{mainc}];"
            f"[{scaled}]format=rgba,colorkey=0x000000:0.18:0.08,colorchannelmixer=aa={op:.4f}[{keyed}];"
            f"[{mainc}][{keyed}]overlay=0:0:format=auto:shortest=1[{out_tag}]"
        )

    # Полный кадр: масштабируем слой под базу, смешиваем.
    # Для режимов addition/screen opacity применяем через colorchannelmixer (blend их не поддерживает напрямую).
    if bm == "addition":
        faded = f"ovfd{uid}"
        return (
            f"[1:v][{base_tag}]scale2ref=w=iw:h=ih[{scaled}][{mainc}];"
            f"[{scaled}]colorchannelmixer=aa={op:.4f}[{faded}];"
            f"[{mainc}][{faded}]blend=all_mode=addition:shortest=1[{out_tag}]"
        )
    return (
        f"[1:v][{base_tag}]scale2ref=w=iw:h=ih[{scaled}][{mainc}];"
        f"[{mainc}][{scaled}]blend=all_mode={bm}:all_opacity={op:.4f}:shortest=1[{out_tag}]"
    )


def _srt_force_style_escaped(
    subtitle_style: str,
    subtitle_font: str | None = None,
    subtitle_font_size: int | None = None,
) -> str:
    """Строка для subtitles=...:force_style= (запятые экранированы для filtergraph)."""
    st = _normalize_subtitle_style(subtitle_style)
    readable = st == "readable"
    if readable:
        default_fs, outline_s, shadow_s, margin_v = 22, "2.5", "0.8", 36
    else:
        default_fs, outline_s, shadow_s, margin_v = 18, "1", "0", 22

    fs = int(subtitle_font_size) if subtitle_font_size and int(subtitle_font_size) > 0 else default_fs
    fs = max(8, min(200, fs))

    parts: list[str] = []
    fn = (subtitle_font or "").strip()
    if fn:
        fn_safe = fn.replace("\\", "").replace(",", " ").strip()
        if fn_safe:
            parts.append(f"FontName={fn_safe}")
    parts.append(f"FontSize={fs}")
    parts.append(f"Outline={outline_s}")
    parts.append(f"Shadow={shadow_s}")
    parts.append(f"MarginV={margin_v}")
    parts.append("Alignment=2")
    joined = ",".join(parts)
    return joined.replace(",", r"\,")


def _random_location_exif(geo_profile: str | None = None, jitter: float = 0.05) -> str:
    raw = str(geo_profile or "").strip()
    custom = _parse_custom_geo(raw)
    if custom:
        base_lat, base_lon = custom
    else:
        base_lat, base_lon = _GEO_PROFILES[_normalize_geo_profile(raw)]
    safe_jitter = max(0.001, min(0.5, float(jitter or 0.05)))
    lat = base_lat + random.uniform(-safe_jitter, safe_jitter)
    lon = base_lon + random.uniform(-safe_jitter, safe_jitter)
    return f"+{lat:.4f}+{lon:.4f}/"


def get_geo_profiles() -> dict[str, dict[str, float | str]]:
    """Координаты + label для выпадающего списка в UI."""
    out: dict[str, dict[str, float | str]] = {}
    for name, (lat, lng) in _GEO_PROFILES.items():
        out[name] = {
            "lat": lat,
            "lng": lng,
            "label": _GEO_PROFILE_LABELS.get(name, name.replace("_", " ").title()),
        }
    return out


def get_render_presets() -> dict[str, dict[str, Any]]:
    return {k: {"label": v["label"], "desc": v["desc"]} for k, v in RENDER_PRESETS.items()}


def get_montage_templates() -> dict[str, dict[str, str]]:
    return MONTAGE_TEMPLATES.copy()


def get_montage_template_ids() -> list[str]:
    """Стабильный порядок ключей (для чередования в пакете variants)."""
    return list(MONTAGE_TEMPLATES.keys())


def get_uniqualize_intensity_modes() -> dict[str, dict[str, str]]:
    return {
        "low": {"label": "Мягко", "desc": "Узкий разброс цвета, темпа и эффектов"},
        "med": {"label": "Норма", "desc": "Как задумано в пресете"},
        "high": {"label": "Сильнее", "desc": "Шире разброс между рендерами"},
    }


def get_overlay_blend_modes() -> dict[str, str]:
    """Ключ → подпись для UI (только поддерживаемые режимы)."""
    return {k: OVERLAY_BLEND_LABELS[k] for k in sorted(OVERLAY_BLEND_MODES) if k in OVERLAY_BLEND_LABELS}


def _normalize_overlay_blend(mode: str | None) -> str:
    k = str(mode or "normal").strip().lower().replace("-", "_")
    aliases = {
        "по_умолчанию": "normal",
        "по умолчанию": "normal",
        "белые_линии": "linekey",
        "белые линии": "linekey",
        "убрать_черный_фон": "linekey",
        "убрать черный фон": "linekey",
        "линии": "linekey",
        "line_art": "linekey",
        "lineart": "linekey",
        "повысить_яркость": "screen",
        "повысить яркость": "screen",
        "экран": "screen",
        "затемнение": "darken",
        "наложение": "screen",
        "жесткий_свет": "hardlight",
        "жесткий свет": "hardlight",
        "мягкий_свет": "softlight",
        "мягкий свет": "softlight",
        "затемнение_основы": "darken",
        "затемнение основы": "darken",
        "линейное_затемнение": "darken",
        "линейное затемнение": "darken",
        "осветление_основы": "screen",
        "осветление основы": "screen",
        # Совместимость со старыми ключами UI/БД.
        "burn": "multiply",
        "dodge": "screen",
        "colorburn": "multiply",
        "colordodge": "screen",
        # Старые русские алиасы.
        "осветление": "lighten",
        "умножение": "multiply",
        "перекрытие": "overlay",
        "жёсткий_свет": "hardlight",
        "мягкий_свет": "softlight",
        "разница": "difference",
        "исключение": "exclusion",
        "добавление": "addition",
    }
    k = aliases.get(k, k)
    return k if k in OVERLAY_BLEND_MODES else "normal"


def overlay_ffmpeg_input_args(overlay_path: Path) -> list[str]:
    """
    Второй вход FFmpeg: картинки зацикливаем; короткое видео-слой — stream_loop для длины основного ролика.
    """
    p = str(overlay_path.resolve())
    suf = overlay_path.suffix.lower()
    if suf in _STATIC_OVERLAY_IMAGES:
        return ["-loop", "1", "-i", p]
    if suf in _OVERLAY_VIDEO_LIKE:
        return ["-stream_loop", "-1", "-i", p]
    return ["-i", p]


def _is_supported_overlay_media(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_OVERLAY_MEDIA


def _fake_creation_time() -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 72))
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _sanitize_overlay_text(text: str, limit: int = 500) -> str:
    """
    Одна строка CTA, без управляющих символов, ограничение длины.
    Для длинных субтитров используйте SRT.
    """
    s = " ".join(str(text or "").split())
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s


def _escape_drive_colon_ffmpeg_path(normalized_path: str) -> str:
    """
    После приведения к виду C:/... — экранировать ':' у буквы диска для filtergraph.

    FFmpeg в drawtext/subtitles воспринимает ':' как разделитель опций; без экранирования
    получается «Could not load font C» и т.п. (типичная проблема на Windows).
    """
    p = normalized_path.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    return p.replace("'", r"\'")


def _escape_filter_path_for_windows(path: str) -> str:
    """Абсолютный путь для drawtext fontfile=/textfile= и фильтра subtitles."""
    p = str(Path(path).resolve()).replace("\\", "/")
    return _escape_drive_colon_ffmpeg_path(p)


def _escape_subtitles_path(path: str) -> str:
    """Путь для фильтра subtitles (тот же экранинг, что для drawtext)."""
    return _escape_filter_path_for_windows(path)


def _audio_lame_roundtrip_probability() -> float:
    """NEORENDER_AUDIO_LAME_ROUNDTRIP_P=0 отключает; по умолчанию 0.25 (двойной перекод аудио MP3→AAC)."""
    raw = (os.environ.get("NEORENDER_AUDIO_LAME_ROUNDTRIP_P") or "0.25").strip().lower()
    if raw in ("0", "none", "off", ""):
        return 0.0
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.25


# Диапазоны pitch-сдвига по пресету (asetrate trick).
# Chromaprint/ACR устойчив до ~±3–4%; deep/ultra намеренно выходят за этот порог.
# standard/soft повышены до ±2.5%/±3% — иначе они попадают в зону уверенного матча Chromaprint.
_PITCH_RANGE: dict[str, tuple[float, float]] = {
    "standard": (0.975, 1.025),   # ±2.5% — выходим за границу уверенного матча
    "soft":     (0.970, 1.030),   # ±3.0% — на пороге Chromaprint, сохраняем качество
    "deep":     (0.960, 1.040),   # ±4% — стабильно ломает Chromaprint
    "ultra":    (0.948, 1.052),   # ±5.2% — максимальный сдвиг без слышимых артефактов
}

# Циррилица → латинские омоглифы (визуально неотличимы в стандартных шрифтах).
_CYR_HOMOGLYPHS: dict[str, str] = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "у": "y",
}
_ZWS = "\u200b"   # zero-width space
_ZWNJ = "\u200c"  # zero-width non-joiner (тоже невидимый)


def _homoglyph_spin(text: str, prob: float = 0.14) -> str:
    """
    Случайная замена Кириллических символов на Latin-омоглифы + вставка
    zero-width пробелов (U+200B) в ~7% мест между буквами.
    Текст выглядит идентично; ASS/бинарник — уникален.
    """
    out: list[str] = []
    for i, ch in enumerate(text):
        sub = _CYR_HOMOGLYPHS.get(ch)
        out.append(sub if sub and random.random() < prob else ch)
        if ch.isalpha() and random.random() < 0.07:
            out.append(_ZWS if random.random() < 0.5 else _ZWNJ)
    return "".join(out)


def spin_yt_metadata(title: str, description: str) -> tuple[str, str]:
    """
    Уникализация YouTube-метаданных для каждого таска:
      - гомоглифы + ZWS в тайтле
      - случайный невидимый trailing-символ в тайтле
      - гомоглифы в описании (меньшая вероятность)
    Не меняет видимый текст — только бинарник.
    """
    _trail = ["\u200b", "\u200c", "\u2060", "\ufeff", ""]
    spun_title = _homoglyph_spin(str(title or ""), prob=0.12) + random.choice(_trail)
    spun_desc  = _homoglyph_spin(str(description or ""), prob=0.07)
    return spun_title, spun_desc


def _pick_micro_resize_pixels() -> tuple[int, int]:
    """Лёгкий «туда-обратно» resize для смены бинарника без заметной картинки."""
    if random.random() < 0.38:
        return (0, 0)
    opts = [(2, 0), (-2, 0), (0, 2), (0, -2), (2, 2), (-2, -2), (4, 0), (0, 4), (-4, 0)]
    return random.choice(opts)


async def _try_lame_aac_roundtrip(outp: Path, audio_bitrate: str) -> bool:
    """Извлечь дорожку в MP3 (lame) и пересобрать контейнер с AAC — иной аудио-fingerprint."""
    ff = _ff.ffmpeg_bin()
    rid = random.randint(1, 10**9)
    tmp_mp3 = outp.parent / f"_neo_lame_{rid}.mp3"
    tmp_mp4 = outp.parent / f"_neo_lame_{rid}.mp4"
    try:
        c1, _, _ = await _ff.run_ffmpeg(
            [
                ff,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(outp),
                "-vn",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(tmp_mp3),
            ]
        )
        if c1 != 0 or not tmp_mp3.is_file() or tmp_mp3.stat().st_size < 32:
            return False
        c2, _, _ = await _ff.run_ffmpeg(
            [
                ff,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(outp),
                "-i",
                str(tmp_mp3),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
                str(tmp_mp4),
            ]
        )
        if c2 != 0 or not tmp_mp4.is_file() or tmp_mp4.stat().st_size < 32:
            return False
        os.replace(str(tmp_mp4), str(outp))
        return True
    except OSError:
        logger.warning("lame→aac roundtrip: не удалось заменить файл", exc_info=True)
        return False
    finally:
        tmp_mp3.unlink(missing_ok=True)
        try:
            tmp_mp4.unlink(missing_ok=True)
        except OSError:
            pass


def build_luxury_encode_argv(
    *,
    ffmpeg_exe: str,
    input_video: Path,
    overlay_media: Path,
    filter_complex: str,
    video_map: str,
    with_audio: bool,
    audio_bitrate: str,
    common_meta: list[str],
    video_codec: str,
    extra_video_encoder_args: list[str],
    output_path: Path,
    vsync_mode: str | None = None,
    main_input_ss_sec: float | None = None,
    main_input_t_sec: float | None = None,
) -> list[str]:
    """Полная argv одного прохода кодирования (тесты, dry_run, отладка)."""
    if vsync_mode is None:
        # Включается только явно через env, чтобы не ломать существующий пайплайн.
        vsync_mode = (os.environ.get("NEORENDER_VSYNC_MODE") or "").strip() or None
    return _hard.build_ffmpeg_encode_argv(
        ffmpeg_exe=ffmpeg_exe,
        input_video=input_video,
        overlay_input_args=overlay_ffmpeg_input_args(overlay_media),
        filter_complex=filter_complex,
        video_map=video_map,
        with_audio=with_audio,
        audio_bitrate=audio_bitrate,
        common_meta=common_meta,
        video_codec=video_codec,
        extra_video_encoder_args=extra_video_encoder_args,
        output_path=output_path,
        vsync_mode=vsync_mode,
        main_input_ss_sec=main_input_ss_sec,
        main_input_t_sec=main_input_t_sec,
    )


# ─── Filter graph builders ────────────────────────────────────────────────────

def _eq_chain(
    sat: float,
    con: float,
    br: float,
    unsharp: bool,
    zoom: bool,
    uniqual_k: float = 1.0,
    trim_frames: int = 0,
    trim_end_frames: int = 0,
    total_frames: int | None = None,
    hue_deg: float = 0.0,
    fps_out: float | None = None,
    colorbalance: str = "",
    micro_dw: int = 0,
    micro_dh: int = 0,
    curves: str = "",
    micro_rotate_deg: float = 0.0,
    invis_text: str = "",
    invis_xy: tuple[int, int] = (0, 0),
    colorspace_roundtrip: bool = False,
    lens_k1: float = 0.0,
    lens_k2: float = 0.0,
    shake_freq: float = 0.0,
    shake_amp: float = 0.0,
    input_tag: str = "0:v",
    auto_hflip: bool = False,
    auto_noise_s: int = 0,
) -> str:
    """
    Строит видеоцепочку eq (+ unsharp + zoompan + trim + hue + fps по флагам).
    Вход: [input_tag], выход: [vbase]
    """
    import math as _math
    chain = f"[{input_tag}]"
    # Trim start + end (меняет GOP-структуру и хеш файла с обоих концов)
    if trim_frames > 0 or trim_end_frames > 0:
        if trim_end_frames > 0 and total_frames and total_frames > trim_frames + trim_end_frames + 1:
            end_f = total_frames - trim_end_frames
            chain += f"trim=start_frame={trim_frames}:end_frame={end_f},setpts=PTS-STARTPTS,"
        elif trim_frames > 0:
            chain += f"trim=start_frame={trim_frames},setpts=PTS-STARTPTS,"
    eq = f"eq=brightness={br:.4f}:contrast={con:.4f}:saturation={sat:.4f}"
    chain += eq
    if abs(hue_deg) > 0.01:
        chain += f",hue=h={hue_deg:.2f}"
    if colorbalance:
        chain += f",{colorbalance}"
    # Curves: случайный сдвиг RGB кривых (меняет цветовой отклик каждого канала)
    if curves:
        chain += f",{curves}"
    if unsharp:
        unsharp_amount = round(random.uniform(0.3, 0.7), 3)
        chain += f",unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount={unsharp_amount}"
    if zoom:
        z_lo, z_hi = _scaled_uniform_interval(1.02, 1.06, uniqual_k)
        z = random.uniform(max(1.005, z_lo), z_hi)
        chain += f",scale=iw*{z:.3f}:ih*{z:.3f},crop=iw/{z:.3f}:ih/{z:.3f}"
    if fps_out is not None:
        chain += f",fps=fps={fps_out:.5f}"
    if micro_dw != 0 or micro_dh != 0:
        chain += f",scale=iw+{int(micro_dw)}:ih+{int(micro_dh)},scale=iw-{int(micro_dw)}:ih-{int(micro_dh)}"
    # Micro-rotate: поворот 0.01–0.08° — меняет пиксельный хеш без заметного артефакта.
    if abs(micro_rotate_deg) > 0.005:
        rad = micro_rotate_deg * _math.pi / 180.0
        chain += f",rotate={rad:.6f}:ow=iw:oh=ih:fillcolor=black@0"
    # Invisible UUID watermark: текст с alpha≈0.008 — человек не видит, бинарный отпечаток уникален.
    if invis_text:
        x, y = invis_xy
        _font_arg = _invis_drawtext_font_arg()
        chain += f",drawtext=text='{invis_text}':x={x}:y={y}:fontsize=6:fontcolor=white@0.008:{_font_arg}"
    # Линзовая дисторсия (barrel/pincushion): k1=±0.008 → невидима, spatial hash уникален.
    if abs(lens_k1) > 1e-5 or abs(lens_k2) > 1e-5:
        chain += f",lenscorrection=k1={lens_k1:.5f}:k2={lens_k2:.5f}"
    # Синтетическое дрожание камеры: sin-поворот < 0.12° — меняет каждый кадр по-разному.
    if abs(shake_amp) > 1e-7 and shake_freq > 1e-4:
        chain += f",rotate={shake_amp:.6f}*sin(t*{shake_freq:.3f}):ow=iw:oh=ih:fillcolor=black@0"
    # yuv420p требует чётные ширина/высота (иначе падение кодека)
    chain += ",scale=trunc(iw/2)*2:trunc(ih/2)*2"
    # Автоматическое видео-зерно: меняет пиксельный отпечаток каждого кадра, не заметно глазу.
    if auto_noise_s > 0:
        chain += f",noise=alls={auto_noise_s}:allf=t+u"
    # Colorspace round-trip: yuv420p→yuv444p→yuv420p — тонкие хроминансные артефакты меняют хеш.
    if colorspace_roundtrip:
        chain += ",format=yuv444p"
    # Горизонтальный флип: меняет spatial hash Content ID — один из наиболее эффективных методов.
    if auto_hflip:
        chain += ",hflip"
    chain += ",format=yuv420p[vbase]"
    return chain


def _escape_ass_event_text(text: str) -> str:
    """Экранирование текста в поле Dialogue (.ass)."""
    s = _sanitize_overlay_text(text)
    return (
        s.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _is_regional_indicator_cp(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def _emoji_cp_start(cp: int) -> bool:
    if 0x1F300 <= cp <= 0x1FAFF:
        return True
    if 0x2600 <= cp <= 0x26FF:
        return True
    if 0x2700 <= cp <= 0x27BF:
        return True
    if 0x1F600 <= cp <= 0x1F64F:
        return True
    if 0x1F680 <= cp <= 0x1F6FF:
        return True
    misc = frozenset(
        {
            0x231A,
            0x231B,
            0x2328,
            0x23CF,
            0x23E9,
            0x23EA,
            0x23EB,
            0x23EC,
            0x23ED,
            0x23EE,
            0x23EF,
            0x23F0,
            0x23F1,
            0x23F2,
            0x23F3,
            0x23F8,
            0x23F9,
            0x23FA,
            0x24C2,
            0x25AA,
            0x25AB,
            0x25B6,
            0x25C0,
            0x25FB,
            0x25FC,
            0x25FD,
            0x25FE,
            0x2B05,
            0x2B06,
            0x2B07,
            0x2B1B,
            0x2B1C,
            0x2B50,
            0x2B55,
            0x3030,
            0x303D,
            0x3297,
            0x3299,
        }
    )
    return cp in misc


def _emoji_cluster_at(s: str, i: int) -> tuple[str, int] | None:
    """Один кластер эмодзи (флаги, ZWJ, тон кожи, VS16) или None."""
    n = len(s)
    if i >= n:
        return None
    c0 = ord(s[i])
    if _is_regional_indicator_cp(c0) and i + 1 < n and _is_regional_indicator_cp(ord(s[i + 1])):
        return s[i : i + 2], i + 2
    if not _emoji_cp_start(c0):
        return None
    j = i + 1
    while j < n:
        cj = ord(s[j])
        if cj in (0xFE0F, 0xFE0E):
            j += 1
            continue
        if cj == 0x200D:
            j += 1
            if j >= n:
                break
            c2 = ord(s[j])
            if _is_regional_indicator_cp(c2) and j + 1 < n and _is_regional_indicator_cp(ord(s[j + 1])):
                j += 2
                continue
            if _emoji_cp_start(c2) or (0x1F3FB <= c2 <= 0x1F3FF):
                j += 1
                continue
            break
        if 0x1F3FB <= cj <= 0x1F3FF:
            j += 1
            continue
        break
    return s[i:j], j


def _subtitle_emoji_font_name() -> str:
    raw = (os.environ.get("NEORENDER_SUBTITLE_EMOJI_FONT") or "").strip()
    if raw:
        return raw[:120]
    if platform.system() == "Windows":
        return "Segoe UI Emoji"
    return "Noto Color Emoji"


def _dir_has_font_files(d: Path) -> bool:
    ok = frozenset({".ttf", ".otf", ".ttc"})
    try:
        return any(p.is_file() and p.suffix.lower() in ok for p in d.iterdir())
    except OSError:
        return False


def _invis_drawtext_font_arg() -> str:
    """
    Возвращает аргумент шрифта для невидимого drawtext.
    Приоритет: fontfile= (прямой путь, без fontconfig) → font=Arial.
    fontconfig на Windows без конфига вызывает segfault FFmpeg.
    """
    bundled = Path(__file__).resolve().parent / "fonts"
    for name in ("Pretendard-Regular.otf", "Pretendard-Regular.ttf"):
        candidate = bundled / name
        if candidate.is_file():
            escaped = _escape_filter_path_for_windows(str(candidate))
            return f"fontfile='{escaped}'"
    env_dir = (os.environ.get("NEORENDER_FONTS_DIR") or "").strip()
    if env_dir:
        for name in ("Pretendard-Regular.otf", "Pretendard-Regular.ttf"):
            candidate = Path(env_dir) / name
            if candidate.is_file():
                escaped = _escape_filter_path_for_windows(str(candidate))
                return f"fontfile='{escaped}'"
    return "font=Arial"


def _optional_fonts_dir_for_subtitles() -> str | None:
    """Если есть TTF/OTF — передаётся в subtitles=…:fontsdir= (libass подхватит Pretendard и т.д.)."""
    env = (os.environ.get("NEORENDER_FONTS_DIR") or "").strip()
    if env:
        pe = Path(env)
        if pe.is_dir() and _dir_has_font_files(pe):
            return str(pe.resolve())
    bundled = Path(__file__).resolve().parent / "fonts"
    if bundled.is_dir() and _dir_has_font_files(bundled):
        return str(bundled.resolve())
    return None


def _ass_escape_plain_chunk(chunk: str) -> str:
    return (
        chunk.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _ass_text_with_emoji_font_overrides(raw_text: str, emoji_font: str) -> str:
    """
    Текст для Dialogue: обычные фрагменты — как раньше; эмодзи — {\\fn…\\bord0\\shad0}…{\\r},
    чтобы цветной глиф не наследовал жирную обводку стиля Default.
    """
    base = _sanitize_overlay_text(raw_text)
    if not base.strip():
        return ""
    ef = (emoji_font or "").strip().replace("\\", "").replace(",", "")[:120]
    if not ef:
        return _ass_escape_plain_chunk(base)

    out: list[str] = []
    i = 0
    n = len(base)
    while i < n:
        cl = _emoji_cluster_at(base, i)
        if cl:
            emo, j = cl
            esc_e = emo.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            out.append(rf"{{\fn{ef}\bord0\shad0}}{esc_e}{{\r}}")
            i = j
        else:
            j = i + 1
            while j < n and _emoji_cluster_at(base, j) is None:
                j += 1
            out.append(_ass_escape_plain_chunk(base[i:j]))
            i = j
    return "".join(out)


# Случайный выбор при subtitle_font пустой: упор на корейские и популярные в KR интерфейсах имена.
_ASS_FONT_POOL = [
    "Arial",
    "Malgun Gothic",
    "Segoe UI",
]


def _play_resolution_for_subtitles(template_key: str, src_w: int, src_h: int) -> tuple[int, int]:
    """
    PlayRes в [Script Info] должен совпадать с разрешением кадра после filter_complex.
    Иначе libass берёт устаревший дефолт (часто 384×288) и FontSize в ASS не соответствует пикселям на экране.
    """
    tmpl = _normalize_template(template_key)
    if tmpl in ("story", "reaction"):
        return (1080, 1920)
    w = max(2, int(src_w) // 2 * 2)
    h = max(2, int(src_h) // 2 * 2)
    if w < 2 or h < 2:
        return (1080, 1920)
    return (w, h)


def _cta_ass_file_body(
    text: str,
    template_key: str,
    subtitle_style: str,
    subtitle_font: str | None = None,
    subtitle_font_size: int | None = None,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> str:
    """
    Один субтитр на всё видео — libass рисует кириллицу надёжнее, чем drawtext+textfile.
    Шрифт выбирается случайно из пула если subtitle_font не задан.
    Эмодзи — отдельный шрифт (см. _ass_text_with_emoji_font_overrides).
    """
    # Уникализация текста: гомоглифы + ZWS (ASS рендерит идентично, бинарник уникален)
    spun = _homoglyph_spin(text)
    esc = _ass_text_with_emoji_font_overrides(spun, _subtitle_emoji_font_name())
    tmpl = _normalize_template(template_key)
    st = _normalize_subtitle_style(subtitle_style)
    readable = st == "readable"
    font_name = subtitle_font.strip() if subtitle_font and subtitle_font.strip() else random.choice(_ASS_FONT_POOL)
    font_name = font_name.replace(",", " ").strip()[:120]
    if tmpl == "news":
        align = 2
        base_margin_v = 56
        default_fs = 38 if readable else 34
        outline = 3.0 if readable else 2.0
        shadow = 1.2 if readable else 0.9
    else:
        align = 8
        base_margin_v = 18
        default_fs = 36 if readable else 32
        outline = 2.8 if readable else 1.6
        shadow = 1.0 if readable else 0.7
    # MarginV джиттер ±10 px — каждый ролик рисует субтитр на своей высоте
    margin_v = max(8, base_margin_v + random.randint(-10, 10))
    fs = int(subtitle_font_size) if subtitle_font_size and subtitle_font_size > 0 else default_fs
    # Случайный оттенок белого (визуально идентичны, ASS байты разные)
    _white_pool = ["&H00FFFFFF", "&H00FAFAFA", "&H00FFFEF0", "&H00F8F8F8", "&H00FFFDEE", "&H00F5F5F5"]
    subtitle_color = random.choice(_white_pool)
    prx = max(2, int(play_res_x))
    pry = max(2, int(play_res_y))
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {prx}\n"
        f"PlayResY: {pry}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{fs},{subtitle_color},&H000000FF,&H00000000,&H6E000000,0,0,0,0,"
        f"100,100,0,0,1,{outline:.1f},{shadow:.1f},{align},16,16,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,99:00:00.00,Default,,0,0,0,,"
        f"{esc}\n"
    )


def _cta_subtitles_filter_chain(
    input_label: str, output_label: str, ass_path_abs: str
) -> str:
    """Вшить готовый .ass через subtitles= (нужен libass в сборке FFmpeg)."""
    if not (ass_path_abs or "").strip():
        return f"{input_label}copy{output_label}"
    esc = _escape_subtitles_path(ass_path_abs)
    fd_part = ""
    fd = _optional_fonts_dir_for_subtitles()
    if fd:
        # Значение fontsdir в кавычках: иначе «C:/…» на Windows режется по ':' (разделитель опций фильтра).
        fd_part = f":fontsdir='{_escape_subtitles_path(fd)}'"
    return f"{input_label}subtitles='{esc}'{fd_part}{output_label}"


def build_filter_complex(
    preset_key: str,
    template_key: str,
    with_audio: bool,
    subtitle_textfile_fwd: str = "",
    srt_path: str = "",
    overlay_mode: str = "on_top",
    overlay_position: str = "center",
    subtitle_style: str = "default",
    subtitle_font: str | None = None,
    subtitle_font_size: int | None = None,
    overlay_blend_mode: str = "normal",
    overlay_opacity: float = 1.0,
    effects: dict[str, bool] | None = None,
    effect_levels: dict[str, str] | None = None,
    uniqualize_intensity: str = "med",
    duration_sec: float | None = None,
    source_fps: float | None = None,
    total_frames: int | None = None,
    micro_dw: int = 0,
    micro_dh: int = 0,
    ass_path: str = "",
) -> tuple[str, str]:
    """
    Сборка filter_complex. Возвращает (строка фильтра, метка видеовыхода для -map).

    subtitle_textfile_fwd — абсолютный путь к временному .ass с одним CTA (слэши /).
    srt_path — опционально сжечь таймкодные субтитры поверх [vout] (нужен libass в FFmpeg).
    ass_path — путь к .ass от subtitle_generator (приоритет над srt_path; использует фильтр ass=).
    overlay_mode — on_top или under_video (подложка на весь кадр).
    overlay_position — для режима «обычное» наложение и on_top.
    overlay_blend_mode / overlay_opacity — смешивание полного кадра (см. get_overlay_blend_modes).
    subtitle_style — default / readable для ASS-CTA и force_style у SRT.
    subtitle_font / subtitle_font_size — опционально для SRT force_style (имя как в системе FFmpeg).
    uniqualize_intensity — low / med / high: насколько широк случайный разброс поверх пресета.
    micro_dw / micro_dh — микросдвиг scale «туда-обратно» для бинарного отпечатка.
    """
    p = RENDER_PRESETS[_normalize_preset(preset_key)]
    tmpl = _normalize_template(template_key)
    om = _normalize_overlay_mode(overlay_mode)
    op = _normalize_overlay_position(overlay_position)
    sst = _normalize_subtitle_style(subtitle_style)
    obl = _normalize_overlay_blend(overlay_blend_mode)
    opa = max(0.0, min(1.0, float(overlay_opacity)))
    uid = random.randint(10000, 99999)
    uq_k = _uniqualize_interval_k(uniqualize_intensity)

    sat = random.uniform(*_scaled_uniform_interval(p["saturation"][0], p["saturation"][1], uq_k))
    con = random.uniform(*_scaled_uniform_interval(p["contrast"][0], p["contrast"][1], uq_k))
    br = random.uniform(*_scaled_uniform_interval(p["brightness"][0], p["brightness"][1], uq_k))

    # Hue-вращение: small random shift меняет хеш без видимых артефактов.
    hue_range = {"low": 1.5, "med": 3.0, "high": 5.5}.get(
        _normalize_uniqualize_intensity(uniqualize_intensity), 3.0
    )
    hue_deg = random.uniform(-hue_range, hue_range)

    # Цветовая температура: тёплый или холодный тон (меняет RGB-баланс).
    cb_strength = {"low": 0.01, "med": 0.025, "high": 0.045}.get(
        _normalize_uniqualize_intensity(uniqualize_intensity), 0.025
    )
    cb_r = round(random.uniform(-cb_strength, cb_strength), 4)
    cb_g = round(random.uniform(-cb_strength * 0.4, cb_strength * 0.4), 4)
    cb_b = round(-cb_r * 0.7 + random.uniform(-cb_strength * 0.2, cb_strength * 0.2), 4)
    colorbalance_filter = f"colorbalance=rs={cb_r}:gs={cb_g}:bs={cb_b}"

    # Curves: случайный сдвиг точки в середине кривой каждого канала (незаметно визуально).
    curves_strength = {"low": 0.010, "med": 0.018, "high": 0.028}.get(
        _normalize_uniqualize_intensity(uniqualize_intensity), 0.018
    )
    c_r = round(0.5 + random.uniform(-curves_strength, curves_strength), 4)
    c_g = round(0.5 + random.uniform(-curves_strength, curves_strength), 4)
    c_b = round(0.5 + random.uniform(-curves_strength, curves_strength), 4)
    curves_filter = (
        f"curves=r='0/0 0.5/{c_r} 1/1':g='0/0 0.5/{c_g} 1/1':b='0/0 0.5/{c_b} 1/1'"
    )

    # Micro-rotate: 60% вероятность лёгкого поворота 0.015–0.08°.
    micro_rotate_deg = 0.0
    if random.random() < 0.60:
        micro_rotate_deg = round(
            random.uniform(0.015, 0.08) * random.choice([-1, 1]), 4
        )

    # Invisible UUID watermark (40% вероятность): бинарный отпечаток без видимого эффекта.
    import uuid as _uuid
    invis_text = ""
    invis_xy: tuple[int, int] = (0, 0)
    if random.random() < 0.40:
        invis_text = _uuid.uuid4().hex[:12]
        invis_xy = (random.randint(2, 28), random.randint(2, 28))

    # Colorspace round-trip: 50% шанс — тонкие хроминансные артефакты меняют хеш.
    colorspace_roundtrip = random.random() < 0.50

    # Линзовая дисторсия — 65% шанс; сила зависит от пресета.
    _lens_strength = {"standard": 0.004, "soft": 0.003, "deep": 0.008, "ultra": 0.012}.get(
        _normalize_preset(preset_key), 0.008
    )
    lens_k1 = lens_k2 = 0.0
    if random.random() < 0.65:
        lens_k1 = round(random.uniform(-_lens_strength, _lens_strength), 5)
        lens_k2 = round(random.uniform(-_lens_strength * 0.3, _lens_strength * 0.3), 5)

    # Синтетическое дрожание камеры — 45% шанс.
    shake_freq = shake_amp = 0.0
    if random.random() < 0.45:
        shake_freq = round(random.uniform(1.4, 3.8), 3)
        shake_amp  = round(random.uniform(0.0007, 0.0022), 6)

    # ── Авто-hflip: меняет spatial hash Content ID без артефактов ───────────────
    # standard/soft: 25-30% — горизонтальный флип один из самых эффективных методов против Content ID;
    # ранее был 0% для этих пресетов, что делало их уязвимыми даже при цветовых правках.
    _hflip_prob = {"standard": 0.25, "soft": 0.30, "deep": 0.40, "ultra": 0.55}.get(
        _normalize_preset(preset_key), 0.0
    )
    auto_hflip = random.random() < _hflip_prob

    # ── Segment reverse: инвертируем первые 2–4 сек (ломает temporal sliding window) ──
    # Content ID матчит по 10-секундным окнам; реверс первого сегмента смещает все окна.
    # ultra: 60% — максимальная защита временного отпечатка.
    _seg_rev_prob = {"deep": 0.30, "ultra": 0.60}.get(_normalize_preset(preset_key), 0.0)
    _do_seg_reverse = (
        random.random() < _seg_rev_prob
        and bool(duration_sec)
        and float(duration_sec or 0) > 6.0
    )
    v_in_tag = "0:v"
    a_in_tag = "0:a"
    _pre_chains: list[str] = []
    if _do_seg_reverse:
        _rev_sec = round(random.uniform(2.0, min(4.0, float(duration_sec) * 0.15)), 2)  # type: ignore[arg-type]
        _pre_chains.append(
            f"[0:v]split=2[_vra][_vrb];"
            f"[_vra]trim=start=0:end={_rev_sec:.2f},setpts=PTS-STARTPTS,reverse[_vrrev];"
            f"[_vrb]trim=start={_rev_sec:.2f},setpts=PTS-STARTPTS[_vrrest];"
            f"[_vrrev][_vrrest]concat=n=2:v=1:a=0[v_preproc]"
        )
        v_in_tag = "v_preproc"
        if with_audio:
            _pre_chains.append(
                f"[0:a]asplit=2[_ara][_arb];"
                f"[_ara]atrim=start=0:end={_rev_sec:.2f},asetpts=PTS-STARTPTS,areverse[_arrev];"
                f"[_arb]atrim=start={_rev_sec:.2f},asetpts=PTS-STARTPTS[_arrest];"
                f"[_arrev][_arrest]concat=n=2:v=0:a=1[a_preproc]"
            )
            a_in_tag = "a_preproc"

    # Random trim: обрезаем 0–3 кадра с начала и 0–2 с конца (меняет GOP и хеш).
    trim_frames_range = {"low": 1, "med": 2, "high": 3}.get(
        _normalize_uniqualize_intensity(uniqualize_intensity), 2
    )
    trim_frames = random.randint(0, trim_frames_range)
    trim_end_frames = random.randint(0, max(0, trim_frames_range - 1))

    # FPS джиттер: вокруг реального FPS исходника (или 30 если не определён).
    base_fps = float(source_fps) if (source_fps and 10.0 <= source_fps <= 120.0) else 30.0
    fps_jitter = {"low": 0.01, "med": 0.03, "high": 0.06}.get(
        _normalize_uniqualize_intensity(uniqualize_intensity), 0.03
    )
    fps_out = round(base_fps + random.uniform(-fps_jitter, fps_jitter), 5)

    # Fade in/out: длительность в секундах.
    fade_dur = {"low": 0.15, "med": 0.25, "high": 0.4}.get(
        _normalize_uniqualize_intensity(uniqualize_intensity), 0.25
    )
    # Время начала fade out: реальная длительность минус fade, иначе пропускаем fade out.
    dur = float(duration_sec) if (duration_sec and duration_sec > 0) else None
    fade_out_st = max(0.0, dur - fade_dur) if dur else None

    tf = (subtitle_textfile_fwd or "").strip()
    has_sub = bool(tf)

    def ov(base: str, out: str) -> str:
        return _overlay_media_chain(base, out, om, op, uid, obl, opa)

    def _add_fade(in_tag: str, out_tag: str) -> str:
        """Fade in всегда; fade out только если знаем длительность."""
        s = f"[{in_tag}]fade=t=in:st=0:d={fade_dur:.3f}"
        if fade_out_st is not None:
            s += f",fade=t=out:st={fade_out_st:.3f}:d={fade_dur:.3f}"
        s += f"[{out_tag}]"
        return s

    chains: list[str] = []
    eff = effects or {}
    e_levels_raw = effect_levels or {}
    speed_mul = 1.0

    # ── Авто видео-зерно: тонкий шум на кадрах меняет пиксельный hash без видимых артефактов ──
    # Активируется только если noise-эффект не включён явно (избегаем двойного шума).
    # deep: 50%, ultra: 65% — достаточно для смены pHash-отпечатка.
    _auto_noise_prob = {"standard": 0.0, "soft": 0.20, "deep": 0.50, "ultra": 0.65}.get(
        preset_key, 0.0
    )
    auto_noise_s = 0
    if not eff.get("noise") and random.random() < _auto_noise_prob:
        _noise_max = {"soft": 3, "deep": 4, "ultra": 6}.get(preset_key, 4)
        auto_noise_s = random.randint(2, _noise_max)

    def _lvl(key: str) -> str:
        raw = str(e_levels_raw.get(key, "med")).strip().lower()
        return raw if raw in {"low", "med", "high"} else "med"

    def _apply_effects(in_tag: str) -> str:
        nonlocal speed_mul
        if not any(bool(v) for v in eff.values()):
            return in_tag
        vfilters: list[str] = []
        if eff.get("mirror"):
            vfilters.append("hflip")
        if eff.get("noise"):
            na = int(min(20, max(5, round(10 * uq_k))))
            vfilters.append(f"noise=alls={na}:allf=t+u")
        if eff.get("gamma_jitter"):
            lvl = _lvl("gamma_jitter")
            if lvl == "low":
                lo, hi = 0.98, 1.02
            elif lvl == "high":
                lo, hi = 0.93, 1.07
            else:
                lo, hi = 0.96, 1.04
            gm_lo, gm_hi = _scaled_uniform_interval(lo, hi, uq_k)
            gm = random.uniform(gm_lo, gm_hi)
            vfilters.append(f"eq=gamma={gm:.4f}")
        if eff.get("crop_reframe"):
            lvl = _lvl("crop_reframe")
            if lvl == "low":
                lo, hi = 1.005, 1.015
            elif lvl == "high":
                lo, hi = 1.04, 1.08
            else:
                lo, hi = 1.015, 1.035
            z_lo, z_hi = _scaled_uniform_interval(lo, hi, uq_k)
            z = random.uniform(z_lo, z_hi)
            # Микрокроп + обратный масштаб до исходного кадра.
            vfilters.append(f"scale=iw*{z:.4f}:ih*{z:.4f},crop=iw/{z:.4f}:ih/{z:.4f}")
        if eff.get("speed"):
            _s_lvl = _lvl("speed")
            if _s_lvl == "low":
                _s_lo_base, _s_hi_base = 0.98, 1.02
            elif _s_lvl == "high":
                _s_lo_base, _s_hi_base = 0.93, 1.07
            else:
                _s_lo_base, _s_hi_base = 0.96, 1.04
            s_lo, s_hi = _scaled_uniform_interval(_s_lo_base, _s_hi_base, uq_k)
            speed_mul = random.uniform(max(0.88, s_lo), min(1.12, s_hi))
            vfilters.append(f"setpts=PTS/{speed_mul:.4f}")
        if not vfilters:
            return in_tag
        out_tag = f"vfx{uid}"
        chains.append(f"[{in_tag}]{','.join(vfilters)}[{out_tag}]")
        return out_tag

    eq_kwargs = dict(
        uniqual_k=uq_k,
        trim_frames=trim_frames,
        trim_end_frames=trim_end_frames,
        total_frames=total_frames,
        hue_deg=hue_deg,
        fps_out=fps_out,
        colorbalance=colorbalance_filter,
        micro_dw=micro_dw,
        micro_dh=micro_dh,
        curves=curves_filter,
        micro_rotate_deg=micro_rotate_deg,
        invis_text=invis_text,
        invis_xy=invis_xy,
        colorspace_roundtrip=colorspace_roundtrip,
        lens_k1=lens_k1,
        lens_k2=lens_k2,
        shake_freq=shake_freq,
        shake_amp=shake_amp,
        input_tag=v_in_tag,
        auto_hflip=auto_hflip,
        auto_noise_s=auto_noise_s,
    )

    chains.extend(_pre_chains)

    if tmpl == "default":
        chains.append(_eq_chain(sat, con, br, p["unsharp"], p["zoom"], **eq_kwargs))
        base_tag = _apply_effects("vbase")
        if has_sub:
            # Сначала PNG, потом текст — иначе непрозрачный/крупный оверлей перекрывает CTA.
            pre = f"vpre{uid}"
            chains.append(ov(base_tag, pre))
            chains.append(_cta_subtitles_filter_chain(f"[{pre}]", "[vout_nf]", tf))
        else:
            chains.append(ov(base_tag, "vout_nf"))
        chains.append(_add_fade("vout_nf", "vout"))

    elif tmpl == "reaction":
        chains.append(_eq_chain(sat, con, br, p["unsharp"], p["zoom"], **eq_kwargs))
        base_tag = _apply_effects("vbase")
        # Нижняя половина: зеркало + дополнительный случайный crop для разнообразия.
        rx = round(random.uniform(0.0, 0.04), 3)
        ry = round(random.uniform(0.0, 0.03), 3)
        crop_bot = f"crop=iw*(1-{rx:.3f}):ih*(1-{ry:.3f}):iw*{rx/2:.3f}:ih*{ry/2:.3f}," if (rx + ry) > 0.005 else ""
        chains.append(
            f"[{base_tag}]split=2[vtop][vbot_raw];"
            "[vtop]scale=1080:960:force_original_aspect_ratio=decrease,"
            "pad=1080:960:(ow-iw)/2:(oh-ih)/2:black[top];"
            f"[vbot_raw]{crop_bot}scale=1080:960:force_original_aspect_ratio=decrease,"
            "pad=1080:960:(ow-iw)/2:(oh-ih)/2:black,hflip[bot];"
            "[top][bot]vstack=inputs=2[stacked]"
        )
        chains.append(ov("stacked", "vout_pre"))
        if has_sub:
            chains.append(_cta_subtitles_filter_chain("[vout_pre]", "[vout_nf]", tf))
        else:
            chains.append("[vout_pre]copy[vout_nf]")
        chains.append(_add_fade("vout_nf", "vout"))

    elif tmpl == "news":
        chains.append(_eq_chain(sat, con, br, p["unsharp"], p["zoom"], **eq_kwargs))
        base_tag = _apply_effects("vbase")
        # drawbox: случайная высота полосы (72–92 px) и непрозрачность (0.50–0.70).
        # Полоса рисуется всегда — и с субтитром, и без (CTA накладывается поверх полосы).
        box_h = random.randint(72, 92)
        box_op = round(random.uniform(0.50, 0.70), 2)
        boxed = f"vboxed{uid}"
        chains.append(
            f"[{base_tag}]drawbox=y=ih-{box_h}:color=black@{box_op}:"
            f"width=iw:height={box_h}:t=fill[{boxed}]"
        )
        if has_sub:
            pre = f"vpre{uid}"
            chains.append(ov(boxed, pre))
            chains.append(_cta_subtitles_filter_chain(f"[{pre}]", "[vout_nf]", tf))
        else:
            chains.append(ov(boxed, "vout_nf"))
        chains.append(_add_fade("vout_nf", "vout"))

    elif tmpl == "story":
        import math as _math_story
        trim_part = f"trim=start_frame={trim_frames},setpts=PTS-STARTPTS," if trim_frames > 0 else ""
        hue_part = f",hue=h={hue_deg:.2f}" if abs(hue_deg) > 0.01 else ""
        cb_part = f",{colorbalance_filter}"
        curves_part = f",{curves_filter}"
        micro_story = ""
        if micro_dw != 0 or micro_dh != 0:
            micro_story = (
                f",scale=iw+{int(micro_dw)}:ih+{int(micro_dh)},"
                f"scale=iw-{int(micro_dw)}:ih-{int(micro_dh)}"
            )
        rotate_part = ""
        if abs(micro_rotate_deg) > 0.005:
            rad = micro_rotate_deg * _math_story.pi / 180.0
            rotate_part = f",rotate={rad:.6f}:ow=iw:oh=ih:fillcolor=black@0"
        invis_part = ""
        if invis_text:
            ix, iy = invis_xy
            _font_arg = _invis_drawtext_font_arg()
            invis_part = f",drawtext=text='{invis_text}':x={ix}:y={iy}:fontsize=6:fontcolor=white@0.008:{_font_arg}"
        lens_part = ""
        if abs(lens_k1) > 1e-5 or abs(lens_k2) > 1e-5:
            lens_part = f",lenscorrection=k1={lens_k1:.5f}:k2={lens_k2:.5f}"
        shake_part = ""
        if abs(shake_amp) > 1e-7 and shake_freq > 1e-4:
            shake_part = f",rotate={shake_amp:.6f}*sin(t*{shake_freq:.3f}):ow=iw:oh=ih:fillcolor=black@0"
        cs_part = ",format=yuv444p" if colorspace_roundtrip else ""
        # Автошум и авто-hflip — применяются в инлайн-цепочке так же, как в _eq_chain.
        noise_part_story = f",noise=alls={auto_noise_s}:allf=t+u" if auto_noise_s > 0 else ""
        hflip_part_story = ",hflip" if auto_hflip else ""
        chains.append(
            f"[{v_in_tag}]{trim_part}crop=min(iw\\,ih*9/16):ih:(iw-min(iw\\,ih*9/16))/2:0,"
            f"scale=1080:1920,eq=brightness={br:.4f}:"
            f"contrast={con:.4f}:saturation={sat:.4f}{hue_part}{cb_part}{curves_part},"
            f"fps=fps={fps_out:.5f}{micro_story}{rotate_part}{invis_part}"
            f"{lens_part}{shake_part},"
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2{noise_part_story}{cs_part}{hflip_part_story},"
            f"format=yuv420p[vbase]"
        )
        base_tag = _apply_effects("vbase")
        if has_sub:
            pre = f"vpre{uid}"
            chains.append(ov(base_tag, pre))
            chains.append(_cta_subtitles_filter_chain(f"[{pre}]", "[vout_nf]", tf))
        else:
            chains.append(ov(base_tag, "vout_nf"))
        chains.append(_add_fade("vout_nf", "vout"))

    elif tmpl == "ugc":
        chains.append(_eq_chain(sat, con, br, False, False, **eq_kwargs))
        base_tag = _apply_effects("vbase")
        # Виньетка: случайный угол PI/5..PI/9, смещённый центр.
        vig_denom = round(random.uniform(5.0, 9.0), 2)
        vig_cx = round(random.uniform(0.44, 0.56), 3)
        vig_cy = round(random.uniform(0.44, 0.56), 3)
        chains.append(
            f"[{base_tag}]vignette=angle=PI/{vig_denom:.2f}:"
            f"x0=w*{vig_cx:.3f}:y0=h*{vig_cy:.3f}[vvig]"
        )
        chains.append(ov("vvig", "vout_pre"))
        if has_sub:
            chains.append(_cta_subtitles_filter_chain("[vout_pre]", "[vout_nf]", tf))
        else:
            chains.append("[vout_pre]copy[vout_nf]")
        chains.append(_add_fade("vout_nf", "vout"))

    else:
        chains.append(_eq_chain(sat, con, br, False, False, **eq_kwargs))
        base_tag = _apply_effects("vbase")
        chains.append(ov(base_tag, "vout_nf"))
        chains.append(_add_fade("vout_nf", "vout"))

    if with_audio:
        a_lo, a_hi = _scaled_uniform_interval(p["atempo"][0], p["atempo"][1], uq_k)
        atempo = random.uniform(max(0.88, a_lo), min(1.12, a_hi))
        if eff.get("speed"):
            # Лёгкий speed-up/slow-down в паре с video setpts.
            atempo = max(0.5, min(2.0, atempo * speed_mul))

        # Pitch shift (расширенный диапазон) — Chromaprint устойчив до ~±3–4%.
        _pr = _PITCH_RANGE.get(_normalize_preset(preset_key), (0.974, 1.026))
        pi_lo, pi_hi = _scaled_uniform_interval(_pr[0], _pr[1], uq_k)
        pitch = random.uniform(max(0.94, pi_lo), min(1.06, pi_hi))
        base_sr = 48000
        new_sr = int(base_sr * pitch)

        # Нужен ли промежуточный тег (если добавляем noise через amix)?
        _noise_prob = {"low": 0.45, "med": 0.80, "high": 0.95}.get(
            _normalize_uniqualize_intensity(uniqualize_intensity), 0.80
        )
        _add_noise = random.random() < _noise_prob
        _apre_tag = f"apre{uid}" if _add_noise else "aout"

        a_chain = f"[{a_in_tag}]atempo={atempo:.4f},asetrate={new_sr},aresample={base_sr}"

        if eff.get("audio_tone"):
            # Лёгкий тональный профиль без агрессивных артефактов.
            lvl = _lvl("audio_tone")
            if lvl == "low":
                a_chain += ",highpass=f=60,lowpass=f=14000,acompressor=threshold=-22dB:ratio=1.6:attack=24:release=140:makeup=0.7"
            elif lvl == "high":
                a_chain += ",highpass=f=100,lowpass=f=10000,acompressor=threshold=-16dB:ratio=2.5:attack=16:release=100:makeup=1.2"
            else:
                a_chain += ",highpass=f=80,lowpass=f=12000,acompressor=threshold=-18dB:ratio=2:attack=20:release=120:makeup=1"
        else:
            # Авто baseline EQ для deep/ultra: мягкий срез сабсоников и ультравысоких частот.
            # Использует f=40/17000 — не конфликтует с audio_tone (f=60/80/100/10000/12000/14000).
            # Меняет спектральный отпечаток аудио без слышимых артефактов.
            _auto_aeq_prob = {"deep": 0.55, "ultra": 0.70}.get(preset_key, 0.0)
            if random.random() < _auto_aeq_prob:
                a_chain += ",highpass=f=40,lowpass=f=17000"

        # Тихое эхо 28–60 мс (40% шанс) — смазывает Chromaprint-окна без слышимого артефакта.
        if random.random() < 0.40:
            _echo_d = random.randint(28, 60)
            _echo_dec = round(random.uniform(0.06, 0.13), 3)
            a_chain += f",aecho=in_gain=0.95:out_gain=1.0:delays={_echo_d}:decays={_echo_dec}"

        # Случайный сдвиг громкости ±1.5 dB (меняет амплитудный профиль дорожки).
        _vol_db = round(random.uniform(-1.5, 1.5), 2)
        a_chain += f",volume={_vol_db}dB"

        # Инверсия стерео-каналов L↔R (40% шанс для deep/ultra — меняет fingerprint).
        # aformat=stereo перед channelmap: гарантирует 2 канала на входе (mono → duplex), иначе FFmpeg
        # падает с «input channel FR not available from input layout mono».
        if _normalize_preset(preset_key) in ("deep", "ultra") and random.random() < 0.40:
            a_chain += ",aformat=channel_layouts=stereo,channelmap=map=FR|FL:channel_layout=stereo"

        # Аудио fade in/out синхронно с видео.
        a_chain += f",afade=t=in:st=0:d={fade_dur:.3f}"
        if fade_out_st is not None:
            a_chain += f",afade=t=out:st={fade_out_st:.3f}:d={fade_dur:.3f}"

        a_chain += f"[{_apre_tag}]"
        chains.append(a_chain)

        if _add_noise:
            # Субпороговый шум (~–52 dBFS) через anoisesrc+amix — полностью ломает Chromaprint/ACR.
            _noise_amp = round(10 ** (random.uniform(-58, -46) / 20.0), 7)
            _ns_tag = f"ns{uid}"
            chains.append(f"anoisesrc=r={base_sr}:amplitude={_noise_amp}:duration=9999[{_ns_tag}]")
            chains.append(
                f"[{_apre_tag}][{_ns_tag}]amix=inputs=2:duration=first:normalize=0[aout]"
            )

    fc = ";".join(chains)
    vmap = "[vout]"

    # ── Тайм-кодные субтитры: ASS имеет приоритет над SRT ────────────────────
    # ASS от subtitle_generator — полная стилизация (шрифт Gmarket, fade, позиция).
    # SRT — запасной вариант с force_style через libass.
    ap = (ass_path or "").strip()
    sp = (srt_path or "").strip()
    if ap and Path(ap).is_file():
        esc = _escape_subtitles_path(str(Path(ap).resolve()))
        fd_ex = ""
        fd = _optional_fonts_dir_for_subtitles()
        if fd:
            fd_ex = f":fontsdir='{_escape_subtitles_path(fd)}'"
        fc += f";[vout]ass='{esc}'{fd_ex}[vfinal]"
        vmap = "[vfinal]"
    elif sp and Path(sp).is_file():
        esc = _escape_subtitles_path(str(Path(sp).resolve()))
        fs = _srt_force_style_escaped(sst, subtitle_font, subtitle_font_size)
        fd_ex = ""
        fd = _optional_fonts_dir_for_subtitles()
        if fd:
            fd_ex = f":fontsdir='{_escape_subtitles_path(fd)}'"
        fc += f";[vout]subtitles='{esc}':charenc=UTF-8{fd_ex}:force_style='{fs}'[vfinal]"
        vmap = "[vfinal]"
    return fc, vmap


# ─── Публичный API ────────────────────────────────────────────────────────────

async def render_unique_video(
    input_video: str | Path,
    overlay_media: str | Path,
    output_path: str | Path,
    *,
    preset: str = "deep",
    template: str = "default",
    subtitle: str = "",
    srt_path: str | None = None,
    ass_path: str | None = None,
    dub_audio_path: str | None = None,
    overlay_mode: str = "on_top",
    overlay_position: str = "center",
    overlay_blend_mode: str = "normal",
    overlay_opacity: float = 1.0,
    subtitle_style: str = "default",
    subtitle_font: str | None = None,
    subtitle_font_size: int | None = None,
    effects: dict[str, bool] | None = None,
    effect_levels: dict[str, str] | None = None,
    geo_enabled: bool = True,
    geo_profile: str | None = None,
    geo_jitter: float = 0.05,
    device_model: str | None = None,
    uniqualize_intensity: str = "med",
    progress_callback: Callable[..., Awaitable[None]] | None = None,
    dry_run: bool = False,
    cancel_event: asyncio.Event | None = None,
    auto_trim_lead_tail: bool = True,
    perceptual_hash_check: bool = True,
    preview_duration_sec: float | None = None,
) -> dict[str, Any]:
    """
    Рендер уникальной версии ролика.

    Параметры
    ----------
    overlay_media : PNG/JPEG/WebP или видео (MP4/MOV/…) — второй вход FFmpeg.
    overlay_blend_mode / overlay_opacity : см. luxury_engine.get_overlay_blend_modes()
    progress_callback : async (percent, label) — опционально, прогресс кодирования 0–100.
    dry_run : только собрать argv FFmpeg (nvenc + x264), без запуска — для отладки и тестов.
    cancel_event : при set() — прервать ffprobe/сборку/FFmpeg (отмена задачи из UI).
    auto_trim_lead_tail : blackdetect + silencedetect, обрезка начала/конца через -ss/-t у основного входа.
    perceptual_hash_check : после рендера — pHash кадров vs оригинал, perceptual_diff_pct и предупреждение если <20%.
    """
    cleanup_txt: list[Path] = []
    try:
        inp  = Path(input_video)
        ov   = Path(overlay_media)
        outp = Path(output_path)

        if not inp.is_file():
            return _error("Исходное видео не найдено.")
        if not ov.is_file():
            return _error("Файл слоя (картинка или видео) не найден.")
        if not _is_supported_overlay_media(ov):
            exts = ", ".join(sorted(_SUPPORTED_OVERLAY_MEDIA))
            return _error(f"Неподдерживаемый формат слоя. Разрешено: {exts}.")
        try:
            if inp.resolve() == outp.resolve():
                return _error("Путь выходного файла совпадает с исходным видео.")
            if ov.resolve() == outp.resolve():
                return _error("Путь выходного файла совпадает с файлом слоя.")
        except OSError:
            pass
        if ov.stat().st_size < 16:
            return _error(
                f"Файл слоя повреждён или пуст ({ov.stat().st_size} байт). "
                "Загрузите корректный PNG/JPG/WebP или видео."
            )
        # Проверяем что FFmpeg реально может декодировать оверлей (ловит битые файлы вроде Invalid PNG).
        # Пропускаем для dry_run — там FFmpeg не вызывается, размеры не нужны.
        if not dry_run:
            ov_dims = await _ff.probe_video_dimensions(ov)
            if ov_dims is None:
                return _error(
                    "Файл слоя повреждён: FFmpeg не может его прочитать. "
                    "Загрузите заново корректный PNG/JPG/WebP или видео."
                )

        outp.parent.mkdir(parents=True, exist_ok=True)

        if _cancelled(cancel_event):
            return _error(_CANCEL_MSG)

        # До ffprobe UI иначе показывал «4% / подготовка» без encoding.active — выглядело как зависание.
        if progress_callback:
            try:
                await progress_callback(2.0, "Анализ видео (ffprobe)…")
            except Exception:
                pass

        duration_sec = await _ff.probe_video_duration_seconds(inp)
        source_fps = await _ff.probe_video_fps(inp)
        src_codec = await _ff.probe_video_codec(inp)

        if _cancelled(cancel_event):
            return _error(_CANCEL_MSG)

        preset_key   = _normalize_preset(preset)
        template_key = _normalize_template(template)
        p = RENDER_PRESETS[preset_key]

        vid_dims = await _ff.probe_video_dimensions(inp)
        src_w, src_h = (vid_dims[0], vid_dims[1]) if vid_dims else (1080, 1920)
        play_rx, play_ry = _play_resolution_for_subtitles(template_key, src_w, src_h)

        with_audio = await _ff.probe_has_audio_stream(inp)

        trim_start_sec = 0.0
        trim_tail_sec = 0.0
        effective_duration_sec = duration_sec
        if auto_trim_lead_tail and duration_sec and duration_sec > 0.4:
            if progress_callback:
                try:
                    await progress_callback(3.5, "Поиск чёрных кадров и тишины…")
                except Exception:
                    pass
            trim_start_sec, trim_tail_sec = await _ff.probe_lead_tail_black_silence(
                inp,
                duration_sec=duration_sec,
                with_audio=with_audio,
            )
            eff = duration_sec - trim_start_sec - trim_tail_sec
            if eff >= 0.12:
                effective_duration_sec = eff
            else:
                trim_start_sec, trim_tail_sec = 0.0, 0.0
                effective_duration_sec = duration_sec

        # Примерное число кадров (после обрезки входа — важно для trim=end_frame=).
        total_frames: int | None = None
        if effective_duration_sec and source_fps:
            total_frames = max(1, int(effective_duration_sec * source_fps))

        main_input_ss: float | None = trim_start_sec if trim_start_sec > 1e-4 else None
        main_input_t: float | None = None
        if (
            effective_duration_sec
            and (trim_start_sec > 1e-4 or trim_tail_sec > 1e-4)
            and float(effective_duration_sec) > 0.05
        ):
            main_input_t = float(effective_duration_sec)
        # Preview: ограничить длительность входа (preview_duration_sec имеет приоритет над trim).
        if preview_duration_sec is not None and preview_duration_sec > 0:
            main_input_t = float(preview_duration_sec)

        micro_dw, micro_dh = _pick_micro_resize_pixels()

        if _cancelled(cancel_event):
            return _error(_CANCEL_MSG)

        if progress_callback:
            try:
                await progress_callback(5.0, "Сборка фильтров и метаданные…")
            except Exception:
                pass

        textfile_fwd = ""
        clean_sub = _sanitize_overlay_text(subtitle)
        if clean_sub:
            ass_p = outp.parent / f"_neo_cta_{random.randint(100000, 999999)}.ass"
            ass_p.write_text(
                _cta_ass_file_body(
                    clean_sub,
                    template_key,
                    subtitle_style,
                    subtitle_font,
                    subtitle_font_size,
                    play_res_x=play_rx,
                    play_res_y=play_ry,
                ),
                encoding="utf-8-sig",
            )
            cleanup_txt.append(ass_p)
            textfile_fwd = str(ass_p.resolve()).replace("\\", "/")

        srt_use = (srt_path or "").strip()
        if srt_use and not Path(srt_use).is_file():
            return _error("Файл SRT не найден.")

        ass_use = (ass_path or "").strip()
        if ass_use and not Path(ass_use).is_file():
            logger.warning("render_unique_video: ASS файл не найден (%s), используем SRT как запасной.", ass_use)
            ass_use = ""

        dub_audio_use = (dub_audio_path or "").strip()
        if dub_audio_use and not Path(dub_audio_use).is_file():
            logger.warning("render_unique_video: dub_audio_path не найден (%s), аудио оригинала сохраняется.", dub_audio_use)
            dub_audio_use = ""

        fc, vmap = build_filter_complex(
            preset_key,
            template_key,
            with_audio,
            textfile_fwd,
            srt_use,
            overlay_mode=overlay_mode,
            overlay_position=overlay_position,
            subtitle_style=subtitle_style,
            subtitle_font=subtitle_font,
            subtitle_font_size=subtitle_font_size,
            overlay_blend_mode=overlay_blend_mode,
            overlay_opacity=overlay_opacity,
            effects=effects,
            effect_levels=effect_levels,
            uniqualize_intensity=uniqualize_intensity,
            duration_sec=effective_duration_sec,
            source_fps=source_fps,
            total_frames=total_frames,
            micro_dw=micro_dw,
            micro_dh=micro_dh,
            ass_path=ass_use,
        )

        if not (fc or "").strip():
            return _error("Не удалось построить цепочку фильтров (пустой filter_complex).")

        if _cancelled(cancel_event):
            return _error(_CANCEL_MSG)

        if progress_callback:
            try:
                await progress_callback(8.0, "Запуск кодирования (FFmpeg)…")
            except Exception:
                pass

        creation       = _fake_creation_time()
        normalized_geo = _normalize_geo_profile(geo_profile)
        location       = _random_location_exif(geo_profile, geo_jitter)
        device, android_mfg, qt_make = resolve_device_fingerprint(device_model)

        ff = _ff.ffmpeg_bin()
        if shutil.which(ff) is None and ff == "ffmpeg":
            return _error("FFmpeg не найден. Установите FFmpeg или задайте FFMPEG_PATH.")

        # Рандомная строка encoder — разная между рендерами (расширенный пул).
        _encoder_variants = [
            "Lavf58.29.100", "Lavf58.45.100", "Lavf58.76.100", "Lavf58.78.100",
            "Lavf59.16.100", "Lavf59.20.100", "Lavf59.27.100",
            "Lavf60.3.100",  "Lavf60.10.100", "Lavf60.16.100",
            "Lavf61.1.100",  "Lavf61.7.100",
        ]
        encoder_str = random.choice(_encoder_variants)

        # Случайный vendor_id для потока (4 ASCII байта — стандарт MP4).
        _vendor_ids = ["FFMP", "appl", "MSFT", "GOOG"]
        vendor_id = random.choice(_vendor_ids)

        # Случайный handler_name — имя обработчика потока в MP4.
        _handler_names = [
            "VideoHandler", "MainConcept Video Media Handler",
            "GPAC ISO Video Handler", "Apple Video Media Handler",
        ]
        handler_name = random.choice(_handler_names)

        common_meta = [
            "-map_metadata", "-1",
            "-metadata", f"creation_time={creation}",
            "-metadata", f"com.android.manufacturer={android_mfg}",
            "-metadata", f"com.android.model={device}",
            "-metadata", f"com.apple.quicktime.make={qt_make}",
            "-metadata", f"com.apple.quicktime.model={device}",
            "-metadata", f"encoder={encoder_str}",
            "-metadata:s:v:0", f"handler_name={handler_name}",
            "-metadata:s:v:0", f"vendor_id={vendor_id}",
        ]
        if geo_enabled:
            common_meta.extend(["-metadata", f"location={location}"])

        # GOP рандомизация: keyframe interval меняет бинарную структуру файла.
        gop_size = random.randint(60, 360)

        audio_br = str(p["audio_bitrate"])
        nv_extra = ["-preset", "p5", "-cq", str(p["cq_nvenc"]), "-pix_fmt", "yuv420p", "-g", str(gop_size)]
        x264_extra = [
            "-preset",
            p["preset_x264"],
            "-crf",
            str(p["crf_x264"]),
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(gop_size),
        ]
        if preset_key == "soft":
            x264_extra.extend(["-tune", "film"])

        skip_nvenc = os.environ.get("NEORENDER_DISABLE_NVENC", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        encode_duration_sec = (
            float(effective_duration_sec) if effective_duration_sec else duration_sec
        )

        async def _apply_dub_audio(dub_path: str) -> bool:
            """Заменяет аудиодорожку в outp на дублированную (без перекодирования видео)."""
            tmp = outp.with_suffix(".dub_tmp.mp4")
            ff_bin = _ff.ffmpeg_bin()
            args = [
                ff_bin, "-y",
                "-i", str(outp),
                "-i", dub_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", audio_br,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                str(tmp),
            ]
            try:
                code, _, err = await _ff.run_ffmpeg_with_progress(
                    args, duration_sec=encode_duration_sec,
                    encode_label="Замена аудио (дубляж)…",
                )
                if code == 0 and tmp.is_file() and tmp.stat().st_size > 0:
                    tmp.replace(outp)
                    logger.info("dub_audio applied: %s", dub_path)
                    return True
                logger.warning("dub_audio FFmpeg failed (code=%s): %s", code, err[:200] if err else "")
                tmp.unlink(missing_ok=True)
            except Exception as exc:
                logger.exception("_apply_dub_audio: %s", exc)
                tmp.unlink(missing_ok=True)
            return False

        async def _success_payload(codec_name: str) -> dict[str, Any]:
            meta: dict[str, Any] = {
                "trim_lead_sec": round(trim_start_sec, 4),
                "trim_tail_sec": round(trim_tail_sec, 4),
                "content_duration_sec": round(float(effective_duration_sec), 4)
                if effective_duration_sec
                else None,
                "micro_resize_w": micro_dw,
                "micro_resize_h": micro_dh,
            }
            # ── Дубляж: заменяем аудиодорожку если есть dub_audio ────────────
            meta["dub_audio_applied"] = False
            if dub_audio_use:
                meta["dub_audio_applied"] = await _apply_dub_audio(dub_audio_use)
            # ── ASS субтитры подтверждаем в метаданных ────────────────────────
            meta["ass_subtitles_burned"] = bool(ass_use)
            meta["srt_subtitles_burned"] = bool(srt_use) and not bool(ass_use)
            try:
                lame_p = _audio_lame_roundtrip_probability()
                if with_audio and lame_p > 0 and random.random() < lame_p and not dub_audio_use:
                    meta["audio_lame_roundtrip"] = await _try_lame_aac_roundtrip(outp, audio_br)
                else:
                    meta["audio_lame_roundtrip"] = False
            except Exception as exc:
                logger.exception("post-encode lame roundtrip: %s", exc)
                meta["audio_lame_roundtrip"] = False
            try:
                if perceptual_hash_check:
                    od = await _ff.probe_video_duration_seconds(outp)
                    meta.update(
                        await _ph.compare_videos_phash(
                            inp,
                            outp,
                            trim_start_sec=trim_start_sec,
                            content_duration_sec=effective_duration_sec,
                            output_duration_sec=od,
                        )
                    )
                else:
                    meta["perceptual_skipped"] = True
                    meta["perceptual_diff_pct"] = None
                    meta["perceptual_too_similar"] = False
                    meta["perceptual_warning"] = None
            except Exception as exc:
                logger.exception("post-encode perceptual hash: %s", exc)
                meta["perceptual_skipped"] = True
                meta["perceptual_diff_pct"] = None
                meta["perceptual_too_similar"] = False
                meta["perceptual_warning"] = None
            return _ok(
                {
                    "output_path": str(outp.resolve()),
                    "codec": codec_name,
                    "preset": preset_key,
                    "template": template_key,
                    "geo_enabled": geo_enabled,
                    "geo_profile": normalized_geo,
                    "device_model": device,
                    **meta,
                }
            )

        if dry_run:
            args_x264 = build_luxury_encode_argv(
                ffmpeg_exe=ff,
                input_video=inp,
                overlay_media=ov,
                filter_complex=fc,
                video_map=vmap,
                with_audio=with_audio,
                audio_bitrate=audio_br,
                common_meta=common_meta,
                video_codec="libx264",
                extra_video_encoder_args=x264_extra,
                output_path=outp,
                main_input_ss_sec=main_input_ss,
                main_input_t_sec=main_input_t,
            )
            out_dr: dict[str, Any] = {
                "dry_run": True,
                "ffmpeg_args_x264": args_x264,
                "ffmpeg_args_primary": args_x264,
                "preset": preset_key,
                "template": template_key,
                "geo_enabled": geo_enabled,
                "geo_profile": normalized_geo,
                "device_model": device,
                "output_path": str(outp.resolve()),
                "trim_lead_sec": round(trim_start_sec, 4),
                "trim_tail_sec": round(trim_tail_sec, 4),
                "micro_resize_w": micro_dw,
                "micro_resize_h": micro_dh,
            }
            if not skip_nvenc:
                args_nv = build_luxury_encode_argv(
                    ffmpeg_exe=ff,
                    input_video=inp,
                    overlay_media=ov,
                    filter_complex=fc,
                    video_map=vmap,
                    with_audio=with_audio,
                    audio_bitrate=audio_br,
                    common_meta=common_meta,
                    video_codec="h264_nvenc",
                    extra_video_encoder_args=nv_extra,
                    output_path=outp,
                    main_input_ss_sec=main_input_ss,
                    main_input_t_sec=main_input_t,
                )
                out_dr["ffmpeg_args_nvenc"] = args_nv
                out_dr["ffmpeg_args_primary"] = args_nv
            else:
                out_dr["ffmpeg_args_nvenc"] = None
            return _ok(out_dr)

        err_nv = b""
        if not skip_nvenc:
            # NVENC
            nv_args = build_luxury_encode_argv(
                ffmpeg_exe=ff,
                input_video=inp,
                overlay_media=ov,
                filter_complex=fc,
                video_map=vmap,
                with_audio=with_audio,
                audio_bitrate=audio_br,
                common_meta=common_meta,
                video_codec="h264_nvenc",
                extra_video_encoder_args=nv_extra,
                output_path=outp,
                main_input_ss_sec=main_input_ss,
                main_input_t_sec=main_input_t,
            )
            code, _, err_nv = await _ff.run_ffmpeg_with_progress(
                nv_args,
                duration_sec=encode_duration_sec,
                progress_cb=progress_callback,
                encode_label="Кодирование (GPU, NVENC)",
                cancel_event=cancel_event,
            )
            if code == 0 and outp.is_file() and outp.stat().st_size > 0:
                return await _success_payload("h264_nvenc")

            if code == -9 or _cancelled(cancel_event):
                return _error(_CANCEL_MSG)

            if code == -124:
                return _error(
                    "Превышено время кодирования FFmpeg (таймаут). Проверьте исходник, фильтры и диск; "
                    "при необходимости увеличьте NEORENDER_FFMPEG_TIMEOUT_SEC в .env (0 — без лимита)."
                )

            logger.warning("NVENC не удался, пробуем libx264. stderr=%s", err_nv[-600:])
        else:
            logger.info("NVENC отключён (NEORENDER_DISABLE_NVENC), сразу libx264")

        x264_args = build_luxury_encode_argv(
            ffmpeg_exe=ff,
            input_video=inp,
            overlay_media=ov,
            filter_complex=fc,
            video_map=vmap,
            with_audio=with_audio,
            audio_bitrate=audio_br,
            common_meta=common_meta,
            video_codec="libx264",
            extra_video_encoder_args=x264_extra,
            output_path=outp,
            main_input_ss_sec=main_input_ss,
            main_input_t_sec=main_input_t,
        )
        code2, _, err2 = await _ff.run_ffmpeg_with_progress(
            x264_args,
            duration_sec=encode_duration_sec,
            progress_cb=progress_callback,
            encode_label="Кодирование (CPU, x264)",
            cancel_event=cancel_event,
        )
        if code2 == 0 and outp.is_file() and outp.stat().st_size > 0:
            return await _success_payload("libx264")

        if code2 == -9 or _cancelled(cancel_event):
            return _error(_CANCEL_MSG)

        if code2 == -124:
            return _error(
                "Превышено время кодирования FFmpeg (таймаут). Проверьте исходник, фильтры и диск; "
                "при необходимости увеличьте NEORENDER_FFMPEG_TIMEOUT_SEC в .env (0 — без лимита)."
            )

        logger.error("ffmpeg failed: %s", err2[-1200:])
        err_txt = err2.decode("utf-8", errors="replace") if isinstance(err2, bytes) else str(err2)
        if srt_use and ("subtitles" in err_txt.lower() or "libass" in err_txt.lower()):
            return _error(
                "Не удалось вшить SRT-субтитры. Установите FFmpeg со встроенным libass "
                "или отключите таймкодные субтитры."
            )
        merged_stderr = err2
        if err_nv.strip():
            merged_stderr = err2 + b"\n--- nvenc ---\n" + err_nv
        hint = _ffmpeg_stderr_hint(merged_stderr)
        err_txt_low = merged_stderr.decode("utf-8", errors="replace").lower()

        # Ошибка из-за слоя (битый PNG/JPG) — не путать с кодеком видео.
        _overlay_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        if "invalid png" in err_txt_low or (
            ov.suffix.lower() in _overlay_exts and "invalid" in err_txt_low
        ):
            return _error(
                "Файл слоя повреждён или не читается FFmpeg. "
                "Загрузите новый оверлей (PNG/JPG/WebP) и повторите рендер."
                + (f" Подробнее: {hint}" if hint else "")
            )

        base = "Не удалось обработать видео. Проверьте FFmpeg, кодек файла и драйвер видеокарты."
        codec_note = ""
        if src_codec:
            _PROBLEMATIC_CODECS = {"prores", "prores_ks", "prores_raw", "prores_lt", "prores_proxy"}
            if src_codec in _PROBLEMATIC_CODECS:
                codec_note = (
                    f" Файл содержит кодек {src_codec.upper()} (Apple ProRes) —"
                    f" нужна сборка FFmpeg с поддержкой этого декодера;"
                    f" проще перекодировать исходник в H.264/AAC (MP4) и загрузить снова."
                )
            elif inp.suffix.lower() == ".mov":
                codec_note = (
                    f" Файл .mov содержит кодек {src_codec.upper()}."
                    f" Если он нестандартный, перекодируйте в H.264/AAC (MP4) и загрузите снова."
                )
        elif inp.suffix.lower() == ".mov":
            codec_note = (
                " Файлы .mov часто в ProRes/HEVC — нужна полная сборка FFmpeg с декодером;"
                " проще перекодировать исходник в H.264/AAC (MP4) и загрузить снова."
            )
        if hint:
            return _error(f"{base}{codec_note} Подробнее: {hint}")
        return _error(f"{base}{codec_note}")

    except Exception as exc:
        logger.exception("render_unique_video: %s", exc)
        detail = str(exc).strip().replace("\n", " ")
        if len(detail) > 280:
            detail = detail[:277] + "…"
        if detail:
            return _error(f"Произошла ошибка при уникализации видео: {type(exc).__name__}: {detail}")
        return _error("Произошла ошибка при уникализации видео.")
    finally:
        for p in cleanup_txt:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
