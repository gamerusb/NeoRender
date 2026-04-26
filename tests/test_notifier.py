from __future__ import annotations

import types

import pytest

from core import notifier


class _Resp:
    def __init__(self, *, ok: bool = True) -> None:
        self.is_success = ok
        self.status_code = 200 if ok else 500
        self.text = "error"

    def json(self):
        return {"ok": self.is_success}


class _Client:
    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Resp(ok=True)


@pytest.mark.asyncio
async def test_send_text_returns_false_without_env(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert await notifier.send_text("hello") is False


@pytest.mark.asyncio
async def test_send_text_success_with_mocked_httpx(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    fake_httpx = types.SimpleNamespace(AsyncClient=_Client)
    monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)

    assert await notifier.send_text("ok message") is True


@pytest.mark.asyncio
async def test_notify_task_success_with_views_respects_threshold(monkeypatch) -> None:
    sent = []

    async def _fake_send(text: str, parse_mode: str = "HTML") -> bool:
        sent.append((text, parse_mode))
        return True

    monkeypatch.setattr(notifier, "is_configured", lambda: True)
    monkeypatch.setattr(notifier, "send_text", _fake_send)

    await notifier.notify_task_success_with_views(1, "https://x", 999, views_threshold=1000)
    assert sent == []

    await notifier.notify_task_success_with_views(1, "https://x", 1500, views_threshold=1000)
    assert len(sent) == 1
