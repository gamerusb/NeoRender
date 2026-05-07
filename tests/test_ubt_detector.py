"""Тесты LLM-детектора UBT/арбитражного контента."""

from __future__ import annotations

import json

import pytest

from core import ubt_detector as ubt


# ── _parse_response ────────────────────────────────────────────────────────────

def test_parse_ubt_found():
    raw = json.dumps({
        "status": "UBT_FOUND",
        "niche": "гемблинг",
        "confidence": 87,
        "triggers": ["#cpa tag", "CTA: ссылка в шапке"],
        "download_url": "https://youtu.be/xxx",
    })
    out = ubt._parse_response(raw)
    assert out["status"] == "UBT_FOUND"
    assert out["niche"] == "гемблинг"
    assert out["confidence"] == 87
    assert len(out["triggers"]) == 2
    assert out["download_url"] == "https://youtu.be/xxx"


def test_parse_organic():
    raw = '{"status": "ORGANIC"}'
    out = ubt._parse_response(raw)
    assert out == {"status": "ORGANIC"}


def test_parse_fenced_json():
    raw = '```json\n{"status": "ORGANIC"}\n```'
    out = ubt._parse_response(raw)
    assert out["status"] == "ORGANIC"


def test_parse_invalid_falls_back_to_organic():
    assert ubt._parse_response("not json at all") == {"status": "ORGANIC"}
    assert ubt._parse_response("") == {"status": "ORGANIC"}
    assert ubt._parse_response("{}") == {"status": "ORGANIC"}


def test_parse_ubt_found_case_insensitive():
    raw = '{"status": "ubt_found", "niche": "крипта", "confidence": 80, "triggers": ["test"]}'
    out = ubt._parse_response(raw)
    assert out["status"] == "UBT_FOUND"


def test_parse_missing_fields_in_ubt():
    raw = '{"status": "UBT_FOUND"}'
    out = ubt._parse_response(raw)
    assert out["status"] == "UBT_FOUND"
    assert out["confidence"] == 0
    assert out["triggers"] == []
    assert out["niche"] == "unknown"


# ── _build_user_message ────────────────────────────────────────────────────────

def test_build_user_message_full():
    video = {
        "title": "Схема заработка",
        "description": "ссылка в шапке",
        "tags": ["#cpa", "#earn"],
        "ocr_text": "BONUS200",
        "transcript": "переходи в профиль",
        "pinned_comment": "t . me / channel",
        "url": "https://youtu.be/abc",
    }
    msg = ubt._build_user_message(video)
    data = json.loads(msg)
    assert data["title"] == "Схема заработка"
    assert data["tags"] == ["#cpa", "#earn"]
    assert data["ocr_text"] == "BONUS200"


def test_build_user_message_minimal():
    out = ubt._build_user_message({})
    data = json.loads(out)
    assert data["title"] == ""
    assert data["tags"] == []
    assert data["url"] == ""


def test_build_user_message_uses_webpage_url_fallback():
    video = {"webpage_url": "https://youtu.be/yyy"}
    data = json.loads(ubt._build_user_message(video))
    assert data["url"] == "https://youtu.be/yyy"


# ── classify_video (мок HTTP) ──────────────────────────────────────────────────

def _make_fake_session(response_body: dict, status: int = 200):
    """Фабрика мок-сессии aiohttp."""

    class FakeResp:
        def __init__(self):
            self.status = status

        async def read(self):
            return json.dumps(response_body).encode()

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

    return FakeClientSession


@pytest.mark.asyncio
async def test_classify_video_ubt_found(monkeypatch):
    llm_payload = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "status": "UBT_FOUND",
                    "niche": "гемблинг",
                    "confidence": 90,
                    "triggers": ["#cpa tag", "CTA в описании"],
                    "download_url": "https://youtu.be/test",
                })
            }
        }]
    }
    monkeypatch.setattr(ubt.aiohttp, "ClientSession", _make_fake_session(llm_payload))

    video = {"title": "Заработок без вложений", "description": "ссылка в шапке #cpa", "url": "https://youtu.be/test"}
    result = await ubt.classify_video(video, api_key="test-key")

    assert result["status"] == "UBT_FOUND"
    assert result["niche"] == "гемблинг"
    assert result["confidence"] == 90
    assert "CTA в описании" in result["triggers"]


@pytest.mark.asyncio
async def test_classify_video_organic(monkeypatch):
    llm_payload = {
        "choices": [{"message": {"content": '{"status": "ORGANIC"}'}}]
    }
    monkeypatch.setattr(ubt.aiohttp, "ClientSession", _make_fake_session(llm_payload))

    result = await ubt.classify_video({"title": "Котики"}, api_key="test-key")
    assert result["status"] == "ORGANIC"


@pytest.mark.asyncio
async def test_classify_video_no_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = await ubt.classify_video({"title": "test"}, api_key=None)
    assert result["status"] == "ERROR"
    assert "GROQ_API_KEY" in result["message"]


@pytest.mark.asyncio
async def test_classify_video_http_error(monkeypatch):
    error_payload = {"error": {"message": "Invalid API key"}}
    monkeypatch.setattr(ubt.aiohttp, "ClientSession", _make_fake_session(error_payload, status=401))

    result = await ubt.classify_video({"title": "test"}, api_key="bad-key")
    assert result["status"] == "ERROR"
    assert "401" in result["message"]


@pytest.mark.asyncio
async def test_classify_video_bad_json_response(monkeypatch):
    class BadResp:
        status = 200

        async def read(self):
            return b"not json at all"

    class BadPostCM:
        async def __aenter__(self):
            return BadResp()

        async def __aexit__(self, *a):
            return None

    class BadSession:
        def post(self, *a, **kw):
            return BadPostCM()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    class BadClientSession:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return BadSession()

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ubt.aiohttp, "ClientSession", BadClientSession)
    result = await ubt.classify_video({"title": "test"}, api_key="key")
    assert result["status"] == "ERROR"
    assert result["message"] == "bad_response"


# ── batch_classify ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_classify_returns_all(monkeypatch):
    call_count = 0

    async def fake_classify(video, api_key=None, model=None):
        nonlocal call_count
        call_count += 1
        return {"status": "ORGANIC"}

    monkeypatch.setattr(ubt, "classify_video", fake_classify)

    videos = [{"title": f"video {i}"} for i in range(5)]
    results = await ubt.batch_classify(videos, api_key="key", concurrency=2)

    assert len(results) == 5
    assert call_count == 5
    assert all(r["status"] == "ORGANIC" for r in results)


@pytest.mark.asyncio
async def test_batch_classify_attaches_video_id(monkeypatch):
    async def fake_classify(video, api_key=None, model=None):
        return {"status": "ORGANIC"}

    monkeypatch.setattr(ubt, "classify_video", fake_classify)

    videos = [{"id": "abc123", "title": "test"}]
    results = await ubt.batch_classify(videos, api_key="key")

    assert results[0]["_video_id"] == "abc123"


@pytest.mark.asyncio
async def test_batch_classify_mixed_results(monkeypatch):
    async def fake_classify(video, api_key=None, model=None):
        if "арбитраж" in (video.get("title") or ""):
            return {"status": "UBT_FOUND", "niche": "гемблинг", "confidence": 85, "triggers": [], "download_url": ""}
        return {"status": "ORGANIC"}

    monkeypatch.setattr(ubt, "classify_video", fake_classify)

    videos = [
        {"title": "арбитраж схема"},
        {"title": "котики милые"},
        {"title": "арбитраж casino"},
    ]
    results = await ubt.batch_classify(videos, api_key="key")
    ubt_count = sum(1 for r in results if r["status"] == "UBT_FOUND")
    assert ubt_count == 2
