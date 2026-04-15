"""Luxury engine tests: mock FFmpeg/ffprobe, validate inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import ffmpeg_runner
from core import luxury_engine as le


@pytest.fixture(autouse=True)
def _luxury_tests_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без реального blackdetect-проба, без MP3-roundtrip и без pHash после мок-рендера."""
    monkeypatch.setenv("NEORENDER_AUDIO_LAME_ROUNDTRIP_P", "0")

    async def _no_trim(*_a, **_k):
        return 0.0, 0.0

    monkeypatch.setattr(ffmpeg_runner, "probe_lead_tail_black_silence", _no_trim)

    # probe_video_dimensions на тестовом 1×1 PNG возвращает None (w<2), что ломает overlay-проверку.
    # В юнит-тестах эта проверка не нужна — подставляем заглушку.
    async def _fake_dims(path, **_k):
        return (200, 200)

    monkeypatch.setattr(ffmpeg_runner, "probe_video_dimensions", _fake_dims)

    async def _no_phash(*_a, **_k):
        return {
            "perceptual_diff_pct": None,
            "perceptual_too_similar": False,
            "perceptual_warning": None,
            "perceptual_skipped": True,
        }

    monkeypatch.setattr("core.perceptual_video_hash.compare_videos_phash", _no_phash)


def test_resolve_device_fingerprint_presets_and_fallback():
    m, a, q = le.resolve_device_fingerprint("Google Pixel 8")
    assert m == "Google Pixel 8" and a == "Google" and q == "Google"
    m2, a2, q2 = le.resolve_device_fingerprint("iPhone 15 Pro")
    assert m2 == "iPhone 15 Pro" and a2 == "Apple" and q2 == "Apple"
    m3, a3, q3 = le.resolve_device_fingerprint("Totally unknown model X")
    assert m3 == "Totally unknown model X" and a3 == "Samsung" and q3 == "Samsung"


async def _fake_duration(_path):
    return 10.0


def _patch_ffmpeg_runner(monkeypatch, fake_run):
    """Подмена run_ffmpeg_with_progress (вызывается из luxury_engine)."""

    async def fake_wp(args, *, duration_sec=None, progress_cb=None, encode_label="", cancel_event=None):
        return await fake_run(args)

    monkeypatch.setattr(ffmpeg_runner, "run_ffmpeg_with_progress", fake_wp)
    monkeypatch.setattr(ffmpeg_runner, "probe_video_duration_seconds", _fake_duration)


def test_default_cta_subtitles_after_overlay(tmp_path: Path):
    """CTA через ASS/subtitles поверх PNG — иначе полноэкранный оверлей скрывает текст."""
    ass = tmp_path / "cta.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,"
        "100,100,0,0,1,2,0,8,10,10,18,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,9:59:59.99,Default,,0,0,0,,Hello\n",
        encoding="utf-8-sig",
    )
    tf_fwd = str(ass.resolve()).replace("\\", "/")
    fc, _ = le.build_filter_complex(
        "deep",
        "default",
        False,
        tf_fwd,
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
    )
    assert "subtitles=" in fc
    assert fc.find("overlay=") < fc.find("subtitles=")


def test_soft_preset_registered():
    assert "soft" in le.RENDER_PRESETS


def test_build_filter_under_video_uses_scale2ref():
    fc, vmap = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        "",
        overlay_mode="under_video",
        overlay_position="center",
        subtitle_style="default",
    )
    assert "scale2ref" in fc
    assert vmap == "[vout]"
    assert "overlay=0:0" in fc


def test_build_filter_screen_blend_uses_blend_filter():
    fc, _ = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
        overlay_blend_mode="screen",
        overlay_opacity=0.55,
    )
    assert "blend=all_mode=screen" in fc
    assert "all_opacity=0.5500" in fc
    assert "shortest=1" in fc


def test_build_filter_linekey_removes_black_background():
    fc, _ = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
        overlay_blend_mode="linekey",
        overlay_opacity=0.7,
    )
    assert "colorkey=0x000000" in fc
    assert "colorchannelmixer=aa=0.7000" in fc
    assert "overlay=0:0" in fc


def test_build_filter_prefers_ass_over_srt(tmp_path: Path):
    ass = tmp_path / "timed.ass"
    srt = tmp_path / "timed.srt"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,"
        "100,100,0,0,1,2,0,2,10,10,24,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,hello\n",
        encoding="utf-8-sig",
    )
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nfallback\n", encoding="utf-8")
    fc, vmap = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        str(srt),
        ass_path=str(ass),
    )
    assert "ass='" in fc
    assert "subtitles='" not in fc
    assert vmap == "[vfinal]"


def test_render_signature_accepts_tandem_params():
    import inspect

    sig = inspect.signature(le.render_unique_video)
    assert "ass_path" in sig.parameters
    assert "dub_audio_path" in sig.parameters


def test_build_filter_extra_effects_are_in_chain():
    fc, _ = le.build_filter_complex(
        "deep",
        "default",
        True,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
        effects={"crop_reframe": True, "gamma_jitter": True, "audio_tone": True},
    )
    assert "eq=gamma=" in fc
    assert "scale=iw*" in fc and "crop=iw/" in fc
    assert "highpass=f=80" in fc
    assert "acompressor=" in fc


def test_build_filter_extra_effects_respect_high_levels():
    fc, _ = le.build_filter_complex(
        "deep",
        "default",
        True,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
        effects={"crop_reframe": True, "gamma_jitter": True, "audio_tone": True},
        effect_levels={"crop_reframe": "high", "gamma_jitter": "high", "audio_tone": "high"},
    )
    assert "eq=gamma=" in fc
    assert "scale=iw*" in fc and "crop=iw/" in fc
    assert "highpass=f=100" in fc
    assert "lowpass=f=10000" in fc


def test_overlay_blend_capcut_aliases_and_labels():
    assert le._normalize_overlay_blend("Затемнение") == "darken"
    assert le._normalize_overlay_blend("Линейное затемнение") == "darken"
    assert le._normalize_overlay_blend("Белые линии") == "linekey"
    assert le._normalize_overlay_blend("Убрать черный фон") == "linekey"
    # colorburn/colorburn теперь правильно маппятся в multiply/screen (не darken/screen)
    assert le._normalize_overlay_blend("colorburn") == "multiply"
    assert le._normalize_overlay_blend("colordodge") == "screen"
    assert le._normalize_overlay_blend("burn") == "multiply"
    assert le._normalize_overlay_blend("dodge") == "screen"
    labels = le.get_overlay_blend_modes()
    assert labels["normal"] == "По умолчанию"
    assert labels["linekey"] == "Белые линии (убрать черный фон)"
    assert labels["screen"] == "Экран"
    assert labels["darken"] == "Затемнение"
    assert labels["multiply"] == "Умножение"
    assert labels["overlay"] == "Перекрытие"
    assert labels["hardlight"] == "Жёсткий свет"
    assert labels["softlight"] == "Мягкий свет"
    assert labels["difference"] == "Разница"
    assert labels["exclusion"] == "Исключение"
    assert labels["lighten"] == "Осветление"
    assert labels["addition"] == "Добавление"
    assert len(labels) == 12


def test_build_filter_on_top_corner_position():
    fc, _ = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="bottom_right",
        subtitle_style="default",
    )
    assert "main_w-overlay_w" in fc and "main_h-overlay_h" in fc


def test_build_filter_srt_adds_force_style(tmp_path: Path):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    fc, vmap = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        str(srt),
        subtitle_style="readable",
    )
    assert "force_style=" in fc
    assert "FontSize=22" in fc
    assert vmap == "[vfinal]"


def test_escape_drive_colon_for_drawtext_paths():
    """Windows: ':' после диска ломает парсер опций drawtext без '\\:'."""
    assert le._escape_drive_colon_ffmpeg_path("C:/Windows/Fonts/malgun.ttf") == r"C\:/Windows/Fonts/malgun.ttf"
    assert le._escape_drive_colon_ffmpeg_path("/usr/share/fonts/Noto.ttf") == "/usr/share/fonts/Noto.ttf"
    assert r"\'" in le._escape_drive_colon_ffmpeg_path("C:/tmp/foo'bar.txt")


@pytest.mark.asyncio
async def test_render_missing_input(tmp_path: Path, tiny_png: Path):
    out = tmp_path / "o.mp4"
    r = await le.render_unique_video(tmp_path / "nope.mp4", tiny_png, out)
    assert r["status"] == "error"
    assert "найден" in r["message"]


@pytest.mark.asyncio
async def test_render_missing_overlay(tmp_path: Path, tiny_mp4: Path):
    out = tmp_path / "o.mp4"
    r = await le.render_unique_video(tiny_mp4, tmp_path / "no.png", out)
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_render_unsupported_overlay_format(tmp_path: Path, tiny_mp4: Path):
    bad = tmp_path / "overlay.txt"
    bad.write_text("x", encoding="utf-8")
    out = tmp_path / "o.mp4"
    r = await le.render_unique_video(tiny_mp4, bad, out)
    assert r["status"] == "error"
    assert "Неподдерживаемый формат слоя" in r["message"]


@pytest.mark.asyncio
async def test_render_output_must_not_equal_input(tmp_path: Path, tiny_mp4: Path, tiny_png: Path):
    r = await le.render_unique_video(tiny_mp4, tiny_png, tiny_mp4)
    assert r["status"] == "error"
    assert "совпадает с исходным видео" in r["message"]


@pytest.mark.asyncio
async def test_render_output_must_not_equal_overlay(tmp_path: Path, tiny_mp4: Path, tiny_png: Path):
    r = await le.render_unique_video(tiny_mp4, tiny_png, tiny_png)
    assert r["status"] == "error"
    assert "совпадает с файлом слоя" in r["message"]


@pytest.mark.asyncio
async def test_render_missing_srt_returns_error(tmp_path: Path, tiny_mp4: Path, tiny_png: Path):
    out = tmp_path / "o.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out, srt_path=str(tmp_path / "no.srt"))
    assert r["status"] == "error"
    assert "SRT" in r["message"]


@pytest.mark.asyncio
async def test_render_success_mocked_ffmpeg(
    monkeypatch, tmp_path: Path, tiny_mp4: Path, tiny_png: Path
):
    seen_args: list[str] = []

    async def fake_run(args: list[str]) -> tuple[int, bytes, bytes]:
        seen_args.extend(args)
        outp = Path(args[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"fakevideo")
        return 0, b"", b""

    async def fake_has_audio(path: Path) -> bool:
        return False

    _patch_ffmpeg_runner(monkeypatch, fake_run)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", fake_has_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")

    out = tmp_path / "out.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out)
    assert r["status"] == "ok"
    assert r["output_path"] == str(out.resolve())
    assert r["geo_profile"] == "busan"
    assert out.read_bytes() == b"fakevideo"


@pytest.mark.asyncio
async def test_render_geo_disabled_skips_location_metadata(
    monkeypatch, tmp_path: Path, tiny_mp4: Path, tiny_png: Path
):
    captured: list[str] = []

    async def fake_run(args: list[str]) -> tuple[int, bytes, bytes]:
        captured.extend(args)
        outp = Path(args[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"fakevideo")
        return 0, b"", b""

    async def fake_has_audio(path: Path) -> bool:
        return False

    _patch_ffmpeg_runner(monkeypatch, fake_run)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", fake_has_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")

    out = tmp_path / "out_geo_off.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out, geo_enabled=False, geo_profile="seoul")
    assert r["status"] == "ok"
    assert "location=" not in " ".join(captured)


@pytest.mark.asyncio
async def test_render_nvenc_fail_fallback_x264(
    monkeypatch, tmp_path: Path, tiny_mp4: Path, tiny_png: Path
):
    calls: list[str] = []

    async def fake_run(args: list[str]) -> tuple[int, bytes, bytes]:
        outp = Path(args[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        codec = "h264_nvenc" if "h264_nvenc" in args else "libx264"
        calls.append(codec)
        if codec == "h264_nvenc":
            return 1, b"", b"nvenc failed"
        outp.write_bytes(b"ok")
        return 0, b"", b""

    async def fake_has_audio(path: Path) -> bool:
        return False

    _patch_ffmpeg_runner(monkeypatch, fake_run)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", fake_has_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")

    out = tmp_path / "out2.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out)
    assert r["status"] == "ok"
    assert "h264_nvenc" in calls and "libx264" in calls


@pytest.mark.asyncio
async def test_render_skip_nvenc_via_env(
    monkeypatch, tmp_path: Path, tiny_mp4: Path, tiny_png: Path
):
    monkeypatch.setenv("NEORENDER_DISABLE_NVENC", "1")

    async def fake_run(args: list[str]) -> tuple[int, bytes, bytes]:
        assert "h264_nvenc" not in args
        assert "libx264" in args
        outp = Path(args[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"ok")
        return 0, b"", b""

    async def fake_has_audio(path: Path) -> bool:
        return False

    _patch_ffmpeg_runner(monkeypatch, fake_run)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", fake_has_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")

    out = tmp_path / "out_cpu.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out)
    assert r["status"] == "ok"
    assert r.get("codec") == "libx264"


@pytest.mark.asyncio
async def test_dry_run_no_ffmpeg_execute(monkeypatch, tmp_path, tiny_mp4, tiny_png):
    async def boom(*_a, **_k):
        raise RuntimeError("FFmpeg не должен вызываться при dry_run")

    monkeypatch.setattr(ffmpeg_runner, "run_ffmpeg_with_progress", boom)

    async def no_audio(_p):
        return False

    monkeypatch.setattr(ffmpeg_runner, "probe_video_duration_seconds", _fake_duration)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", no_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")

    out = tmp_path / "dry.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out, dry_run=True)
    assert r["status"] == "ok"
    assert r.get("dry_run") is True
    prim = r.get("ffmpeg_args_primary") or []
    x4 = r.get("ffmpeg_args_x264") or []
    assert "-filter_complex" in prim and "-filter_complex" in x4
    assert prim.count("-i") >= 2
    assert "libx264" in x4


def test_ffmpeg_runner_parse_black_silence_lead_tail():
    from core import ffmpeg_runner as fr

    log = "pre black_start:0 black_end:0.35 black_duration:0.35 post"
    assert fr.parse_black_intervals(log) == [(0.0, 0.35)]
    sil = "[silencedetect] silence_start: 0\n[silencedetect] silence_end: 0.2"
    assert fr.parse_silence_intervals(sil, 5.0) == [(0.0, 0.2)]
    assert fr.lead_tail_trim_from_intervals([(0.0, 0.4)], 10.0) == (0.4, 0.0)
    _a, tail = fr.lead_tail_trim_from_intervals([(9.55, 10.0)], 10.0)
    assert _a == 0.0 and abs(tail - 0.45) < 0.02


def test_micro_resize_in_eq_chain():
    fc, _ = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
        micro_dw=2,
        micro_dh=-2,
    )
    assert "scale=iw+2:ih" in fc and "scale=iw-2:ih" in fc


def test_micro_resize_story_template():
    fc, _ = le.build_filter_complex(
        "deep",
        "story",
        False,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
        micro_dw=4,
        micro_dh=0,
    )
    assert "scale=iw+4:ih+0" in fc or "scale=iw+4:ih" in fc


@pytest.mark.asyncio
async def test_dry_run_includes_ss_and_t_after_trim(monkeypatch, tmp_path, tiny_mp4, tiny_png):
    async def fake_trim(*_a, **_k):
        return 0.4, 0.2

    monkeypatch.setattr(ffmpeg_runner, "probe_lead_tail_black_silence", fake_trim)
    monkeypatch.setattr(ffmpeg_runner, "probe_video_duration_seconds", _fake_duration)
    out = tmp_path / "dry_trim.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out, dry_run=True)
    assert r["status"] == "ok"
    args = r.get("ffmpeg_args_x264") or []
    assert "-ss" in args
    assert "-t" in args
    assert r.get("trim_lead_sec") == 0.4
    assert r.get("trim_tail_sec") == 0.2


def test_build_luxury_encode_argv_two_inputs(tmp_path, tiny_mp4, tiny_png):
    fc, vmap = le.build_filter_complex(
        "deep",
        "default",
        False,
        "",
        "",
        overlay_mode="on_top",
        overlay_position="center",
        subtitle_style="default",
    )
    argv = le.build_luxury_encode_argv(
        ffmpeg_exe="ffmpeg",
        input_video=tiny_mp4,
        overlay_media=tiny_png,
        filter_complex=fc,
        video_map=vmap,
        with_audio=False,
        audio_bitrate="192k",
        common_meta=["-map_metadata", "-1"],
        video_codec="libx264",
        extra_video_encoder_args=["-crf", "23", "-pix_fmt", "yuv420p"],
        output_path=tmp_path / "x.mp4",
    )
    assert argv[0] == "ffmpeg"
    assert argv.count("-i") == 2
    assert "-filter_complex" in argv


# ─── Новые тесты: функционал добавленный в рефакторинге ──────────────────────

# --- Hue-вращение ---

def test_hue_present_in_filter_complex():
    """Hue-вращение должно присутствовать в filter_complex при uniqualize_intensity != low."""
    # Запускаем несколько раз: hue_deg рандомный, но диапазон ненулевой при med/high.
    found = False
    for _ in range(30):
        fc, _ = le.build_filter_complex("deep", "default", False, uniqualize_intensity="high")
        if "hue=h=" in fc:
            found = True
            break
    assert found, "hue=h= не найден в filter_complex при uniqualize_intensity=high"


def test_hue_value_within_range():
    """Hue-значение укладывается в ожидаемый диапазон для intensity=high (±5.5)."""
    import re
    for _ in range(20):
        fc, _ = le.build_filter_complex("ultra", "default", False, uniqualize_intensity="high")
        m = re.search(r"hue=h=([+-]?\d+\.\d+)", fc)
        if m:
            val = float(m.group(1))
            assert -6.0 <= val <= 6.0, f"hue вне диапазона: {val}"
            return
    # Если за 20 попыток не попали — hue=0, это валидно для очень узкого диапазона.


# --- Random trim ---

def test_trim_present_in_filter_complex():
    """trim=start_frame должен появляться при intensity=high."""
    found = False
    for _ in range(30):
        fc, _ = le.build_filter_complex("deep", "default", False, uniqualize_intensity="high")
        if "trim=start_frame=" in fc:
            found = True
            break
    assert found, "trim=start_frame= не найден при intensity=high"


def test_trim_frame_range():
    """start_frame не выходит за пределы [0, 3]."""
    import re
    for _ in range(30):
        fc, _ = le.build_filter_complex("deep", "default", False, uniqualize_intensity="high")
        m = re.search(r"trim=start_frame=(\d+)", fc)
        if m:
            val = int(m.group(1))
            assert 0 <= val <= 3, f"trim=start_frame вне диапазона: {val}"


# --- FPS-вариация ---

def test_fps_present_in_filter_complex():
    """fps=fps= должен присутствовать в filter_complex."""
    fc, _ = le.build_filter_complex("deep", "default", False)
    assert "fps=fps=" in fc


def test_fps_within_range():
    """FPS укладывается в 29.9–30.1."""
    import re
    for _ in range(10):
        fc, _ = le.build_filter_complex("deep", "default", False, uniqualize_intensity="high")
        m = re.search(r"fps=fps=([0-9.]+)", fc)
        if m:
            val = float(m.group(1))
            assert 29.9 <= val <= 30.1, f"FPS вне диапазона: {val}"


# --- Fade in/out ---

def test_fade_present_in_all_templates():
    """fade=t=in и fade=t=out должны присутствовать во всех шаблонах при известной длительности."""
    for tmpl in le.MONTAGE_TEMPLATES:
        fc, _ = le.build_filter_complex("deep", tmpl, True, duration_sec=30.0)
        assert "fade=t=in" in fc, f"fade=t=in отсутствует в шаблоне {tmpl}"
        assert "fade=t=out" in fc, f"fade=t=out отсутствует в шаблоне {tmpl}"


def test_fade_out_absent_without_duration():
    """Без duration_sec fade=t=out не добавляется (нет данных о длине видео)."""
    fc, _ = le.build_filter_complex("deep", "default", True)
    assert "fade=t=in" in fc
    assert "fade=t=out" not in fc


def test_audio_fade_present_when_audio():
    """afade должен быть в аудио-цепочке при with_audio=True и известной длительности."""
    fc, _ = le.build_filter_complex("deep", "default", True, duration_sec=30.0)
    assert "afade=t=in" in fc
    assert "afade=t=out" in fc


def test_no_audio_fade_without_audio():
    """При with_audio=False аудио-цепочка не генерируется."""
    fc, _ = le.build_filter_complex("deep", "default", False)
    assert "afade" not in fc
    assert "[aout]" not in fc


# --- Баг-фикс story + effects ---

def test_story_template_applies_effects():
    """story должен применять mirror/noise/speed — баг до фикса."""
    for _ in range(5):
        fc, _ = le.build_filter_complex(
            "deep", "story", False,
            effects={"mirror": True, "noise": True},
            uniqualize_intensity="high",
        )
        assert "hflip" in fc, "mirror (hflip) не применился в шаблоне story"
        assert "noise=" in fc, "noise не применился в шаблоне story"


def test_story_template_applies_speed():
    """story + speed: setpts должен появляться."""
    for _ in range(5):
        fc, _ = le.build_filter_complex(
            "deep", "story", True,
            effects={"speed": True},
        )
        assert "setpts=PTS/" in fc, "speed (setpts) не применился в шаблоне story"


# --- Новые blend-режимы ---

def test_new_blend_modes_pass_through_correctly():
    """multiply/overlay/hardlight/softlight/difference/exclusion/lighten/addition — реальные режимы."""
    real_blend_modes = ["multiply", "overlay", "hardlight", "softlight", "difference", "exclusion", "lighten"]
    for mode in real_blend_modes:
        fc, _ = le.build_filter_complex(
            "deep", "default", False,
            overlay_blend_mode=mode, overlay_opacity=0.8,
        )
        assert f"blend=all_mode={mode}" in fc, f"blend mode {mode} не найден в filter_complex"


def test_addition_blend_uses_colorchannelmixer():
    """addition — специальный путь через colorchannelmixer."""
    fc, _ = le.build_filter_complex(
        "deep", "default", False,
        overlay_blend_mode="addition", overlay_opacity=0.6,
    )
    assert "blend=all_mode=addition" in fc
    assert "colorchannelmixer=aa=0.6000" in fc


def test_russian_blend_aliases_new():
    """Новые русские алиасы корректно резолвятся."""
    assert le._normalize_overlay_blend("Осветление") == "lighten"
    assert le._normalize_overlay_blend("Умножение") == "multiply"
    assert le._normalize_overlay_blend("Перекрытие") == "overlay"
    assert le._normalize_overlay_blend("Жёсткий_свет") == "hardlight"
    assert le._normalize_overlay_blend("Мягкий_свет") == "softlight"
    assert le._normalize_overlay_blend("Разница") == "difference"
    assert le._normalize_overlay_blend("Исключение") == "exclusion"
    assert le._normalize_overlay_blend("Добавление") == "addition"


# --- GOP рандомизация ---

@pytest.mark.asyncio
async def test_render_gop_randomized_in_args(monkeypatch, tmp_path, tiny_mp4, tiny_png):
    """GOP (-g) должен присутствовать в argv FFmpeg и быть в диапазоне [60, 360] (как в luxury_engine)."""
    captured: list[str] = []

    async def fake_run(args):
        captured.extend(args)
        outp = Path(args[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"ok")
        return 0, b"", b""

    async def no_audio(_):
        return False

    _patch_ffmpeg_runner(monkeypatch, fake_run)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", no_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")

    out = tmp_path / "gop.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out)
    assert r["status"] == "ok"
    assert "-g" in captured
    g_val = int(captured[captured.index("-g") + 1])
    assert 60 <= g_val <= 360, f"GOP вне диапазона: {g_val}"


# --- Encoder metadata ---

@pytest.mark.asyncio
async def test_render_encoder_metadata_present(monkeypatch, tmp_path, tiny_mp4, tiny_png):
    """metadata encoder= должен присутствовать в argv FFmpeg."""
    captured: list[str] = []

    async def fake_run(args):
        captured.extend(args)
        outp = Path(args[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"ok")
        return 0, b"", b""

    async def no_audio(_):
        return False

    _patch_ffmpeg_runner(monkeypatch, fake_run)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", no_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")

    out = tmp_path / "enc.mp4"
    r = await le.render_unique_video(tiny_mp4, tiny_png, out)
    assert r["status"] == "ok"
    meta_args = " ".join(captured)
    assert "encoder=Lavf" in meta_args, "encoder= metadata не найден в argv"


@pytest.mark.asyncio
async def test_render_encoder_string_varies(monkeypatch, tmp_path, tiny_mp4, tiny_png):
    """Строка encoder отличается между рендерами (за 20 попыток должны встретить ≥ 2 варианта)."""
    seen: set[str] = set()

    async def fake_run(args):
        for i, a in enumerate(args):
            if a == "-metadata":
                nxt = args[i + 1] if i + 1 < len(args) else ""
                if nxt.startswith("encoder="):
                    seen.add(nxt)
        outp = Path(args[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"ok")
        return 0, b"", b""

    async def no_audio(_):
        return False

    _patch_ffmpeg_runner(monkeypatch, fake_run)
    monkeypatch.setattr(ffmpeg_runner, "probe_has_audio_stream", no_audio)
    monkeypatch.setattr(le.shutil, "which", lambda x: "ffmpeg")
    monkeypatch.setenv("NEORENDER_DISABLE_NVENC", "1")

    for i in range(20):
        out = tmp_path / f"enc_{i}.mp4"
        await le.render_unique_video(tiny_mp4, tiny_png, out)

    assert len(seen) >= 2, f"encoder string не варьируется: {seen}"


# --- Расширенные гео-профили ---

def test_new_geo_profiles_exist():
    """Новые корейские города присутствуют в _GEO_PROFILES."""
    profiles = le.get_geo_profiles()
    for city in ["daegu", "daejeon", "gwangju", "suwon", "jeju", "ulsan", "pohang"]:
        assert city in profiles, f"Гео-профиль {city} отсутствует"


def test_geo_coordinates_valid_ranges():
    """Координаты всех профилей в валидных географических диапазонах."""
    for name, coords in le.get_geo_profiles().items():
        lat, lng = coords["lat"], coords["lng"]
        assert -90 <= lat <= 90, f"{name}: широта {lat} вне диапазона"
        assert -180 <= lng <= 180, f"{name}: долгота {lng} вне диапазона"


def test_custom_geo_parse_valid():
    """Произвольные координаты через запятую правильно парсятся."""
    result = le._parse_custom_geo("37.5665,126.9780")
    assert result is not None
    lat, lon = result
    assert abs(lat - 37.5665) < 0.0001
    assert abs(lon - 126.9780) < 0.0001


def test_custom_geo_parse_with_signs():
    """Координаты с явными знаками."""
    result = le._parse_custom_geo("+51.5074,-0.1278")
    assert result is not None
    lat, lon = result
    assert abs(lat - 51.5074) < 0.0001
    assert abs(lon + 0.1278) < 0.0001


def test_custom_geo_parse_invalid():
    """Невалидные строки возвращают None."""
    assert le._parse_custom_geo("not_a_coord") is None
    assert le._parse_custom_geo("200.0,50.0") is None   # lat > 90
    assert le._parse_custom_geo("") is None


def test_custom_geo_used_in_exif():
    """Произвольные координаты используются при генерации EXIF-строки."""
    loc = le._random_location_exif("51.5074,-0.1278", jitter=0.001)
    assert loc.startswith("+51.") or loc.startswith("+51")
    assert "-0." in loc or "-0" in loc


def test_new_geo_profiles_used_in_exif():
    """Новые профили дают валидную EXIF-строку."""
    for city in ["jeju", "daegu", "gwangju"]:
        loc = le._random_location_exif(city, jitter=0.01)
        assert loc.endswith("/")
        assert "+" in loc


# --- Уникальность между рендерами ---

def test_filter_complex_differs_between_calls():
    """Два вызова build_filter_complex дают разные filter_complex (случайность работает)."""
    results = set()
    for _ in range(10):
        fc, _ = le.build_filter_complex("deep", "default", True, uniqualize_intensity="high")
        results.add(fc)
    assert len(results) > 1, "filter_complex одинаковый во всех вызовах — рандомизация сломана"


def test_all_templates_produce_valid_vmap():
    """Все шаблоны возвращают [vout] или [vfinal] как vmap."""
    for tmpl in le.MONTAGE_TEMPLATES:
        _, vmap = le.build_filter_complex("deep", tmpl, True)
        assert vmap in ("[vout]", "[vfinal]"), f"Неожиданный vmap={vmap!r} для {tmpl}"


def test_all_presets_produce_valid_filter():
    """Все пресеты успешно строят непустой filter_complex."""
    for preset in le.RENDER_PRESETS:
        fc, vmap = le.build_filter_complex(preset, "default", True)
        assert fc.strip(), f"Пустой filter_complex для пресета {preset}"
        assert "vout" in vmap


# ─── Интеграционные тесты (реальный FFmpeg) ──────────────────────────────────

import shutil
import subprocess

pytestmark_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg не найден в PATH"
)


@pytest.fixture(scope="module")
def real_h264_mp4(tmp_path_factory) -> Path:
    """Настоящий H.264/AAC MP4, 3 секунды 720×1280."""
    p = tmp_path_factory.mktemp("real_video") / "src.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=720x1280:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-c:a", "aac", "-t", "3",
            str(p),
        ],
        check=True,
        capture_output=True,
    )
    return p


@pytest.fixture(scope="module")
def real_h264_noaudio(tmp_path_factory) -> Path:
    """H.264 MP4 без звука, 3 секунды."""
    p = tmp_path_factory.mktemp("noaudio") / "noaudio.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=720x1280:rate=30",
            "-c:v", "libx264", "-an", "-t", "3",
            str(p),
        ],
        check=True,
        capture_output=True,
    )
    return p


@pytest.fixture(scope="module")
def real_overlay_png(tmp_path_factory) -> Path:
    """PNG 200×200 для использования в реальных тестах."""
    p = tmp_path_factory.mktemp("overlay") / "ov.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x200:d=1", "-frames:v", "1", str(p)],
        check=True,
        capture_output=True,
    )
    return p


# --- _invis_drawtext_font_arg: fontfile= вместо font=Arial ---

def test_invis_drawtext_uses_fontfile_not_arial():
    """После фикса drawtext должен использовать fontfile= (обход fontconfig), не font=Arial."""
    arg = le._invis_drawtext_font_arg()
    assert arg.startswith("fontfile="), f"Ожидался fontfile=, получен: {arg!r}"
    assert "Pretendard-Regular.otf" in arg
    assert "font=Arial" not in arg


def test_invis_drawtext_path_escapes_windows_drive_colon():
    """Путь к шрифту содержит экранированное ':' после буквы диска (Windows)."""
    import sys
    if sys.platform != "win32":
        pytest.skip("Только для Windows")
    arg = le._invis_drawtext_font_arg()
    # На Windows путь выглядит как C\:/path/to/font.otf
    assert r"\:" in arg, f"Диск ':' не экранирован в fontfile: {arg!r}"


# --- probe_video_codec ---

@pytest.mark.asyncio
async def test_probe_video_codec_returns_h264(real_h264_mp4):
    """probe_video_codec возвращает 'h264' для стандартного MP4."""
    codec = await ffmpeg_runner.probe_video_codec(real_h264_mp4)
    assert codec == "h264", f"Ожидался h264, получен: {codec!r}"


@pytest.mark.asyncio
async def test_probe_video_codec_returns_none_for_missing():
    """probe_video_codec возвращает None для несуществующего файла."""
    from pathlib import Path
    result = await ffmpeg_runner.probe_video_codec(Path("/nonexistent/file.mov"))
    assert result is None


# --- _ffmpeg_stderr_hint ---

def test_ffmpeg_stderr_hint_extracts_error_line():
    from core.luxury_engine import _ffmpeg_stderr_hint
    err = b"some preamble\nError opening filters!\nDecoder not found\n"
    hint = _ffmpeg_stderr_hint(err)
    assert "Decoder" in hint or "Error" in hint or "decoder" in hint.lower()


def test_ffmpeg_stderr_hint_empty_returns_empty():
    from core.luxury_engine import _ffmpeg_stderr_hint
    assert _ffmpeg_stderr_hint(b"") == ""


def test_ffmpeg_stderr_hint_no_error_returns_last_line():
    from core.luxury_engine import _ffmpeg_stderr_hint
    err = b"line1\nsome random output\nlast line"
    hint = _ffmpeg_stderr_hint(err)
    assert hint  # не пусто


# --- Реальный рендер: все основные сценарии ---

@pytest.mark.asyncio
async def test_real_render_default_succeeds(real_h264_mp4, real_overlay_png, tmp_path):
    """Базовый рендер с реальным FFmpeg должен завершаться успехом."""
    import os
    os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    out = tmp_path / "out_default.mp4"
    r = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        geo_enabled=False, perceptual_hash_check=False,
    )
    assert r["status"] == "ok", f"Рендер упал: {r.get('message')}"
    assert out.is_file() and out.stat().st_size > 0


@pytest.mark.asyncio
async def test_real_render_story_template(real_h264_mp4, real_overlay_png, tmp_path):
    """Шаблон story с реальным FFmpeg."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    out = tmp_path / "out_story.mp4"
    r = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        template="story", geo_enabled=False, perceptual_hash_check=False,
    )
    assert r["status"] == "ok", f"story упал: {r.get('message')}"
    assert out.is_file() and out.stat().st_size > 0


@pytest.mark.asyncio
async def test_real_render_all_templates(real_h264_mp4, real_overlay_png, tmp_path):
    """Все шаблоны рендерятся без ошибок."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    for tmpl in le.MONTAGE_TEMPLATES:
        out = tmp_path / f"out_{tmpl}.mp4"
        r = await le.render_unique_video(
            real_h264_mp4, real_overlay_png, out,
            template=tmpl, geo_enabled=False, perceptual_hash_check=False,
        )
        assert r["status"] == "ok", f"Шаблон {tmpl!r} упал: {r.get('message')}"
        assert out.is_file() and out.stat().st_size > 0


@pytest.mark.asyncio
async def test_real_render_all_presets(real_h264_mp4, real_overlay_png, tmp_path):
    """Все пресеты рендерятся без ошибок."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    for preset in le.RENDER_PRESETS:
        out = tmp_path / f"out_{preset}.mp4"
        r = await le.render_unique_video(
            real_h264_mp4, real_overlay_png, out,
            preset=preset, geo_enabled=False, perceptual_hash_check=False,
        )
        assert r["status"] == "ok", f"Пресет {preset!r} упал: {r.get('message')}"


@pytest.mark.asyncio
async def test_real_render_no_audio(real_h264_noaudio, real_overlay_png, tmp_path):
    """Рендер видео без аудиодорожки — FFmpeg не должен падать на [aout]."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    out = tmp_path / "out_noaudio.mp4"
    r = await le.render_unique_video(
        real_h264_noaudio, real_overlay_png, out,
        geo_enabled=False, perceptual_hash_check=False,
    )
    assert r["status"] == "ok", f"noaudio рендер упал: {r.get('message')}"


@pytest.mark.asyncio
async def test_real_render_all_blend_modes(real_h264_mp4, real_overlay_png, tmp_path):
    """Все blend-режимы успешно кодируются реальным FFmpeg."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    modes = ["normal", "screen", "multiply", "overlay", "darken", "lighten",
             "hardlight", "softlight", "difference", "exclusion", "addition", "linekey"]
    for mode in modes:
        out = tmp_path / f"out_blend_{mode}.mp4"
        r = await le.render_unique_video(
            real_h264_mp4, real_overlay_png, out,
            overlay_blend_mode=mode, geo_enabled=False, perceptual_hash_check=False,
        )
        assert r["status"] == "ok", f"blend_mode={mode!r} упал: {r.get('message')}"


@pytest.mark.asyncio
async def test_real_render_effects(real_h264_mp4, real_overlay_png, tmp_path):
    """Эффекты mirror/noise/speed/crop_reframe проходят реальный FFmpeg."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    out = tmp_path / "out_effects.mp4"
    r = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        effects={"mirror": True, "noise": True, "speed": True},
        geo_enabled=False, perceptual_hash_check=False,
    )
    assert r["status"] == "ok", f"effects упал: {r.get('message')}"


@pytest.mark.asyncio
async def test_real_render_under_video_mode(real_h264_mp4, real_overlay_png, tmp_path):
    """overlay_mode=under_video с реальным FFmpeg (scale2ref + overlay)."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    out = tmp_path / "out_under.mp4"
    r = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        overlay_mode="under_video", geo_enabled=False, perceptual_hash_check=False,
    )
    assert r["status"] == "ok", f"under_video упал: {r.get('message')}"


@pytest.mark.asyncio
async def test_real_render_cancel_event(real_h264_mp4, real_overlay_png, tmp_path):
    """Cancel event до старта возвращает статус error (не ok, не исключение)."""
    import asyncio as _aio
    cancel = _aio.Event()
    cancel.set()
    out = tmp_path / "out_cancel.mp4"
    r = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        cancel_event=cancel, geo_enabled=False,
    )
    assert r["status"] == "error"
    assert not out.is_file() or out.stat().st_size == 0


@pytest.mark.asyncio
async def test_real_render_progress_callback_called(real_h264_mp4, real_overlay_png, tmp_path):
    """progress_callback вызывается ≥1 раза и финальный percent == 100."""
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    log: list[tuple[float, str]] = []

    async def cb(pct, label, metrics=None):
        log.append((pct, label))

    out = tmp_path / "out_progress.mp4"
    r = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        geo_enabled=False, perceptual_hash_check=False,
        progress_callback=cb,
    )
    assert r["status"] == "ok"
    assert len(log) >= 1
    percents = [p for p, _ in log]
    assert max(percents) == 100.0, f"Финальный прогресс не 100: {percents[-3:]}"


@pytest.mark.asyncio
async def test_real_render_drawtext_fontfile_not_crash(real_h264_mp4, real_overlay_png, tmp_path):
    """
    Рендер НЕ должен падать с SIGSEGV/код 139 из-за fontconfig.
    Фикс: drawtext использует fontfile= вместо font=Arial.
    Проверяем, что у нас нет font=Arial в filter_complex.
    """
    import os; os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    out = tmp_path / "out_drawtext.mp4"
    r = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        geo_enabled=False, perceptual_hash_check=False,
        uniqualize_intensity="high",
    )
    assert r["status"] == "ok", f"Возможен segfault в drawtext: {r.get('message')}"
    # Дополнительно: dry_run — убедиться что font=Arial не попал в аргументы
    r_dry = await le.render_unique_video(
        real_h264_mp4, real_overlay_png, out,
        geo_enabled=False, dry_run=True, uniqualize_intensity="high",
    )
    args_str = " ".join(r_dry.get("ffmpeg_args_x264") or [])
    assert "font=Arial" not in args_str, "font=Arial обнаружен в аргументах FFmpeg — фикс не работает"
