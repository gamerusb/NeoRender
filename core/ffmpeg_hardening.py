"""
Безопасная сборка argv для FFmpeg:
- строгая валидация stream mapping;
- безопасное добавление -vsync (опционально);
- единый builder для всех проходов (GPU/CPU).
"""

from __future__ import annotations

from pathlib import Path


ALLOWED_VSYNC = {"vfr", "2", "cfr", "0", "1"}


def validate_filter_complex(filter_complex: str) -> str:
    fc = str(filter_complex or "").strip()
    if not fc:
        raise ValueError("Пустой filter_complex")
    if "\n" in fc or "\r" in fc:
        raise ValueError("filter_complex не должен содержать переносы строк")
    return fc


def validate_stream_map(video_map: str, with_audio: bool) -> None:
    vm = str(video_map or "").strip()
    if not (vm.startswith("[") and vm.endswith("]")):
        raise ValueError(f"Некорректная video map метка: {video_map!r}")
    if with_audio and vm == "[aout]":
        raise ValueError("video_map не может указывать на аудио-метку [aout]")


def normalize_vsync(vsync_mode: str | None) -> str | None:
    if vsync_mode is None:
        return None
    mode = str(vsync_mode).strip().lower()
    if not mode:
        return None
    if mode not in ALLOWED_VSYNC:
        raise ValueError(f"Неподдерживаемый vsync режим: {vsync_mode!r}")
    return mode


def build_ffmpeg_encode_argv(
    *,
    ffmpeg_exe: str,
    input_video: Path,
    overlay_input_args: list[str],
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
    dub_input_args: list[str] | None = None,
) -> list[str]:
    validate_stream_map(video_map, with_audio)
    fc = validate_filter_complex(filter_complex)
    vsync = normalize_vsync(vsync_mode)

    maps_audio: list[str] = ["-map", "[aout]"] if with_audio else []
    audio_enc = ["-c:a", "aac", "-b:a", audio_bitrate] if with_audio else ["-an"]

    main_in_path = str(input_video.resolve())
    ss_part: list[str] = []
    if main_input_ss_sec is not None and float(main_input_ss_sec) > 1e-4:
        ss_part = ["-ss", f"{float(main_input_ss_sec):.4f}"]
    t_after_i: list[str] = []
    if main_input_t_sec is not None and float(main_input_t_sec) > 0.05:
        t_after_i = ["-t", f"{float(main_input_t_sec):.4f}"]

    out: list[str] = [
        ffmpeg_exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *ss_part,
        "-i",
        main_in_path,
        *t_after_i,
        *overlay_input_args,
        *(dub_input_args or []),
        "-filter_complex",
        fc,
        "-map",
        video_map,
        *maps_audio,
        *common_meta,
        "-c:v",
        video_codec,
        *extra_video_encoder_args,
        *audio_enc,
        "-max_muxing_queue_size",
        "1024",
        "-movflags",
        "+faststart",
    ]
    if vsync is not None:
        out.extend(["-vsync", vsync])
    out.append(str(output_path.resolve()))
    return out

