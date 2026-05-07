"""
Генерация метаданных для YouTube Shorts через Groq Chat (Llama и др.).

Функции
-------
generate_metadata(api_key, niche)
    Базовый вызов — один заголовок/описание/комментарий/overlay.

generate_viral_metadata(api_key, niche, competitor_examples, hook_pattern, n_variants)
    Улучшенный вызов: конкурентные примеры + hook-паттерн + 5 вариантов заголовка.
    competitor_examples — список dict {title, view_count} из content_scraper.

generate_caption_sequence(api_key, niche, duration_sec, competitor_examples)
    Генерирует SRT-строку с 3-фазной caption-последовательностью для Shorts:
    hook (0–3с) → удержание (середина) → CTA (последние 3с).

ping_groq_api(api_key)
    Проверка ключа без расхода токенов чата.

При любой ошибке возвращается status=ok с fallback-данными — пайплайн не прерывается.
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
_DEFAULT_MODEL = "llama-3.1-8b-instant"
_TIMEOUT = aiohttp.ClientTimeout(total=45, connect=15)
_PING_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=8)

# NOTE: При переходе на Anthropic Claude добавить в system-сообщение:
#   {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "breakpoint"}}
# Это снизит расход токенов ~на 75% при повторных вызовах (кэш живёт 5 мин).

_http_session: aiohttp.ClientSession | None = None


async def _get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(limit=4, keepalive_timeout=60)
        _http_session = aiohttp.ClientSession(timeout=_TIMEOUT, connector=connector)
    return _http_session


# ── Fallback-данные ───────────────────────────────────────────────────────────

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
_FALLBACK_OVERLAY = [
    "지금 확인! 🔥",
    "놓치지 마세요",
    "단 60초 몰입",
    "마지막 반전 주의",
    "한 판 더! 👇",
]

# 3-фазные caption fallback-последовательности
_FALLBACK_CAPTIONS = [
    [
        {"time": 0.5,  "text": "⚠️ 끝까지 봐"},
        {"time": 5.0,  "text": "이게 진짜...?"},
        {"time": -3.0, "text": "구독 = 다음편 🔔"},
    ],
    [
        {"time": 0.5,  "text": "잠깐!! 실화임?"},
        {"time": 6.0,  "text": "반전 주의 👀"},
        {"time": -3.0, "text": "좋아요 눌러줘 🙏"},
    ],
]


def _fallback_metadata(niche: str) -> dict[str, Any]:
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
        "title_variants": [{"title": title, "hook_type": "curiosity", "ctr_score": 70}],
    }


def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    out.update(data)
    return out


# ── Ping ──────────────────────────────────────────────────────────────────────

async def ping_groq_api(api_key: str | None) -> dict[str, Any]:
    """Проверка ключа: GET /openai/v1/models (не списывает токены чата)."""
    k = (api_key or "").strip()
    if not k:
        return {"live": False, "message": "Ключ не задан"}
    headers = {"Authorization": f"Bearer {k}"}
    try:
        session = await _get_http_session()
        async with session.get(GROQ_MODELS_URL, headers=headers, timeout=_PING_TIMEOUT) as resp:
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


# ── Промпты ───────────────────────────────────────────────────────────────────

_HOOK_DESCRIPTIONS = {
    "curiosity": (
        "CURIOSITY GAP: title must withhold the result — ends with '...', '반전주의', '결말 충격' "
        "or similar cliff-hanger. Never reveal the outcome."
    ),
    "number": (
        "NUMBER HOOK: title MUST start with a specific number or quantity "
        "(e.g., '이거 3번 봤는데', '5초 안에', '100만원짜리'). Numbers stop the scroll."
    ),
    "interrupt": (
        "PATTERN INTERRUPT: title starts with a sudden exclamation mid-action "
        "(e.g., '잠깐!!', '멈춰!!', '실화임?', '이게 됩니까??'). Feels like someone grabbed your arm."
    ),
    "auto": (
        "Choose the BEST hook type (curiosity/number/interrupt) based on the niche. "
        "Mix different hook types across variants."
    ),
}


def _competitor_block(competitor_examples: list[dict[str, Any]]) -> str:
    """Форматирует топ-видео конкурентов как few-shot примеры для промпта."""
    if not competitor_examples:
        return ""
    lines = ["TOP PERFORMING Shorts this week (study these patterns CAREFULLY):"]
    for i, v in enumerate(competitor_examples[:8], 1):
        title = str(v.get("title") or "").strip()
        views = int(v.get("view_count") or 0)
        if not title:
            continue
        views_fmt = f"{views / 1_000_000:.1f}M" if views >= 1_000_000 else f"{views // 1000}K"
        lines.append(f'  {i}. "{title}" → {views_fmt} views')
    if len(lines) == 1:
        return ""
    lines.append("Replicate the STRUCTURE and EMOTIONAL TRIGGERS of these titles, not the exact words.")
    return "\n".join(lines)


def _build_viral_prompt(
    niche: str,
    competitor_examples: list[dict[str, Any]],
    hook_pattern: str,
    n_variants: int,
) -> str:
    hook_desc = _HOOK_DESCRIPTIONS.get(hook_pattern, _HOOK_DESCRIPTIONS["auto"])
    comp_block = _competitor_block(competitor_examples)
    comp_section = f"\n\n{comp_block}" if comp_block else ""

    return f"""You are a viral Korean YouTube Shorts expert. Your task: generate maximum-CTR metadata.{comp_section}

NICHE: {niche}
HOOK RULE: {hook_desc}
LANGUAGE: Korean for ALL text fields.

Generate EXACTLY {n_variants} title variants ranked by predicted CTR (best first).
Also generate: description (2 sentences + 3 hashtags), pinned comment, and overlay_text (≤50 chars, single punchy line for burning into video).

Return ONLY this JSON (no markdown, no explanation):
{{
  "variants": [
    {{"title": "...", "hook_type": "curiosity|number|interrupt", "ctr_score": 0-100}},
    {{"title": "...", "hook_type": "...", "ctr_score": 0-100}}
  ],
  "description": "...",
  "comment": "...",
  "overlay_text": "..."
}}"""


def _build_basic_prompt(niche: str) -> str:
    return (
        f'Generate a viral YouTube Shorts title, a 2-sentence description with 3 hashtags, '
        f'a pinned comment, and ONE very short on-screen caption (max ~50 characters, Korean) '
        f'for burning into the video — no timestamps, single line, punchy. '
        f'Niche: {niche}. Language: Korean for all fields. '
        f'Return ONLY valid JSON: '
        f'{{"title": "...", "description": "...", "comment": "...", "overlay_text": "..."}}'
    )


def _build_caption_sequence_prompt(
    niche: str,
    duration_sec: float,
    competitor_examples: list[dict[str, Any]],
) -> str:
    comp_block = _competitor_block(competitor_examples)
    comp_section = f"\n\n{comp_block}" if comp_block else ""
    mid_time = round(duration_sec * 0.35, 1)
    end_time = round(max(duration_sec - 3.5, duration_sec * 0.75), 1)

    return f"""You are a viral Korean YouTube Shorts caption writer.{comp_section}

NICHE: {niche}
VIDEO DURATION: {duration_sec:.0f} seconds

Create a 3-phase caption sequence that maximises retention and loop replays:
  Phase 1 (HOOK, ~0.5s): stop the swipe — short shock/curiosity in ≤15 chars
  Phase 2 (HOLD, ~{mid_time}s): deepen engagement — builds tension/anticipation in ≤20 chars
  Phase 3 (CTA, ~{end_time}s): convert viewer — subscribe/loop nudge in ≤18 chars

All text in Korean. Emojis allowed (1 per line max).

Return ONLY this JSON:
{{
  "captions": [
    {{"time": 0.5, "text": "..."}},
    {{"time": {mid_time}, "text": "..."}},
    {{"time": {end_time}, "text": "..."}}
  ]
}}"""


# ── Парсеры ───────────────────────────────────────────────────────────────────

def _parse_basic_json(content: str) -> dict[str, str] | None:
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
        if not (isinstance(overlay, str) and overlay.strip()):
            t = str(title).strip()
            overlay = t[:72] + ("…" if len(t) > 72 else "")
        return {
            "title": str(title).strip(),
            "description": str(desc).strip(),
            "comment": str(comment).strip(),
            "overlay_text": str(overlay).strip()[:500],
        }
    except Exception:
        return None


def _parse_viral_json(content: str, n_variants: int) -> dict[str, Any] | None:
    """Парсит расширенный ответ с variants[], description, comment, overlay_text."""
    try:
        text = content.strip()
        # Извлекаем JSON если обёрнут в markdown-блок
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        data = json.loads(text)
        if not isinstance(data, dict):
            return None

        variants_raw = data.get("variants")
        desc = str(data.get("description") or "").strip()
        comment = str(data.get("comment") or "").strip()
        overlay = str(data.get("overlay_text") or "").strip()[:500]

        if not (desc and comment):
            return None

        variants: list[dict[str, Any]] = []
        if isinstance(variants_raw, list):
            for v in variants_raw:
                if not isinstance(v, dict):
                    continue
                t = str(v.get("title") or "").strip()
                if not t:
                    continue
                variants.append({
                    "title": t,
                    "hook_type": str(v.get("hook_type") or "auto").strip(),
                    "ctr_score": max(0, min(100, int(v.get("ctr_score") or 70))),
                })

        if not variants:
            return None

        # Берём лучший вариант как основной заголовок
        best = variants[0]
        if not overlay:
            overlay = best["title"][:72]

        return {
            "title": best["title"],
            "description": desc,
            "comment": comment,
            "overlay_text": overlay,
            "title_variants": variants[:n_variants],
        }
    except Exception:
        return None


def _parse_caption_json(content: str, duration_sec: float) -> list[dict[str, Any]] | None:
    """Парсит caption-sequence ответ в список {time, text}."""
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
        captions_raw = data.get("captions")
        if not isinstance(captions_raw, list):
            return None
        result = []
        for c in captions_raw:
            if not isinstance(c, dict):
                continue
            t = str(c.get("text") or "").strip()
            if not t:
                continue
            time_val = float(c.get("time") or 0.5)
            result.append({"time": time_val, "text": t})
        return result if result else None
    except Exception:
        return None


# ── Общий HTTP-вызов к Groq ───────────────────────────────────────────────────

async def _groq_chat(
    key: str,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.85,
) -> str | None:
    """Возвращает content строку или None при ошибке."""
    model = os.environ.get("GROQ_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        session = await _get_http_session()
        async with session.post(GROQ_CHAT_URL, headers=headers, json=body) as resp:
            raw = await resp.read()
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                logger.warning("Groq non-json: %s", raw[:400])
                return None
            if resp.status >= 400:
                err = payload.get("error", {}) if isinstance(payload, dict) else {}
                logger.warning("Groq HTTP %s: %s", resp.status, err.get("message", raw[:200]))
                return None
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if not choices or not isinstance(choices, list):
                return None
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            return content if isinstance(content, str) else None
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("Groq timeout")
        return None
    except aiohttp.ClientError as exc:
        logger.exception("Groq client error: %s", exc)
        return None
    except Exception as exc:
        logger.exception("_groq_chat: %s", exc)
        return None


# ── Публичный API ─────────────────────────────────────────────────────────────

async def generate_metadata(api_key: str | None, niche: str) -> dict[str, Any]:
    """
    Базовый вызов — один заголовок + описание + комментарий + overlay.
    Оставлен для обратной совместимости; внутри вызывает generate_viral_metadata.
    """
    return await generate_viral_metadata(
        api_key=api_key,
        niche=niche,
        competitor_examples=[],
        hook_pattern="auto",
        n_variants=1,
    )


async def generate_viral_metadata(
    api_key: str | None,
    niche: str,
    competitor_examples: list[dict[str, Any]] | None = None,
    hook_pattern: str = "auto",
    n_variants: int = 5,
) -> dict[str, Any]:
    """
    Расширенная генерация с конкурентными примерами и 5 вариантами заголовка.

    Параметры
    ---------
    api_key           : ключ Groq (или env GROQ_API_KEY)
    niche             : ниша / тема видео
    competitor_examples : список dict {title, view_count} из content_scraper.search_videos()
                         — передаются как few-shot примеры в промпт
    hook_pattern      : "curiosity" | "number" | "interrupt" | "auto"
    n_variants        : сколько вариантов заголовка вернуть (1–10, обычно 5)

    Возвращает
    ----------
    status=ok + {title, description, comment, overlay_text, title_variants[]}
    """
    key = (api_key or os.environ.get("GROQ_API_KEY") or "").strip()
    niche_clean = (niche or "general").strip() or "general"
    examples = competitor_examples or []
    n = max(1, min(10, int(n_variants)))
    hook = hook_pattern if hook_pattern in _HOOK_DESCRIPTIONS else "auto"

    if not key:
        logger.warning("generate_viral_metadata: нет ключа Groq, используем fallback.")
        fb = _fallback_metadata(niche_clean)
        return _ok({**fb, "used_fallback": True, "reason": "no_api_key"})

    # Используем расширенный промпт когда нужно несколько вариантов или есть примеры
    use_viral = n > 1 or bool(examples) or hook != "auto"

    if use_viral:
        prompt = _build_viral_prompt(niche_clean, examples, hook, n)
        max_tok = 800 + n * 80
    else:
        prompt = _build_basic_prompt(niche_clean)
        max_tok = 512

    content = await _groq_chat(key, prompt, max_tokens=max_tok)

    if content is None:
        fb = _fallback_metadata(niche_clean)
        return _ok({**fb, "used_fallback": True, "reason": "api_error"})

    # Сначала пробуем расширенный парсер, потом базовый
    parsed: dict[str, Any] | None = None
    if use_viral:
        parsed = _parse_viral_json(content, n)
    if parsed is None:
        basic = _parse_basic_json(content)
        if basic:
            parsed = {**basic, "title_variants": [{"title": basic["title"], "hook_type": "auto", "ctr_score": 70}]}

    if not parsed:
        logger.warning("generate_viral_metadata: не удалось распарсить ответ LLM: %s", content[:300])
        fb = _fallback_metadata(niche_clean)
        return _ok({**fb, "used_fallback": True, "reason": "parse_error"})

    return _ok({**parsed, "used_fallback": False, "hook_pattern": hook})


async def generate_caption_sequence(
    api_key: str | None,
    niche: str,
    duration_sec: float = 30.0,
    competitor_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Генерирует 3-фазную caption-последовательность для Shorts.

    Возвращает
    ----------
    status=ok + {captions: [{time, text}], srt: "<SRT строка>"}

    srt — готовый SRT-контент для передачи в luxury_engine (subtitle_srt_path).
    """
    key = (api_key or os.environ.get("GROQ_API_KEY") or "").strip()
    niche_clean = (niche or "general").strip() or "general"
    dur = max(5.0, float(duration_sec))
    examples = competitor_examples or []

    # Fallback caption sequence
    def _fallback() -> dict[str, Any]:
        template = random.choice(_FALLBACK_CAPTIONS)
        captions = []
        for c in template:
            t = float(c["time"])
            actual_time = dur + t if t < 0 else t  # отрицательное = от конца
            captions.append({"time": round(actual_time, 1), "text": c["text"]})
        return _ok({"captions": captions, "srt": _captions_to_srt(captions, dur), "used_fallback": True})

    if not key:
        return _fallback()

    prompt = _build_caption_sequence_prompt(niche_clean, dur, examples)
    content = await _groq_chat(key, prompt, max_tokens=300, temperature=0.75)

    if content is None:
        return _fallback()

    parsed = _parse_caption_json(content, dur)
    if not parsed:
        logger.warning("generate_caption_sequence: parse fail: %s", content[:300])
        return _fallback()

    return _ok({"captions": parsed, "srt": _captions_to_srt(parsed, dur), "used_fallback": False})


def _captions_to_srt(captions: list[dict[str, Any]], duration_sec: float) -> str:
    """Конвертирует список {time, text} в SRT строку."""
    lines: list[str] = []
    for i, cap in enumerate(captions, 1):
        start = float(cap["time"])
        # Конец = начало следующего caption или +3 сек, не позже длительности
        if i < len(captions):
            end = float(captions[i]["time"]) - 0.1
        else:
            end = min(start + 3.5, duration_sec - 0.1)
        end = max(start + 0.5, end)
        lines.append(str(i))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(str(cap["text"]))
        lines.append("")
    return "\n".join(lines)


def _srt_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
