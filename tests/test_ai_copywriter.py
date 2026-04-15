"""Тесты Groq-копирайтера: мок HTTP, fallback без ключа."""

from __future__ import annotations

import json

import pytest

from core import ai_copywriter as ac


def test_parse_llm_json_clean():
    raw = (
        '{"title": "T", "description": "D #a #b #c", "comment": "C", '
        '"overlay_text": "화면 텍스트"}'
    )
    assert ac._parse_llm_json(raw) == {
        "title": "T",
        "description": "D #a #b #c",
        "comment": "C",
        "overlay_text": "화면 텍스트",
    }


def test_parse_llm_json_derives_overlay_from_title():
    raw = '{"title": "Only Title", "description": "D #a #b #c", "comment": "C"}'
    out = ac._parse_llm_json(raw)
    assert out["overlay_text"] == "Only Title"


def test_parse_llm_json_fenced():
    raw = '```json\n{"title": "A", "description": "B", "comment": "C"}\n```'
    out = ac._parse_llm_json(raw)
    assert out["title"] == "A"


def test_parse_llm_json_invalid():
    assert ac._parse_llm_json("not json") is None
    assert ac._parse_llm_json('{"title": "x"}') is None


@pytest.mark.asyncio
async def test_ping_groq_empty_key():
    r = await ac.ping_groq_api("")
    assert r["live"] is False
    assert "не задан" in r["message"].lower()


@pytest.mark.asyncio
async def test_generate_metadata_no_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = await ac.generate_metadata(None, "casino")
    assert r["status"] == "ok"
    assert "title" in r and "description" in r and "comment" in r and "overlay_text" in r
    assert r.get("used_fallback") is True


@pytest.mark.asyncio
async def test_generate_metadata_no_key_uses_fallback():
    """Без ключа generate_metadata возвращает fallback (not error)."""
    r = await ac.generate_metadata(None, "x")
    assert r.get("used_fallback") is True
    assert "title" in r


@pytest.mark.asyncio
async def test_generate_metadata_groq_success(monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "title": "한글 제목",
                            "description": "설명. #a #b #c",
                            "comment": "댓글",
                            "overlay_text": "짧은 캡션",
                        }
                    )
                }
            }
        ]
    }

    class FakeResp:
        status = 200

        async def read(self):
            return json.dumps(payload).encode()

    class FakePostCM:
        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *a):
            return None

    class FakeSession:
        def post(self, url, headers=None, json=None):
            return FakePostCM()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    class FakeClientSession:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ac.aiohttp, "ClientSession", FakeClientSession)

    r = await ac.generate_metadata("test-key", "niche")
    assert r["status"] == "ok"
    assert r["title"] == "한글 제목"
    assert r["overlay_text"] == "짧은 캡션"
    assert r.get("used_fallback") is False
