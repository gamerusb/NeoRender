"""
ubt_detector.py — LLM-ядро детектора арбитражного (UBT) контента.

Получает метаданные видео и классифицирует их через Groq Chat:
  {"status": "UBT_FOUND", "niche": "...", "confidence": 85, "triggers": [...], "download_url": "..."}
  {"status": "ORGANIC"}

Интегрируется в pipeline через classify_video() или batch_classify().
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=15)
_DEFAULT_MODEL = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = """\
Ты — антифрод OSINT-алгоритм для обнаружения арбитражного (UBT) трафика в YouTube Shorts.

## Задача
Проанализируй метаданные видео по 3 векторам и определи — является ли оно арбитражным (UBT) или органическим контентом.

## Векторы анализа

### Вектор 1: Аномалии метаданных
- Мусорные теги-якоря: #inout, #cpa, #traff, #affiliate, #earn, #монетизация со скрытыми суффиксами
- Обфускация текста: замена кириллицы на латиницу (с→c, а→a, о→o), пробелы между буквами слов («з а р а б о т о к»), скрытые unicode-символы
- Кликбейт-несоответствие: упоминания денег/заработка при тегах с играми/мемами

### Вектор 2: Воронка трафика
- CTA в описании/транскрипте: «ссылка в шапке», «переходи в профиль», «жми на ник», «промокод», «регистрация»
- Замаскированные ссылки в закреплённом комментарии: «t . me», «bit.ly», «vk.cc», ссылки с пробелами
- Призывы к действию с финансовой мотивацией: «получи бонус», «первый депозит», «фриспины»

### Вектор 3: Визуальные маркеры (из OCR)
- Промокоды на экране: BONUS200, FREE100, WELCOME и аналоги
- Интерфейсы казино: слоты, рулетка, ставки
- Фейковые банковские чеки/транзакции, «скрины выплат»
- Формат split-screen: «до/после», «было/стало», реакция на выигрыш

## Порог срабатывания
confidence > 75 И не менее 2 паттернов из РАЗНЫХ векторов

## Входные данные
JSON-объект с полями:
- title: заголовок видео
- description: описание
- tags: список тегов
- ocr_text: текст с кадров (если доступно)
- transcript: аудио-транскрипт (если доступно)
- pinned_comment: закреплённый комментарий (если доступно)
- url: ссылка на видео

## Формат ответа
Если UBT обнаружен:
{"status": "UBT_FOUND", "niche": "гемблинг/крипта/дейтинг/схемы", "confidence": 85, "triggers": ["описание триггера 1", "описание триггера 2"], "download_url": "<url>"}

Если органический контент:
{"status": "ORGANIC"}

Никаких дополнительных рассуждений, только сухой вывод.\
"""


def _build_user_message(video: dict[str, Any]) -> str:
    payload = {
        "title": str(video.get("title") or ""),
        "description": str(video.get("description") or ""),
        "tags": video.get("tags") or [],
        "ocr_text": str(video.get("ocr_text") or ""),
        "transcript": str(video.get("transcript") or ""),
        "pinned_comment": str(video.get("pinned_comment") or ""),
        "url": str(video.get("url") or video.get("webpage_url") or ""),
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_response(content: str) -> dict[str, Any]:
    text = content.strip()
    if "```" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return {"status": "ORGANIC"}
        status = str(data.get("status") or "ORGANIC").upper()
        if status == "UBT_FOUND":
            return {
                "status": "UBT_FOUND",
                "niche": str(data.get("niche") or "unknown"),
                "confidence": int(data.get("confidence") or 0),
                "triggers": list(data.get("triggers") or []),
                "download_url": str(data.get("download_url") or ""),
            }
        return {"status": "ORGANIC"}
    except Exception:
        return {"status": "ORGANIC"}


async def classify_video(
    video: dict[str, Any],
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Классифицирует одно видео через LLM.
    Возвращает {"status": "UBT_FOUND"|"ORGANIC", ...} или {"status": "ERROR", "message": ...}.
    """
    key = (api_key or os.environ.get("GROQ_API_KEY") or "").strip()
    if not key:
        return {"status": "ERROR", "message": "GROQ_API_KEY not set"}

    chosen_model = (model or os.environ.get("GROQ_MODEL_UBT") or _DEFAULT_MODEL).strip()

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(video)},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(GROQ_CHAT_URL, headers=headers, json=body) as resp:
                raw = await resp.read()
                try:
                    payload = json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    logger.warning("ubt_detector: non-json response: %s", raw[:200])
                    return {"status": "ERROR", "message": "bad_response"}

                if resp.status >= 400:
                    err = payload.get("error", {}) if isinstance(payload, dict) else {}
                    msg = str(err.get("message", "")) if isinstance(err, dict) else str(err)
                    logger.warning("ubt_detector: HTTP %s: %s", resp.status, msg)
                    return {"status": "ERROR", "message": f"HTTP {resp.status}"}

                choices = payload.get("choices") if isinstance(payload, dict) else None
                if not choices or not isinstance(choices, list):
                    return {"status": "ERROR", "message": "no_choices"}

                msg_obj = choices[0].get("message") if isinstance(choices[0], dict) else None
                content = msg_obj.get("content") if isinstance(msg_obj, dict) else None
                if not isinstance(content, str):
                    return {"status": "ERROR", "message": "no_content"}

                return _parse_response(content)

    except asyncio.TimeoutError:
        logger.warning("ubt_detector: timeout for video %s", video.get("url") or video.get("id"))
        return {"status": "ERROR", "message": "timeout"}
    except aiohttp.ClientError as exc:
        logger.warning("ubt_detector: network error: %s", exc)
        return {"status": "ERROR", "message": "network"}
    except Exception as exc:
        logger.exception("ubt_detector: unexpected: %s", exc)
        return {"status": "ERROR", "message": "unknown"}


async def batch_classify(
    videos: list[dict[str, Any]],
    api_key: str | None = None,
    model: str | None = None,
    concurrency: int = 3,
) -> list[dict[str, Any]]:
    """
    Классифицирует список видео с ограничением параллельности.
    Возвращает список результатов в том же порядке.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(video: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            result = await classify_video(video, api_key=api_key, model=model)
            return {**result, "_video_id": video.get("id") or video.get("url") or ""}

    return await asyncio.gather(*[_one(v) for v in videos])
