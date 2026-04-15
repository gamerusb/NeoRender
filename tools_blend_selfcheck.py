from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

from core import luxury_engine as le
from core import ffmpeg_runner as ff


def _gen_assets(work: Path) -> tuple[Path, Path]:
    work.mkdir(parents=True, exist_ok=True)
    inp = work / "sample_in.mp4"
    ov = work / "sample_overlay.png"
    ffmpeg = ff.ffmpeg_bin()
    if not inp.is_file():
        # Короткий ролик 4 сек: motion + аудио.
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=720x1280:rate=30",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000",
                "-t",
                "4",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(inp),
            ],
            check=True,
        )
    if not ov.is_file():
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=#22aaff@0.6:s=720x1280",
                "-frames:v",
                "1",
                str(ov),
            ],
            check=True,
        )
    return inp, ov


async def main() -> int:
    os.environ.setdefault("NEORENDER_DISABLE_NVENC", "1")
    os.environ.setdefault("NEORENDER_FFMPEG_TIMEOUT_SEC", "120")
    work = Path("data") / "_selfcheck_blend"
    inp, ov = _gen_assets(work)
    modes = list(le.get_overlay_blend_modes().keys())
    out: list[dict[str, object]] = []
    for mode in modes:
        t0 = time.perf_counter()
        dst = work / f"out_{mode}.mp4"
        r = await le.render_unique_video(
            inp,
            ov,
            dst,
            preset="soft",
            template="default",
            overlay_mode="on_top",
            overlay_position="center",
            overlay_blend_mode=mode,
            overlay_opacity=1.0 if mode == "normal" else 0.35,
            subtitle="",
        )
        dt = round(time.perf_counter() - t0, 3)
        ok = r.get("status") == "ok" and dst.is_file() and dst.stat().st_size > 0
        out.append(
            {
                "mode": mode,
                "status": r.get("status"),
                "ok": ok,
                "elapsed_sec": dt,
                "msg": str(r.get("message", ""))[:140],
            }
        )
    print(json.dumps({"modes_total": len(out), "results": out}, ensure_ascii=False, indent=2))
    return 0 if all(x["ok"] for x in out) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
