"""
Модуль для генерации авто-субтитров и AI дубляжа.
Использует faster-whisper для STT, Groq API (опционально) для перевода, и edge-tts для озвучки.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import random
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def format_timestamp(seconds: float) -> str:
    """Конвертирует секунды в формат SRT (00:00:00,000)."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msec = int(round((seconds - int(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{msec:03d}"

def _is_cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except (ImportError, Exception):
        return False

async def transcribe_and_process(
    original_video: str | Path,
    target_lang: str | None = None,
    groq_key: str | None = None,
    generate_dub: bool = False,
    output_dir: Path | None = None
) -> dict[str, Any]:
    """
    Основная точка входа для генерации авто-сабов и дубляжа.
    1. Транскрибация видео.
    2. Если задан target_lang, перевод через Groq API.
    3. Создание .srt файла.
    4. Если generate_dub, создание dub_audio.mp3.
    """
    video_path = Path(original_video)
    base_dir = output_dir or video_path.parent
    safe_name = video_path.stem
    uid = random.randint(1000, 9999)
    out_srt = base_dir / f"{safe_name}_subs_{uid}.srt"
    out_audio = base_dir / f"{safe_name}_dub_{uid}.mp3"
    
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster-whisper не установлен. Выполните pip install faster-whisper")
        return {"status": "error", "message": "Модуль faster-whisper не установлен."}

    device = "cuda" if _is_cuda_available() else "cpu"
    
    # Блокируем event loop на время загрузки модели и инференса, 
    # так как faster-whisper синхронный. В идеале вынести в run_in_executor.
    loop = asyncio.get_running_loop()
    
    def _run_whisper():
        model = None
        try:
            logger.info("Загрузка модели whisper (device=%s)...", device)
            model = WhisperModel("base", device=device, compute_type="default")
            segments, _info = model.transcribe(str(video_path), beam_size=5)
            parsed = []
            for i, segment in enumerate(segments):
                parsed.append({
                    "idx": i + 1,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                })
            return parsed
        finally:
            # Убираем long-lived ссылки, чтобы процесс не копил RAM между задачами.
            model = None
            gc.collect()

    try:
        parsed_segments = await loop.run_in_executor(None, _run_whisper)
            
        if not parsed_segments:
            return {"status": "ok", "message": "В видео не найдено речи", "srt_path": None, "dub_path": None}

        # Если запрошен перевод
        if target_lang and groq_key:
            parsed_segments = await _translate_segments(parsed_segments, target_lang, groq_key)
            
        # Генерация SRT файла
        with open(out_srt, "w", encoding="utf-8") as f:
            for s in parsed_segments:
                f.write(f"{s['idx']}\n")
                f.write(f"{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}\n")
                f.write(f"{s['text']}\n\n")

        dub_path = None
        if generate_dub:
            dub_path = await _generate_edge_tts(parsed_segments, target_lang, str(out_audio))

        return {
            "status": "ok", 
            "srt_path": str(out_srt), 
            "dub_path": dub_path
        }
    except Exception as exc:
        logger.exception("Ошибка генерации авто-сабов: %s", exc)
        try:
            out_srt.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            out_audio.unlink(missing_ok=True)
        except OSError:
            pass
        return {"status": "error", "message": str(exc)}

async def _translate_segments(segments: list[dict], target_lang: str, groq_key: str) -> list[dict]:
    """Перевод массива сегментов с помощью Groq API (одним промптом, чтобы сохранить тайминги)."""
    if not segments: return segments
    import aiohttp
    import json
    
    combined_text = "\n".join([f"[{s['idx']}]: {s['text']}" for s in segments])
    
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json",
    }
    prompt = (
        f"Translate the following subtitles sequentially to {target_lang}. "
        f"You must keep the exact same sequence format '[ID]: translated text'.\n\n{combined_text}"
    )
    body = {
         "model": os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
         "messages": [{"role": "user", "content": prompt}],
         "temperature": 0.3
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            async with session.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body) as resp:
                 if resp.status == 200:
                     payload = await resp.json()
                     content = payload["choices"][0]["message"]["content"]
                     
                     # Парсер ответов вида [1]: 연설
                     translated_map = {}
                     for line in content.split("\n"):
                         m = re.match(r"\[(\d+)\]:\s*(.*)", line.strip())
                         if m:
                             translated_map[int(m.group(1))] = m.group(2).strip()
                             
                     for s in segments:
                         idx = s["idx"]
                         if idx in translated_map:
                             # Очищаем лишние кавычки, если модель их добавила
                             clean_text = translated_map[idx].strip('"').strip()
                             s["text"] = clean_text
    except Exception as exc:
        logger.error("Ошибка перевода субтитров: %s", exc)
        
    return segments

async def _generate_edge_tts(segments: list[dict], target_lang: str | None, out_path: str) -> str | None:
    """Генерирует единый аудиофайл дубляжа."""
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts не установлен. Пропускаем дубляж.")
        return None
        
    # Подбор голоса. В боевом режиме это можно вынести в настройки
    voice = "ko-KR-SunHiNeural" if target_lang == "ko" else "en-US-JennyNeural"
    
    # Собираем весь текст. Edge-TTS автоматически расставит паузы на знаках препинания.
    all_text = " ".join([s["text"] for s in segments])
    if not all_text.strip(): return None
    
    try:
        communicate = edge_tts.Communicate(all_text, voice)
        await communicate.save(out_path)
        return out_path
    except Exception as exc:
        logger.error("Ошибка генерации TTS: %s", exc)
        return None
