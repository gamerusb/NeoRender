"""
AI Генератор субтитров.

Пайплайн:
  1. ffmpeg — извлечь аудио из видео/файла
  2. Groq Whisper API — транскрибация с тайм-кодами (whisper-large-v3)
  3. Groq LLaMA — перевод каждого сегмента на целевой язык (опционально)
  4. Генерация .srt файла
  5. ffmpeg — вжечь субтитры в копию видео (опционально)

Использует тот же GROQ_API_KEY что и ai_copywriter.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

import aiohttp
from core import ffmpeg_runner

logger = logging.getLogger(__name__)

GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_CHAT_URL    = "https://api.groq.com/openai/v1/chat/completions"
_WHISPER_MODEL   = "whisper-large-v3"
_TRANSLATE_MODEL = "llama-3.1-8b-instant"
_TIMEOUT         = aiohttp.ClientTimeout(total=300, connect=20)

SUPPORTED_LANGS = {
    "ko": "Korean",
    "en": "English",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "th": "Thai",
    "ar": "Arabic",
}


# ── SRT / ASS helpers ────────────────────────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    """Convert float seconds → SRT timestamp HH:MM:SS,mmm."""
    ms  = int(round(seconds * 1000))
    h   = ms // 3_600_000;  ms -= h * 3_600_000
    m   = ms //    60_000;  ms -= m *    60_000
    s   = ms //     1_000;  ms -= s *     1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_ass_ts(seconds: float) -> str:
    """Convert float seconds → ASS timestamp H:MM:SS.cc (centiseconds)."""
    cs  = int(round(seconds * 100))
    h   = cs // 360_000;  cs -= h * 360_000
    m   = cs //   6_000;  cs -= m *   6_000
    s   = cs //     100;  cs -= s *     100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_srt(segments: list[dict[str, Any]]) -> str:
    """Build SRT string from list of {start, end, text} dicts."""
    lines: list[str] = []
    idx = 1
    for seg in segments:
        start = float(seg.get("start") or 0)
        end   = float(seg.get("end")   or start + 2)
        text  = str(seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{idx}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{text}\n")
        idx += 1
    return "\n".join(lines)


def _ass_encode_font(font_path: Path) -> list[str]:
    """
    Encode a font file for embedding in ASS [Fonts] section using the
    encoding format that Aegisub and libass expect.

    libass uses a custom 6-bit encoding where each byte group of 3 is packed
    into 4 characters from the range 33-96 ('!' to '`').
    The algorithm is Aegisub-compatible and tested against libass 0.17.x.
    """
    data = font_path.read_bytes()
    encoded_lines: list[str] = []
    i = 0
    line_chars: list[str] = []

    while i < len(data):
        # Take up to 3 bytes
        b0 = data[i];     i += 1
        b1 = data[i] if i < len(data) else 0;  i += 1
        b2 = data[i] if i < len(data) else 0;  i += 1

        # Pack 3 bytes into 4 6-bit groups
        c0 = (b0 >> 2) & 0x3F
        c1 = ((b0 & 0x03) << 4) | ((b1 >> 4) & 0x0F)
        c2 = ((b1 & 0x0F) << 2) | ((b2 >> 6) & 0x03)
        c3 = b2 & 0x3F

        # Map 0-63 to chars 33-96 ('!' to '`') — same as Aegisub
        for c in (c0, c1, c2, c3):
            line_chars.append(chr(c + 33))

        # Aegisub uses 80-char lines (20 groups of 3 bytes = 60 bytes → 80 chars)
        if len(line_chars) >= 80:
            encoded_lines.append("".join(line_chars[:80]))
            line_chars = line_chars[80:]

    if line_chars:
        encoded_lines.append("".join(line_chars))

    return encoded_lines


def build_ass(
    segments: list[dict[str, Any]],
    *,
    font_name: str = "Gmarket Sans Bold",
    font_size: int = 14,
    fade_in_ms: int = 0,
    fade_out_ms: int = 0,
    margin_v: int = 40,
    bold: bool = False,
    uppercase: bool = False,
    letter_spacing: int = 1,
    embed_font_path: Path | None = None,
) -> str:
    """
    Build ASS subtitle file with smooth fade-in/out animation.

    Key features:
    - Optional \\fad(); default off (fade lowers perceived brightness)
    - Caption: белый текст, чёрная обводка ~2.5px (читаемость на любом фоне)
    - Optional font embedding via [Fonts] section (uuencoded) —
      libass uses the embedded font directly, bypassing DirectWrite/system cache.
      This is the most reliable way to use custom fonts on Windows.
    """
    bold_flag = "1" if bold else "0"
    # Белый текст, чёрная обводка (ASS: &HAABBGGRR)
    primary   = "&H00FFFFFF"
    secondary = "&H00FFFFFF"
    outline_c = "&H00000000"
    back_c    = "&H00000000"
    outline_w = 2.5  # ~2–3 px визуально в зависимости от разрешения

    style_line = (
        f"Style: Default,{font_name},{font_size},"
        f"{primary},{secondary},{outline_c},{back_c},"
        f"{bold_flag},0,0,0,"
        f"100,100,{letter_spacing},0,"
        "1,"        # BorderStyle=1
        f"{outline_w},0,"  # Outline, Shadow
        "2,"        # bottom-center
        f"18,18,{margin_v},1"
    )

    lines: list[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line,
        "",
    ]

    # ── Embed font (bypasses DirectWrite/system font cache entirely) ──────
    if embed_font_path and embed_font_path.exists():
        lines += [
            "[Fonts]",
            f"fontname: {embed_font_path.name}",
        ]
        lines += _ass_encode_font(embed_font_path)
        lines += [""]

    lines += [
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for seg in segments:
        start = float(seg.get("start") or 0)
        end   = float(seg.get("end")   or start + 2)
        text  = str(seg.get("text") or "").strip()
        if not text:
            continue
        if uppercase:
            text = text.upper()
        # Пер-строка: белый текст, чёрная обводка (дублируем стиль на случай кэша libass)
        prefix = "{\\1c&HFFFFFF&\\3c&H000000&\\bord2.5\\shad0"
        if fade_in_ms > 0 or fade_out_ms > 0:
            prefix += "\\fad(" + str(fade_in_ms) + "," + str(fade_out_ms) + ")"
        prefix += "}"
        lines.append(
            f"Dialogue: 0,{_fmt_ass_ts(start)},{_fmt_ass_ts(end)},"
            f"Default,,0,0,0,,{prefix}{text}"
        )

    return "\n".join(lines) + "\n"


def _split_text_chunks(text: str, max_words: int = 4, max_chars: int = 28) -> list[str]:
    """
    Split long subtitle text into short readable chunks.
    First split by punctuation, then by word count/char length.
    """
    raw_parts = [p.strip() for p in re.split(r"(?<=[\.\!\?\;\,\:\u3002\uFF01\uFF1F])\s+", text.strip()) if p.strip()]
    if not raw_parts:
        return []
    out: list[str] = []
    for part in raw_parts:
        words = part.split()
        if not words:
            continue
        cur: list[str] = []
        for w in words:
            cand = " ".join([*cur, w]).strip()
            if cur and (len(cur) >= max_words or len(cand) > max_chars):
                out.append(" ".join(cur).strip())
                cur = [w]
            else:
                cur.append(w)
        if cur:
            out.append(" ".join(cur).strip())
    return [x for x in out if x]


def rebalance_segments(
    segments: list[dict[str, Any]],
    *,
    max_words: int = 4,
    max_chars: int = 28,
    min_duration: float = 0.5,
) -> list[dict[str, Any]]:
    """
    Improve subtitle timing granularity:
    - split long lines into smaller chunks,
    - distribute original segment time proportionally by text length.
    """
    out: list[dict[str, Any]] = []
    for seg in segments:
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start + 1.0)
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        if end <= start:
            end = start + 1.0
        duration = max(min_duration, end - start)
        chunks = _split_text_chunks(text, max_words=max_words, max_chars=max_chars)
        if len(chunks) <= 1:
            out.append({"start": start, "end": end, "text": text})
            continue
        weights = [max(1, len(c.replace(" ", ""))) for c in chunks]
        total_w = sum(weights) or 1
        cur = start
        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1:
                nxt = end
            else:
                piece = duration * (weights[i] / total_w)
                nxt = min(end, cur + max(min_duration, piece))
            out.append({"start": cur, "end": nxt, "text": chunk})
            cur = nxt
    return out


# ── ffmpeg helpers ────────────────────────────────────────────────────────────

def _ffmpeg() -> str:
    return ffmpeg_runner.ffmpeg_bin()


def extract_audio(video_path: str | Path, out_wav: str | Path) -> bool:
    """Extract mono 16kHz WAV (Whisper-optimal) from video."""
    cmd = [
        _ffmpeg(), "-y", "-i", str(video_path),
        "-ac", "1", "-ar", "16000", "-vn",
        str(out_wav),
    ]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0


async def extract_audio_async(video_path: str | Path, out_wav: str | Path) -> bool:
    """Executor-wrapper: не блокирует event loop API-сервера."""
    return await asyncio.to_thread(extract_audio, video_path, out_wav)


def _fonts_dirs() -> list[str]:
    """Return candidate font directories (user + system)."""
    dirs = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    dirs.append(r"C:\Windows\Fonts")
    # also look next to the subtitle_generator module itself
    dirs.append(str(Path(__file__).parent / "fonts"))
    return [d for d in dirs if os.path.isdir(d)]


def _write_fontconfig(fonts_dirs: list[str], conf_path: Path) -> None:
    """Write a minimal fontconfig fonts.conf pointing to custom font dirs."""
    dir_lines = "\n".join(f'  <dir>{d.replace(chr(92), "/")}</dir>' for d in fonts_dirs)
    conf_path.write_text(
        f'<?xml version="1.0"?>\n'
        f'<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        f'<fontconfig>\n'
        f'{dir_lines}\n'
        f'  <cachedir>~/.cache/fontconfig</cachedir>\n'
        f'</fontconfig>\n',
        encoding="utf-8",
    )


_FONT_PREFER = "GmarketSansBold.otf"  # bold face for strong on-screen text
_FONT_FALLBACKS = ["GmarketSansMedium.otf", "GmarketSansLight.otf"]


def _resolve_font_file() -> Path | None:
    """Find the GmarketSans font file in any known fonts directory."""
    for d in _fonts_dirs():
        for name in [_FONT_PREFER] + _FONT_FALLBACKS:
            p = Path(d) / name
            if p.exists():
                return p
    return None


def burn_subtitles(
    video_path: str | Path,
    srt_path: str | Path,
    out_path: str | Path,
    *,
    ass_path: str | Path | None = None,
) -> bool:
    """
    Burn subtitles into a copy of the video using ASS (with fade) when available.

    Font resolution strategy:
      1. Copy GmarketSans font file next to the ASS file so libass finds it
         without needing fontconfig or system installation.
      2. Pass fontsdir= pointing to that local dir (simple relative-friendly path).
      3. Also set FONTCONFIG_FILE env var as a belt-and-suspenders approach.
      4. Fall back gracefully to SRT+force_style if ASS is missing.
    """
    import shutil

    out_dir = Path(out_path).parent
    env = os.environ.copy()

    # ── set up fontconfig pointing to known font dirs ──────────────────────
    conf_path = out_dir / "_fonts.conf"
    font_dirs = _fonts_dirs()
    _write_fontconfig(font_dirs, conf_path)
    env["FONTCONFIG_FILE"] = str(conf_path)

    # ── copy font file to output dir so libass can find it by filename ─────
    font_src = _resolve_font_file()
    local_font_dir = out_dir / "_fonts"
    local_font_dir.mkdir(exist_ok=True)
    if font_src:
        shutil.copy2(font_src, local_font_dir / font_src.name)
        logger.info("burn_subtitles: copied font %s → %s", font_src.name, local_font_dir)
    else:
        logger.warning("burn_subtitles: GmarketSans not found in any font dir")

    def _ffmpeg_esc(p: str) -> str:
        """Escape path for ffmpeg -vf filter string (Windows-safe)."""
        s = str(p).replace("\\", "/")
        # UNC путь //server/share не содержит drive-letter, двоеточие экранировать не нужно.
        if re.match(r"^[a-zA-Z]:/", s):
            s = s[0] + "\\:" + s[2:]
        return s

    local_fonts_esc = _ffmpeg_esc(str(local_font_dir))

    if ass_path and Path(ass_path).exists():
        ass_esc = _ffmpeg_esc(str(ass_path))
        vf = f"ass='{ass_esc}':fontsdir='{local_fonts_esc}'"
    else:
        style = (
            "FontName=Gmarket Sans Bold,"
            "FontSize=16,"
            "PrimaryColour=&H00FFFFFF,"
            "SecondaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BackColour=&H00000000,"
            "Outline=2.5,"
            "Shadow=0,"
            "BorderStyle=1,"
            "MarginV=48,"
            "Alignment=2"
        )
        srt_esc = _ffmpeg_esc(str(srt_path))
        vf = (
            f"subtitles='{srt_esc}':"
            f"fontsdir='{local_fonts_esc}':"
            f"force_style='{style}'"
        )

    cmd = [
        _ffmpeg(), "-y", "-i", str(video_path),
        "-vf", vf,
        "-c:a", "copy",
        str(out_path),
    ]
    logger.info("burn_subtitles cmd: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, env=env)
    stderr_txt = r.stderr.decode(errors="replace")
    if r.returncode != 0:
        logger.warning("burn_subtitles FAILED:\n%s", stderr_txt[:1000])
    else:
        # log any font-related warnings from libass even on success
        for line in stderr_txt.splitlines():
            if "font" in line.lower() or "ass" in line.lower():
                logger.debug("ffmpeg: %s", line)
        logger.info("burn_subtitles OK → %s", out_path)
    return r.returncode == 0


async def burn_subtitles_async(
    video_path: str | Path,
    srt_path: str | Path,
    out_path: str | Path,
    *,
    ass_path: str | Path | None = None,
) -> bool:
    """Executor-wrapper: безопасный запуск burn без блокировки loop."""
    return await asyncio.to_thread(
        burn_subtitles,
        video_path,
        srt_path,
        out_path,
        ass_path=ass_path,
    )


# ── Groq Whisper transcription ────────────────────────────────────────────────

async def transcribe(audio_path: str | Path, api_key: str, language: str | None = None) -> list[dict[str, Any]]:
    """
    Transcribe audio via Groq Whisper. Returns list of segments:
    [{start, end, text}, …]
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio not found: {path}")

    data = aiohttp.FormData()
    data.add_field("model", _WHISPER_MODEL)
    data.add_field("response_format", "verbose_json")
    data.add_field("timestamp_granularities[]", "segment")
    if language:
        data.add_field("language", language[:2])
    with open(path, "rb") as f:
        data.add_field("file", f, filename=path.name, content_type="audio/wav")
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(
                GROQ_WHISPER_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    hint = ""
                    if resp.status == 401:
                        hint = (
                            " Нужен действующий ключ Groq (https://console.groq.com, "
                            "префикс gsk_). Ключ OpenAI (sk-…) сюда не подходит; "
                            "обновите ключ в «Настройки» или в .env как GROQ_API_KEY."
                        )
                    raise RuntimeError(f"Whisper error {resp.status}: {body[:300]}{hint}")
                result = json.loads(body)

    segments = result.get("segments") or []
    return [
        {
            "start": float(s.get("start") or 0),
            "end":   float(s.get("end")   or 0),
            "text":  str(s.get("text") or "").strip(),
        }
        for s in segments
        if str(s.get("text") or "").strip()
    ]


# ── Groq LLaMA translation ────────────────────────────────────────────────────

async def translate_segments(
    segments: list[dict[str, Any]],
    target_lang: str,
    api_key: str,
    batch_size: int = 30,
) -> list[dict[str, Any]]:
    """
    Translate segment texts to target_lang (ISO-639-1 code).
    Batches requests to stay within token limits.
    """
    lang_name = SUPPORTED_LANGS.get(target_lang, target_lang)
    translated: list[dict[str, Any]] = []

    for i in range(0, len(segments), batch_size):
        batch = segments[i : i + batch_size]
        texts = [s["text"] for s in batch]
        numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(texts))

        prompt = (
            f"Translate each numbered subtitle line to {lang_name}.\n"
            "Rules:\n"
            "- Keep the same line numbers.\n"
            "- Do NOT add explanations, only the translated text.\n"
            "- Keep the same emotional tone.\n"
            "- One line per translation.\n\n"
            f"{numbered}\n\n"
            "Output format (one line each):\n1. <translation>\n2. <translation>…"
        )

        payload = {
            "model": _TRANSLATE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 2048,
        }

        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                async with session.post(
                    GROQ_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as resp:
                    body = await resp.text()
                    if resp.status != 200:
                        logger.warning("translate batch error %s: %s", resp.status, body[:200])
                        translated.extend(batch)
                        continue
                    data = json.loads(body)
                    content = data["choices"][0]["message"]["content"].strip()

            # parse "1. text\n2. text" format
            trans_map: dict[int, str] = {}
            for line in content.splitlines():
                m = re.match(r"^(\d+)\.\s*(.*)", line.strip())
                if m:
                    trans_map[int(m.group(1))] = m.group(2).strip()

            for j, seg in enumerate(batch):
                t = trans_map.get(j + 1, seg["text"])
                translated.append({**seg, "text": t or seg["text"]})
        except Exception as exc:
            logger.warning("translate_segments batch %d error: %s", i, exc)
            translated.extend(batch)

    return translated


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_subtitles(
    video_path: str | Path,
    output_dir: str | Path,
    api_key: str,
    source_lang: str | None = None,
    target_lang: str | None = None,
    burn: bool = False,
    on_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Full pipeline: video → .srt (+ optional burned video).

    Returns:
    {
        "status": "ok",
        "srt_path": "...",
        "burned_path": "..." | None,
        "segments": [...],
        "segment_count": N,
        "source_lang": "...",
        "target_lang": "...",
    }
    """
    vp = Path(video_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not vp.exists():
        return {"status": "error", "message": f"Файл не найден: {vp}"}
    if not api_key:
        return {"status": "error", "message": "GROQ_API_KEY не задан"}

    stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", vp.stem)[:40]

    # ── Step 1: extract audio ──
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_path = Path(tf.name)

    try:
        logger.info("subtitle: extracting audio from %s", vp.name)
        if not await extract_audio_async(vp, wav_path):
            return {"status": "error", "message": "ffmpeg не смог извлечь аудио"}

        # ── Step 2: transcribe ──
        logger.info("subtitle: transcribing via Groq Whisper")
        segments = await transcribe(wav_path, api_key, language=source_lang)
        if not segments:
            return {"status": "error", "message": "Whisper не вернул сегменты — возможно видео без речи"}

        detected_lang = source_lang or "auto"

        # ── Step 3: translate (optional) ──
        if target_lang and target_lang != source_lang:
            if on_step:
                on_step("Перевод (LLaMA)")
            logger.info("subtitle: translating %d segments → %s", len(segments), target_lang)
            segments = await translate_segments(segments, target_lang, api_key)

        # ── Step 3.5: timing-friendly short chunks ──
        segments = rebalance_segments(segments, max_words=4, max_chars=28)

        # ── Step 4: build SRT + ASS ──
        if on_step:
            on_step("Генерация .srt")
        lang_suffix = f"_{target_lang}" if target_lang else ""
        srt_content = build_srt(segments)
        srt_path = out / f"{stem}{lang_suffix}.srt"
        srt_path.write_text(srt_content, encoding="utf-8")

        # ASS with fade animation — used for burning.
        # "Gmarket Sans Bold" is the exact GDI face name for the bold master.
        ass_content = build_ass(
            segments,
            font_name="Gmarket Sans Bold",
            font_size=16,
            fade_in_ms=0,
            fade_out_ms=0,
            margin_v=48,
            bold=False,
            letter_spacing=0,
            embed_font_path=_resolve_font_file(),
        )
        ass_path = out / f"{stem}{lang_suffix}.ass"
        # newline='\n' prevents Windows text-mode from inserting \r\n (breaks libass)
        ass_path.write_text(ass_content, encoding="utf-8", newline="\n")
        logger.info("subtitle: SRT+ASS written to %s (%d segments)", out, len(segments))

        # ── Step 5: burn (optional) ──
        burned_path: Path | None = None
        if burn:
            if on_step:
                on_step("Вжигание субтитров")
            burned_path = out / f"{stem}{lang_suffix}_subtitled.mp4"
            logger.info("subtitle: burning ASS subtitles into video")
            if not await burn_subtitles_async(vp, srt_path, burned_path, ass_path=ass_path):
                burned_path = None
                logger.warning("subtitle: burn failed, returning SRT only")

        return {
            "status": "ok",
            "srt_path": str(srt_path),
            "srt_filename": srt_path.name,
            "ass_path": str(ass_path),
            "ass_filename": ass_path.name,
            "burned_path": str(burned_path) if burned_path else None,
            "burned_filename": burned_path.name if burned_path else None,
            "segments": segments,
            "segment_count": len(segments),
            "source_lang": detected_lang,
            "target_lang": target_lang or detected_lang,
        }
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass
