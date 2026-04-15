"""
Запуск FFmpeg / ffprobe в одном месте: прогресс, ошибки, Windows без консольных всплытий.

Отделение от luxury_engine упрощает тесты и снижает риск регрессий в subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Таймаут ffprobe: зависший процесс даёт «вечные 4%» в UI без кодирования.
_DEFAULT_PROBE_TIMEOUT = 60.0

# Кодирование без лимита может «висеть» вечно, если FFmpeg завис. 0 / none = без лимита.
_FFMPEG_TIMEOUT_DEFAULT_SEC = 14_400.0  # 4 ч
_FFMPEG_TIMEOUT_EXIT = -124


def _ffmpeg_encode_timeout_sec() -> float | None:
    raw = os.environ.get("NEORENDER_FFMPEG_TIMEOUT_SEC")
    if raw is None:
        return _FFMPEG_TIMEOUT_DEFAULT_SEC
    s = str(raw).strip().lower()
    if s in ("0", "", "none", "off", "inf"):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return _FFMPEG_TIMEOUT_DEFAULT_SEC


def _ffmpeg_stall_timeout_sec() -> float | None:
    """
    Таймаут «нет прогресса» для FFmpeg: процесс жив, но out_time/fps не двигаются.
    0/none/off = отключено.
    """
    raw = os.environ.get("NEORENDER_FFMPEG_STALL_SEC")
    if raw is None:
        return 120.0
    s = str(raw).strip().lower()
    if s in ("0", "", "none", "off", "inf"):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return 120.0


async def _communicate_kill_on_timeout(
    proc: asyncio.subprocess.Process, timeout_sec: float | None
) -> tuple[bytes, bytes, int]:
    """
    Дождаться завершения процесса. При таймауте — kill и короткое ожидание drain.
    Возвращает (stdout, stderr, returncode_после_ожидания).
    """
    if timeout_sec is None:
        out, err = await proc.communicate()
        return out or b"", err or b"", proc.returncode if proc.returncode is not None else 0

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        return out or b"", err or b"", proc.returncode if proc.returncode is not None else 0
    except asyncio.TimeoutError:
        logger.error(
            "ffmpeg: превышен таймаут кодирования (%.0f с). Убейте зависший процесс или увеличьте NEORENDER_FFMPEG_TIMEOUT_SEC.",
            timeout_sec,
        )
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=90.0)
        except asyncio.TimeoutError:
            out, err = b"", b""
        return (
            out or b"",
            (err or b"") + b"\n[neorender] ffmpeg: timeout encoding",
            _FFMPEG_TIMEOUT_EXIT,
        )


async def _communicate_or_kill(
    proc: asyncio.subprocess.Process, timeout: float
) -> tuple[bytes, bytes]:
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "ffprobe: таймаут %.0f с (pid=%s), процесс останавливается",
            timeout,
            getattr(proc, "pid", None),
        )
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        raise


def ffmpeg_bin() -> str:
    return (os.environ.get("FFMPEG_PATH") or "ffmpeg").strip() or "ffmpeg"


def ffprobe_bin() -> str:
    env = (os.environ.get("FFPROBE_PATH") or "").strip()
    if env:
        return env
    ff = ffmpeg_bin()
    if ff != "ffmpeg" and Path(ff).is_file():
        return str(Path(ff).parent / "ffprobe")
    return "ffprobe"


async def probe_ffmpeg_runs(exe: str | None = None) -> tuple[bool, str]:
    """
    Проверка, что бинарник FFmpeg реально запускается (не только есть в PATH).
    Возвращает (успех, первая строка вывода или сообщение об ошибке).
    """
    cmd = (exe or ffmpeg_bin()).strip() or "ffmpeg"
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd,
            "-hide_banner",
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode != 0:
            return False, f"код выхода {proc.returncode}"
        raw = (out or b"") + (err or b"")
        line = raw.decode("utf-8", errors="replace").splitlines()[0].strip()
        return True, line or "ffmpeg"
    except FileNotFoundError:
        return False, "исполняемый файл не найден"
    except asyncio.TimeoutError:
        return False, "таймаут запуска"
    except Exception as exc:
        return False, str(exc).strip()[:200] or "ошибка запуска"


def _windows_subprocess_kwargs() -> dict:
    """На Windows не поднимать отдельное консольное окно (меньше мельканий и сбоев)."""
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not flags:
        return {}
    return {"creationflags": flags}


def _ffmpeg_args_with_progress(args: list[str], prog_path: str) -> list[str]:
    a = list(args)
    for i, x in enumerate(a):
        if x == "-loglevel" and i + 1 < len(a):
            a[i + 2 : i + 2] = ["-progress", prog_path]
            return a
    if len(a) >= 1:
        a[1:1] = ["-progress", prog_path]
    return a


def progress_file_output_seconds(content: str) -> float | None:
    """Последнее out_time_* из файла прогресса FFmpeg (значение в микросекундах)."""
    last_us: int | None = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("out_time_us="):
            try:
                last_us = int(line.split("=", 1)[1].strip())
            except ValueError:
                continue
        elif line.startswith("out_time_ms="):
            try:
                last_us = int(line.split("=", 1)[1].strip())
            except ValueError:
                continue
    if last_us is None:
        return None
    return max(0.0, last_us / 1_000_000.0)


def progress_file_metrics(content: str) -> dict[str, float]:
    """
    Метрики из progress-файла FFmpeg (последние значения).

    Пример строк:
      fps=28.0
      speed=1.02x
      out_time_us=1234567
    """
    out: dict[str, float] = {}
    out_sec = progress_file_output_seconds(content)
    if out_sec is not None:
        out["out_time_sec"] = float(out_sec)
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("fps="):
            try:
                out["fps"] = float(s.split("=", 1)[1].strip())
            except ValueError:
                pass
        elif s.startswith("speed="):
            raw = s.split("=", 1)[1].strip().lower()
            if raw.endswith("x"):
                raw = raw[:-1]
            try:
                out["speed"] = float(raw)
            except ValueError:
                pass
    return out


async def run_ffmpeg(
    args: list[str],
    *,
    cancel_event: asyncio.Event | None = None,
) -> tuple[int, bytes, bytes]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        if cancel_event is None:
            tout = _ffmpeg_encode_timeout_sec()
            out, err, code = await _communicate_kill_on_timeout(proc, tout)
            return code, out, err

        comm = asyncio.create_task(proc.communicate())
        ev_wait = asyncio.create_task(cancel_event.wait())
        done, _ = await asyncio.wait(
            {comm, ev_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if ev_wait in done and not comm.done():
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            ev_wait.cancel()
            try:
                await ev_wait
            except asyncio.CancelledError:
                pass
            try:
                out, err = await asyncio.wait_for(comm, timeout=60.0)
            except asyncio.TimeoutError:
                out, err = b"", b""
            code = proc.returncode if proc.returncode is not None else -9
            return code, out or b"", err or b""

        ev_wait.cancel()
        try:
            await ev_wait
        except asyncio.CancelledError:
            pass
        out, err = await comm
        return proc.returncode if proc.returncode is not None else -1, out or b"", err or b""
    except FileNotFoundError:
        return -1, b"", b"ffmpeg not found"
    except Exception as exc:
        logger.exception("run_ffmpeg: %s", exc)
        return -2, b"", str(exc).encode("utf-8", errors="replace")


async def run_ffmpeg_with_progress(
    args: list[str],
    *,
    duration_sec: float | None,
    progress_cb: Callable[[float, str], Awaitable[None]] | None,
    encode_label: str,
    cancel_event: asyncio.Event | None = None,
) -> tuple[int, bytes, bytes]:
    if progress_cb is None:
        return await run_ffmpeg(args, cancel_event=cancel_event)

    # Кешируем арность коллбека один раз — не вызываем inspect на каждом тике.
    _cb_has_metrics = len(inspect.signature(progress_cb).parameters) >= 3

    async def _call_cb(pct: float, metrics: dict | None = None) -> None:
        try:
            if _cb_has_metrics:
                await progress_cb(pct, encode_label, metrics or {})  # type: ignore[misc]
            else:
                await progress_cb(pct, encode_label)
        except Exception:
            pass

    fd, prog_path = tempfile.mkstemp(prefix="neo_ffp_", suffix=".txt")
    os.close(fd)
    args_p = _ffmpeg_args_with_progress(args, prog_path)
    stop = asyncio.Event()
    prog_file = Path(prog_path)
    proc_holder: list[asyncio.subprocess.Process | None] = [None]
    stalled_flag = {"value": False}

    async def _poller() -> None:
        last_shown = -1.0
        last_progress_ts = asyncio.get_event_loop().time()
        last_out_sec = -1.0
        stall_sec = _ffmpeg_stall_timeout_sec()
        while not stop.is_set():
            if cancel_event and cancel_event.is_set():
                p = proc_holder[0]
                if p and p.returncode is None:
                    try:
                        p.kill()
                    except ProcessLookupError:
                        pass
                return
            await asyncio.sleep(0.25)
            if cancel_event and cancel_event.is_set():
                p = proc_holder[0]
                if p and p.returncode is None:
                    try:
                        p.kill()
                    except ProcessLookupError:
                        pass
                return
            try:
                txt = prog_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "progress=end" in txt:
                await _call_cb(99.0, progress_file_metrics(txt))
                return
            out_sec = progress_file_output_seconds(txt)
            if out_sec is not None and out_sec > last_out_sec + 0.01:
                last_out_sec = out_sec
                last_progress_ts = asyncio.get_event_loop().time()
            if stall_sec is not None:
                p = proc_holder[0]
                if p and p.returncode is None:
                    now = asyncio.get_event_loop().time()
                    if now - last_progress_ts > stall_sec:
                        stalled_flag["value"] = True
                        try:
                            p.kill()
                        except ProcessLookupError:
                            pass
                        return
            if out_sec is None:
                continue
            if duration_sec and duration_sec > 0:
                pct = min(99.0, max(0.0, (out_sec / duration_sec) * 100.0))
            else:
                pct = min(99.0, out_sec * 2.0)
            if pct - last_shown >= 0.5 or pct >= 98.0:
                last_shown = pct
                await _call_cb(pct, progress_file_metrics(txt))

    poll_task = asyncio.create_task(_poller())
    code = -3
    out = b""
    err = b""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args_p,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        proc_holder[0] = proc
        tout = _ffmpeg_encode_timeout_sec()
        out, err, code = await _communicate_kill_on_timeout(proc, tout)
    finally:
        stop.set()
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        try:
            prog_file.unlink(missing_ok=True)
        except OSError:
            pass

    if cancel_event and cancel_event.is_set():
        return -9, out or b"", err or b""
    if stalled_flag["value"]:
        return -125, out or b"", (err or b"") + b"\n[neorender] ffmpeg: stalled (no progress)"
    if code == 0:
        await _call_cb(100.0, {})
    return code, out or b"", err or b""


async def probe_video_duration_seconds(
    path: Path, *, timeout_sec: float = _DEFAULT_PROBE_TIMEOUT
) -> float | None:
    probe = ffprobe_bin()
    try:
        proc = await asyncio.create_subprocess_exec(
            probe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        try:
            out, _ = await _communicate_or_kill(proc, timeout_sec)
        except asyncio.TimeoutError:
            return None
        if proc.returncode != 0:
            return None
        s = (out or b"").decode("utf-8", errors="replace").strip()
        if not s or s == "N/A":
            return None
        d = float(s)
        return d if d > 0.05 else None
    except (FileNotFoundError, ValueError, OSError):
        return None


async def probe_video_dimensions(
    path: Path, *, timeout_sec: float = _DEFAULT_PROBE_TIMEOUT
) -> tuple[int, int] | None:
    """Ширина×высота первого видеопотока (чётные значения как у ffprobe) или None."""
    probe = ffprobe_bin()
    try:
        proc = await asyncio.create_subprocess_exec(
            probe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        try:
            out, _ = await _communicate_or_kill(proc, timeout_sec)
        except asyncio.TimeoutError:
            return None
        if proc.returncode != 0:
            return None
        s = (out or b"").decode("utf-8", errors="replace").strip().lower()
        if "x" not in s:
            return None
        a, b = s.split("x", 1)
        w = int(a.strip())
        h = int(b.strip())
        if w < 2 or h < 2:
            return None
        return (w, h)
    except (FileNotFoundError, ValueError, OSError):
        return None


async def probe_has_audio_stream(
    path: Path, *, timeout_sec: float = _DEFAULT_PROBE_TIMEOUT
) -> bool:
    probe = ffprobe_bin()
    try:
        proc = await asyncio.create_subprocess_exec(
            probe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        try:
            out, _ = await _communicate_or_kill(proc, timeout_sec)
        except asyncio.TimeoutError:
            logger.warning("probe_has_audio_stream: timeout, считаем что аудио есть")
            return True
        return proc.returncode == 0 and bool(out.strip())
    except FileNotFoundError:
        return True
    except Exception as exc:
        logger.warning("probe_has_audio_stream: %s", exc)
        return True


async def probe_video_fps(
    path: Path, *, timeout_sec: float = _DEFAULT_PROBE_TIMEOUT
) -> float | None:
    """Возвращает реальный FPS видеопотока (avg_frame_rate) или None."""
    probe = ffprobe_bin()
    try:
        proc = await asyncio.create_subprocess_exec(
            probe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        try:
            out, _ = await _communicate_or_kill(proc, timeout_sec)
        except asyncio.TimeoutError:
            return None
        if proc.returncode != 0:
            return None
        s = (out or b"").decode("utf-8", errors="replace").strip()
        if not s or s in ("N/A", "0/0"):
            return None
        # avg_frame_rate возвращается как "30000/1001" или "30/1"
        if "/" in s:
            num, den = s.split("/", 1)
            n, d = float(num), float(den)
            if d == 0:
                return None
            fps = n / d
        else:
            fps = float(s)
        return fps if 1.0 <= fps <= 240.0 else None
    except (FileNotFoundError, ValueError, OSError):
        return None


async def probe_video_codec(
    path: Path, *, timeout_sec: float = _DEFAULT_PROBE_TIMEOUT
) -> str | None:
    """Название кодека первого видеопотока (напр. 'prores', 'hevc', 'h264') или None."""
    probe = ffprobe_bin()
    try:
        proc = await asyncio.create_subprocess_exec(
            probe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        try:
            out, _ = await _communicate_or_kill(proc, timeout_sec)
        except asyncio.TimeoutError:
            return None
        if proc.returncode != 0:
            return None
        s = (out or b"").decode("utf-8", errors="replace").strip().lower()
        return s or None
    except (FileNotFoundError, ValueError, OSError):
        return None


_BLACK_DETECT_RE = re.compile(
    r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)"
)


def parse_black_intervals(stderr_text: str) -> list[tuple[float, float]]:
    """Пары (start, end) из логов фильтра blackdetect."""
    out: list[tuple[float, float]] = []
    for m in _BLACK_DETECT_RE.finditer(stderr_text):
        out.append((float(m.group(1)), float(m.group(2))))
    return out


def parse_silence_intervals(stderr_text: str, duration_sec: float | None) -> list[tuple[float, float]]:
    """Пары (start, end) из silencedetect; если конец файла в тишине — закрываем последний интервал."""
    intervals: list[tuple[float, float]] = []
    pending: float | None = None
    for line in stderr_text.splitlines():
        m1 = re.search(r"silence_start:\s*([\d.]+)", line)
        if m1:
            pending = float(m1.group(1))
            continue
        m2 = re.search(r"silence_end:\s*([\d.]+)", line)
        if m2 and pending is not None:
            intervals.append((pending, float(m2.group(1))))
            pending = None
    if pending is not None and duration_sec is not None and duration_sec > pending + 0.05:
        intervals.append((pending, float(duration_sec)))
    return intervals


def lead_tail_trim_from_intervals(
    intervals: list[tuple[float, float]],
    duration_sec: float | None,
    *,
    edge_eps: float = 0.08,
) -> tuple[float, float]:
    """
    По интервалам «плохого» контента (чёрный / тишина) оценить обрезку с начала и с конца (секунды).
    """
    if not intervals:
        return 0.0, 0.0
    lead = 0.0
    intervals_sorted = sorted(intervals, key=lambda x: x[0])
    first = intervals_sorted[0]
    if first[0] <= edge_eps:
        lead = max(0.0, first[1])
    tail = 0.0
    if duration_sec and duration_sec > edge_eps * 2:
        last = intervals_sorted[-1]
        if last[1] >= duration_sec - edge_eps:
            tail = max(0.0, duration_sec - last[0])
    return lead, tail


async def probe_lead_tail_black_silence(
    path: Path,
    *,
    duration_sec: float | None,
    with_audio: bool,
    max_lead_sec: float = 1.0,
    max_tail_sec: float = 1.0,
    timeout_sec: float = 180.0,
) -> tuple[float, float]:
    """
    silencedetect + blackdetect: сколько секунд срезать с начала и с конца основного входа.
    Возвращает (trim_start_sec, trim_tail_sec). Безопасные потолки — max_lead_sec / max_tail_sec.
    """
    ff = ffmpeg_bin()
    # d= минимальная длительность сегмента; не слишком агрессивно, чтобы не резать контент.
    vf = "blackdetect=d=0.12:pix_th=0.10:pic_th=0.98"
    cmd: list[str] = [
        ff,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        str(path.resolve()),
        "-vf",
        vf,
    ]
    if with_audio:
        cmd.extend(["-af", "silencedetect=noise=-50dB:d=0.22"])
    else:
        cmd.append("-an")
    cmd.extend(["-f", "null", "-"])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.warning("probe_lead_tail_black_silence: таймаут для %s", path)
            return 0.0, 0.0
    except FileNotFoundError:
        return 0.0, 0.0

    text = (err or b"").decode("utf-8", errors="replace")
    b_lead, b_tail = lead_tail_trim_from_intervals(parse_black_intervals(text), duration_sec)
    if with_audio:
        s_lead, s_tail = lead_tail_trim_from_intervals(
            parse_silence_intervals(text, duration_sec), duration_sec
        )
    else:
        s_lead, s_tail = 0.0, 0.0

    trim_start = min(max_lead_sec, max(b_lead, s_lead, 0.0))
    trim_tail = min(max_tail_sec, max(b_tail, s_tail, 0.0))

    if duration_sec and duration_sec > 0.2:
        cap = max(0.0, duration_sec - 0.15)
        if trim_start + trim_tail > cap:
            if cap <= 0:
                return 0.0, 0.0
            scale = cap / (trim_start + trim_tail)
            trim_start *= scale
            trim_tail *= scale
    return trim_start, trim_tail


async def extract_video_frame_png_bytes(
    path: Path, *, time_sec: float, timeout_sec: float = 60.0
) -> bytes | None:
    """Один кадр в PNG (сырые байты) для perceptual hash."""
    ff = ffmpeg_bin()
    if time_sec < 0:
        time_sec = 0.0
    cmd = [
        ff,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{time_sec:.4f}",
        "-i",
        str(path.resolve()),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_windows_subprocess_kwargs(),
        )
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return None
    if proc is None or proc.returncode != 0 or not out or len(out) < 32:
        return None
    return bytes(out)
