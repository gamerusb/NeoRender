"""
Сравнение двух роликов по perceptual hash (pHash), близко к тому, как оценивают похожесть кадров многие системы.

Требует: Pillow, imagehash (см. requirements.txt). Если пакетов нет — сравнение тихо пропускается.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

from core import ffmpeg_runner as _ff

logger = logging.getLogger(__name__)

# Ниже этого среднего отличия по битам pHash (в %) считаем, что результат слишком близок к оригиналу.
# 25% — более консервативный порог: YouTube Content ID способен матчить при diff < 30% в ряде сценариев.
PHASH_LOW_DIFF_WARNING_PCT = 25.0

try:
    import imagehash
    from PIL import Image
except ImportError:
    imagehash = None  # type: ignore[assignment, misc]
    Image = None  # type: ignore[assignment, misc]


def perceptual_hash_available() -> bool:
    return imagehash is not None and Image is not None


def _phash_distance_pct(png_a: bytes, png_b: bytes) -> float | None:
    if not perceptual_hash_available():
        return None

    def _work() -> float:
        im1 = Image.open(io.BytesIO(png_a))
        im2 = Image.open(io.BytesIO(png_b))
        h1 = imagehash.phash(im1)
        h2 = imagehash.phash(im2)
        dist = h1 - h2
        bits = 64.0
        return min(100.0, max(0.0, (dist / bits) * 100.0))

    try:
        return float(_work())
    except Exception:
        logger.debug("perceptual hash: не удалось сравнить кадры", exc_info=True)
        return None


async def compare_videos_phash(
    original: Path,
    rendered: Path,
    *,
    trim_start_sec: float = 0.0,
    content_duration_sec: float | None,
    output_duration_sec: float | None,
    samples: int = 5,
) -> dict[str, object]:
    """
    Достаём несколько пар кадров на согласованных отметках времени и усредняем отличие pHash (0–100%).

    diff_pct — средняя доля отличающихся битов хеша; чем выше, тем сильнее визуальное отличие.
    too_similar — True если diff_pct < PHASH_LOW_DIFF_WARNING_PCT.
    """
    out: dict[str, object] = {
        "perceptual_diff_pct": None,
        "perceptual_too_similar": False,
        "perceptual_warning": None,
        "perceptual_skipped": True,
    }
    if not perceptual_hash_available():
        out["perceptual_skipped"] = True
        out["perceptual_warning"] = None
        return out

    cd = content_duration_sec
    od = output_duration_sec
    if cd is None or od is None or cd < 0.15 or od < 0.15:
        return out

    base = min(float(cd), float(od))
    ts = max(0.0, float(trim_start_sec))
    diffs: list[float] = []
    n = max(2, min(12, int(samples)))
    for i in range(n):
        u = (i + 1.0) / (n + 1.0)
        t_content = u * base
        t_orig = ts + t_content
        t_out = t_content
        if t_orig < 0 or t_out < 0:
            continue
        png_o = await _ff.extract_video_frame_png_bytes(original, time_sec=t_orig)
        png_r = await _ff.extract_video_frame_png_bytes(rendered, time_sec=t_out)
        if not png_o or not png_r:
            continue
        p = await asyncio.to_thread(_phash_distance_pct, png_o, png_r)
        if p is not None:
            diffs.append(p)

    if not diffs:
        out["perceptual_skipped"] = True
        return out

    avg = sum(diffs) / len(diffs)
    out["perceptual_diff_pct"] = round(avg, 2)
    out["perceptual_skipped"] = False
    if avg < PHASH_LOW_DIFF_WARNING_PCT:
        out["perceptual_too_similar"] = True
        out["perceptual_warning"] = (
            f"Кадры результата близки к оригиналу по pHash (среднее отличие {avg:.1f}% < "
            f"{PHASH_LOW_DIFF_WARNING_PCT:.0f}%). Для платформ вроде YouTube имеет смысл усилить уникализацию."
        )
    return out
