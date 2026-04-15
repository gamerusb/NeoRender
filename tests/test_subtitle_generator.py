"""Тесты для модуля AI субтитров."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import subtitle_generator as sg


def test_fmt_ts_basic():
    assert sg._fmt_ts(0.0) == "00:00:00,000"
    assert sg._fmt_ts(1.234) == "00:00:01,234"
    assert sg._fmt_ts(61.009) == "00:01:01,009"


def test_build_ass_white_fill_black_outline():
    ass = sg.build_ass([{"start": 0.0, "end": 1.0, "text": "Hi"}])
    assert "&H00FFFFFF" in ass
    assert "2.5,0," in ass  # Outline=2.5, Shadow=0 в строке Style
    assert "\\1c&HFFFFFF&" in ass
    assert "\\3c&H000000&" in ass
    assert "\\bord2.5" in ass


def test_build_srt_skips_empty_lines():
    segments = [
        {"start": 0.0, "end": 1.2, "text": "Hello"},
        {"start": 1.2, "end": 2.0, "text": "   "},  # should be skipped
        {"start": 2.0, "end": 4.0, "text": "World"},
    ]
    srt = sg.build_srt(segments)
    assert "1\n00:00:00,000 --> 00:00:01,200\nHello" in srt
    assert "2\n00:00:02,000 --> 00:00:04,000\nWorld" in srt
    assert "   " not in srt


@pytest.mark.asyncio
async def test_generate_subtitles_requires_api_key(tiny_mp4: Path, tmp_path: Path):
    result = await sg.generate_subtitles(
        video_path=tiny_mp4,
        output_dir=tmp_path,
        api_key="",
    )
    assert result["status"] == "error"
    assert "GROQ_API_KEY" in result["message"]


@pytest.mark.asyncio
async def test_generate_subtitles_success_with_mocks(monkeypatch, tiny_mp4: Path, tmp_path: Path):
    """Проверка полного пайплайна без реальных ffmpeg/Groq."""

    async def fake_transcribe(audio_path, api_key, language=None):
        return [
            {"start": 0.0, "end": 1.0, "text": "Привет"},
            {"start": 1.1, "end": 2.6, "text": "Как дела?"},
        ]

    async def fake_translate_segments(segments, target_lang, api_key, batch_size=30):
        return [{**s, "text": f"[{target_lang}] {s['text']}"} for s in segments]

    def fake_extract_audio(video_path, out_wav):
        Path(out_wav).write_bytes(b"wav")
        return True

    def fake_burn_subtitles(video_path, srt_path, out_path, **kwargs):
        Path(out_path).write_bytes(b"mp4-subtitled")
        return True

    monkeypatch.setattr(sg, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(sg, "transcribe", fake_transcribe)
    monkeypatch.setattr(sg, "translate_segments", fake_translate_segments)
    monkeypatch.setattr(sg, "burn_subtitles", fake_burn_subtitles)

    result = await sg.generate_subtitles(
        video_path=tiny_mp4,
        output_dir=tmp_path,
        api_key="test-key",
        source_lang="ru",
        target_lang="ko",
        burn=True,
    )

    assert result["status"] == "ok"
    assert result["segment_count"] == 2
    assert result["target_lang"] == "ko"
    assert result["burned_path"] is not None

    srt_path = Path(result["srt_path"])
    burned_path = Path(result["burned_path"])
    assert srt_path.exists()
    assert burned_path.exists()
    srt_text = srt_path.read_text(encoding="utf-8")
    assert "[ko] Привет" in srt_text
    assert "[ko] Как дела?" in srt_text

