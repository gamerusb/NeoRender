"""
Генерация заголовка, описания, закреплённого комментария и короткой строки
для вшивания на видео (overlay_text) через Groq Chat (Llama и др.).

Ключ API не хранится в коде: передайте api_key из UI/хранилища или задайте
переменную окружения GROQ_API_KEY.

При любой ошибке сети, таймауте или битом JSON возвращается безопасный
запасной вариант на корейском — пайплайн не прерывается.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
# Быстрая бесплатная модель на Groq (можно сменить через GROQ_MODEL).
_DEFAULT_MODEL = "llama-3.1-8b-instant"
_TIMEOUT = aiohttp.ClientTimeout(total=45, connect=15)
# Лёгкий ping без расхода токенов чата.
_PING_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=8)

# Запасные тексты на корейском (ниша «шорты / казино» — нейтральный кликбейт).
_FALLBACK_TITLES = [
    "이 조합 실화? 🔥 지금 확인하세요!",
    "단 60초! 놓치면 후회하는 쇼츠",
    "지금 바로 도전! 역대급 반전",
    "한국인이라면 무조건 봐야 할 영상",
    "클릭 1번이면 끝? 놀라운 결과",
]
_FALLBACK_DESCRIPTIONS = [
    "짧고 강렬한 한 판, 지금 플레이하세요. #쇼츠 #한국 #바이럴",
    "60초 안에 몰입! 댓글로 의견 남겨주세요. #Shorts #추천 #실시간",
    "마지막 반전 주의! 구독과 좋아요 부탁드립니다. #YouTube #쇼츠 #이벤트",
]
_FALLBACK_COMMENTS = [
    "핀 댓글: 오늘의 추천 조합은 여기 정리했어요 👇 좋아요 눌러주세요!",
    "고정: 다음 영상도 곧 올라옵니다. 알림 켜두세요!",
]
# Короткая строка для вшивания на кадр (ASS/subtitles), без Whisper / SRT.
_FALLBACK_OVERLAY = [
    "지금 확인! 🔥",
    "놓치지 마세요",
    "단 60초 몰입",
    "마지막 반전 주의",
    "한 판 더! 👇",
]


def _fallback_metadata(niche: str) -> dict[str, str]:
    """Всегда валидный dict для загрузчика (ниша только для лога/разнообразия)."""
    niche_hint = (niche or "Shorts").strip()[:40]
    title = random.choice(_FALLBACK_TITLES)
    description = random.choice(_FALLBACK_DESCRIPTIONS)
    if niche_hint:
        title = f"{title} | {niche_hint}"
        description = f"{description} #{niche_hint.replace(' ', '')}"
    return {
        "title": title,
        "description": description,
        "comment": random.choice(_FALLBACK_COMMENTS),
        "overlay_text": random.choice(_FALLBACK_OVERLAY),
    }


def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    out.update(data)
    return out


async def ping_groq_api(api_key: str | None) -> dict[str, Any]:
    """
    Проверка ключа: GET /openai/v1/models (не списывает токены чата).
    Возвращает {"live": bool, "message": str}.
    """
    k = (api_key or "").strip()
    if not k:
        return {"live": False, "message": "Ключ не задан"}
    headers = {"Authorization": f"Bearer {k}"}
    try:
        async with aiohttp.ClientSession(timeout=_PING_TIMEOUT) as session:
            async with session.get(GROQ_MODELS_URL, headers=headers) as resp:
                if resp.status == 200:
                    return {"live": True, "message": "API на связи"}
                if resp.status == 401:
                    return {"live": False, "message": "Ключ недействителен"}
                return {"live": False, "message": f"HTTP {resp.status}"}
    except asyncio.TimeoutError:
        return {"live": False, "message": "Таймаут Groq"}
    except aiohttp.ClientError as exc:
        logger.debug("ping_groq_api: %s", exc)
        return {"live": False, "message": "Нет сети до api.groq.com"}
    except Exception as exc:
        logger.warning("ping_groq_api: %s", exc)
        return {"live": False, "message": "Ошибка проверки Groq"}


def _build_prompt(niche: str) -> str:
    return (
        f'Generate a viral YouTube Shorts title, a 2-sentence description with 3 hashtags, '
        f'a pinned comment, and ONE very short on-screen caption (max ~50 characters, Korean) '
        f'for burning into the video — no timestamps, single line, punchy. '
        f'Niche: {niche}. Language: Korean for all fields. '
        f'Return ONLY valid JSON: '
        f'{{"title": "...", "description": "...", "comment": "...", "overlay_text": "..."}}'
    )


def _parse_llm_json(content: str) -> dict[str, str] | None:
    """Достаёт JSON из ответа модели (иногда оборачивает в ```json)."""
    try:
        text = content.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        title = data.get("title")
        desc = data.get("description")
        comment = data.get("comment")
        if not all(isinstance(x, str) and x.strip() for x in (title, desc, comment)):
            return None
        overlay = data.get("overlay_text")
        if isinstance(overlay, str) and overlay.strip():
            overlay = overlay.strip()[:500]
        else:
            # Модель могла забыть поле — берём начало заголовка
            t = title.strip()
            overlay = t[:72] + ("…" if len(t) > 72 else "")
        return {
            "title": title.strip(),
            "description": desc.strip(),
            "comment": comment.strip(),
            "overlay_text": overlay,
        }
    except Exception:
        return None


async def generate_metadata(api_key: str | None, niche: str) -> dict[str, Any]:
    """
    Запрос к Groq Chat Completions. При сбое возвращает status=ok и fallback,
    чтобы оркестратор не падал (для UI можно проверить поле used_fallback).
    """
    key = (api_key or os.environ.get("GROQ_API_KEY") or "").strip()
    niche_clean = (niche or "general").strip() or "general"

    if not key:
        logger.warning("generate_metadata: нет API ключа Groq, используем запасной текст.")
        fb = _fallback_metadata(niche_clean)
        return _ok({**fb, "used_fallback": True, "reason": "no_api_key"})

    model = os.environ.get("GROQ_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": _build_prompt(niche_clean),
            }
        ],
        "temperature": 0.85,
        "max_tokens": 512,
    }

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(GROQ_CHAT_URL, headers=headers, json=body) as resp:
                raw = await resp.read()
                try:
                    payload = json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    logger.warning("Groq non-json: %s", raw[:400])
                    fb = _fallback_metadata(niche_clean)
                    return _ok({**fb, "used_fallback": True, "reason": "bad_response"})

                if resp.status >= 400:
                    err_msg = ""
                    if isinstance(payload, dict):
                        err = payload.get("error")
                        if isinstance(err, dict):
                            err_msg = str(err.get("message", ""))
                    logger.warning("Groq HTTP %s: %s", resp.status, err_msg or raw[:200])
                    fb = _fallback_metadata(niche_clean)
                    return _ok({**fb, "used_fallback": True, "reason": "http_error"})

                if not isinstance(payload, dict):
                    fb = _fallback_metadata(niche_clean)
                    return _ok({**fb, "used_fallback": True, "reason": "invalid_payload"})

                choices = payload.get("choices")
                if not choices or not isinstance(choices, list):
                    fb = _fallback_metadata(niche_clean)
                    return _ok({**fb, "used_fallback": True, "reason": "no_choices"})

                msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, str):
                    fb = _fallback_metadata(niche_clean)
                    return _ok({**fb, "used_fallback": True, "reason": "no_content"})

                parsed = _parse_llm_json(content)
                if not parsed:
                    logger.warning("Groq bad JSON content: %s", content[:300])
                    fb = _fallback_metadata(niche_clean)
                    return _ok({**fb, "used_fallback": True, "reason": "parse_error"})

                return _ok({**parsed, "used_fallback": False})
    except TimeoutError:
        logger.warning("Groq timeout")
        fb = _fallback_metadata(niche_clean)
        return _ok({**fb, "used_fallback": True, "reason": "timeout"})
    except aiohttp.ClientError as exc:
        logger.exception("Groq client error: %s", exc)
        fb = _fallback_metadata(niche_clean)
        return _ok({**fb, "used_fallback": True, "reason": "network"})
    except Exception as exc:
        logger.exception("generate_metadata: %s", exc)
        fb = _fallback_metadata(niche_clean)
        return _ok({**fb, "used_fallback": True, "reason": "unknown"})


