"""Доп. тесты youtube_automator: детекция верификации Google."""

from __future__ import annotations

import pytest

from core import youtube_automator as yt


class FakePage:
    def __init__(self, html: str):
        self._html = html

    async def content(self):
        return self._html


@pytest.mark.asyncio
async def test_detect_verification_positive():
    page = FakePage("<html>Please Verify it's you now</html>")
    assert await yt._detect_verification(page) is True


@pytest.mark.asyncio
async def test_detect_verification_negative():
    page = FakePage("<html>Normal YouTube</html>")
    assert await yt._detect_verification(page) is False
