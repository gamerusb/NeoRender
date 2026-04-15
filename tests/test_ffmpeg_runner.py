"""Тесты ffmpeg_runner: отмена и таймауты без реального FFmpeg."""

from __future__ import annotations

import asyncio

import pytest

from core import ffmpeg_runner as fr


class _FakeProc:
    def __init__(self, *, complete_after: float = 0.0, out: bytes = b"", err: bytes = b"") -> None:
        self.returncode: int | None = None
        self._complete_after = complete_after
        self._out = out
        self._err = err
        self.killed = False
        self.communicate_calls = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        self.communicate_calls += 1
        if self._complete_after > 0:
            waited = 0.0
            while waited < self._complete_after and not self.killed:
                await asyncio.sleep(0.01)
                waited += 0.01
        if self.killed:
            self.returncode = -9 if self.returncode is None else self.returncode
            return b"", b"killed"
        self.returncode = 0 if self.returncode is None else self.returncode
        return self._out, self._err

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


@pytest.mark.asyncio
async def test_run_ffmpeg_timeout_returns_minus_124(monkeypatch):
    proc = _FakeProc(complete_after=0.5)

    async def _fake_create(*_args, **_kwargs):
        return proc

    monkeypatch.setenv("NEORENDER_FFMPEG_TIMEOUT_SEC", "0.01")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    code, _out, err = await fr.run_ffmpeg(["ffmpeg", "-version"])
    assert code == -124
    assert proc.killed is True
    assert b"timeout encoding" in err


@pytest.mark.asyncio
async def test_run_ffmpeg_cancel_event_kills_process(monkeypatch):
    proc = _FakeProc(complete_after=5.0)

    async def _fake_create(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    ev = asyncio.Event()
    task = asyncio.create_task(fr.run_ffmpeg(["ffmpeg", "-version"], cancel_event=ev))
    await asyncio.sleep(0.03)
    ev.set()
    code, _out, _err = await task

    assert proc.killed is True
    assert code == -9


@pytest.mark.asyncio
async def test_run_ffmpeg_with_progress_cancel_returns_minus_9(monkeypatch):
    proc = _FakeProc(complete_after=5.0)

    async def _fake_create(*_args, **_kwargs):
        return proc

    updates: list[float] = []

    async def _cb(pct: float, _label: str) -> None:
        updates.append(pct)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    ev = asyncio.Event()
    task = asyncio.create_task(
        fr.run_ffmpeg_with_progress(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "in.mp4", "out.mp4"],
            duration_sec=10.0,
            progress_cb=_cb,
            encode_label="enc",
            cancel_event=ev,
        )
    )
    await asyncio.sleep(0.05)
    ev.set()
    code, _out, _err = await task

    assert proc.killed is True
    assert code == -9
    # На отмене не должно приходить финальное 100%.
    assert not any(p >= 100.0 for p in updates)
