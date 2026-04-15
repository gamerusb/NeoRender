from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        raw = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def build_recommendations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    views_pool = [_safe_int(r.get("views"), 0) for r in rows]
    baseline = max(100, int(median(views_pool))) if views_pool else 100
    out: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for row in rows:
        views = max(0, _safe_int(row.get("views"), 0))
        likes = max(0, _safe_int(row.get("likes"), 0))
        status = str(row.get("status") or "active").strip().lower()
        like_rate = (likes / views) if views > 0 else 0.0

        pub = _parse_dt(row.get("published_at"))
        age_h = (now - pub).total_seconds() / 3600.0 if pub is not None else None

        reasons: list[str] = []
        steps: list[str] = []
        score = 65

        low_views_threshold = max(120, int(baseline * 0.35))

        if status == "banned":
            score = 15
            reasons.append("Недоступно/блокировка: ролик не получает дистрибуцию.")
            steps.extend(
                [
                    "Пересобрать ролик с новым аудио/визуалом и перезалить как новую версию.",
                    "Убрать спорные фразы в title/description и нейтрализовать формулировки.",
                    "Сделать 3 новых хука (первые 1-2 сек) и протестировать пакетом.",
                ]
            )
        elif status == "shadowban":
            score = 30
            reasons.append("Низкая дистрибуция: возможный shadowban или слабый стартовый сигнал.")
            steps.extend(
                [
                    "Сократить длительность версии до 18-28 сек и усилить первый кадр/хук.",
                    "Переиздать с новой обложкой-кадром и другой первой строкой title.",
                    "Добавить явный CTA на комментарий в последние 2-3 секунды.",
                ]
            )
        else:
            if views < low_views_threshold:
                score -= 25
                reasons.append("Слабый хук/упаковка: ролик набирает ниже базовой медианы.")
                steps.append("Сделать 3 варианта хука и перезапустить A/B пакет.")
            if views > 0 and like_rate < 0.015:
                score -= 15
                reasons.append("Низкая вовлеченность: лайков мало относительно просмотров.")
                steps.append("Усилить CTA: попросить мнение/выбор в комментариях в конце ролика.")
            if age_h is not None and age_h >= 24 and views < max(200, int(baseline * 0.5)):
                score -= 10
                reasons.append("После 24ч нет разгона: вероятно, не сработали длительность/ритм.")
                steps.append("Переиздать укороченную версию с более плотным монтажом.")

            if not reasons:
                score = max(score, 78)
                reasons.append("Метрики в пределах нормы: ролик можно масштабировать.")
                steps.extend(
                    [
                        "Сделать 2-3 близкие вариации заголовка и первого кадра.",
                        "Увеличить частоту публикаций этого контент-угла.",
                    ]
                )

        out.append(
            {
                "id": row.get("id"),
                "video_url": row.get("video_url"),
                "status": status,
                "views": views,
                "likes": likes,
                "like_rate": round(like_rate * 100.0, 2),
                "health_score": max(1, min(99, int(score))),
                "diagnosis": reasons[:3],
                "next_steps": steps[:4],
            }
        )
    return out

