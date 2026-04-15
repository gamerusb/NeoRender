from __future__ import annotations

from pathlib import Path

import pytest

from core import ffmpeg_hardening as h


def test_build_ffmpeg_encode_argv_with_vfr():
    argv = h.build_ffmpeg_encode_argv(
        ffmpeg_exe="ffmpeg",
        input_video=Path("in.mp4"),
        overlay_input_args=["-i", "overlay.png"],
        filter_complex="[0:v]null[vout];[0:a]anull[aout]",
        video_map="[vout]",
        with_audio=True,
        audio_bitrate="160k",
        common_meta=["-map_metadata", "-1"],
        video_codec="libx264",
        extra_video_encoder_args=["-crf", "22"],
        output_path=Path("out.mp4"),
        vsync_mode="vfr",
    )
    assert "-filter_complex" in argv
    assert "-map" in argv
    assert "[vout]" in argv
    assert "[aout]" in argv
    assert "-vsync" in argv
    assert "vfr" in argv


def test_build_ffmpeg_encode_argv_main_input_seek_and_duration():
    argv = h.build_ffmpeg_encode_argv(
        ffmpeg_exe="ffmpeg",
        input_video=Path("in.mp4"),
        overlay_input_args=["-i", "ov.png"],
        filter_complex="[0:v]null[vout]",
        video_map="[vout]",
        with_audio=False,
        audio_bitrate="128k",
        common_meta=[],
        video_codec="libx264",
        extra_video_encoder_args=["-crf", "23"],
        output_path=Path("out.mp4"),
        main_input_ss_sec=0.5,
        main_input_t_sec=59.25,
    )
    assert argv[argv.index("-ss") + 1].startswith("0.5")
    i_in = argv.index("-i")
    assert argv[i_in + 1].endswith("in.mp4")
    assert argv[i_in + 2] == "-t"
    assert argv[i_in + 3].startswith("59.25")


def test_validate_stream_map_rejects_audio_label_as_video():
    with pytest.raises(ValueError):
        h.build_ffmpeg_encode_argv(
            ffmpeg_exe="ffmpeg",
            input_video=Path("in.mp4"),
            overlay_input_args=["-i", "overlay.png"],
            filter_complex="[0:v]null[vout];[0:a]anull[aout]",
            video_map="[aout]",
            with_audio=True,
            audio_bitrate="160k",
            common_meta=[],
            video_codec="libx264",
            extra_video_encoder_args=[],
            output_path=Path("out.mp4"),
        )

