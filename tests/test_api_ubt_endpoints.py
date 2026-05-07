"""
API-тесты для эндпоинтов UBT-классификации:
  POST /api/research/ubt-classify
  POST /api/research/ubt-batch
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from core import database as dbmod
from core import ubt_detector as ubt
from core.main_loop import AutomationPipeline


# ── Fixture ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(temp_db_path: Path, tiny_png: Path) -> TestClient:
    api_server._pipelines.clear()
    assert asyncio.run(dbmod.init_db(temp_db_path)).get("status") == "ok"
    api_server._pipelines["default"] = AutomationPipeline(
        db_path=temp_db_path,
        overlay_png=tiny_png,
        tenant_id="default",
    )
    return TestClient(api_server.app)


HEADERS = {"X-Tenant-ID": "default"}


# ── /api/research/ubt-classify ─────────────────────────────────────────────────

class TestUbtClassifyEndpoint:
    def test_returns_organic_when_classify_returns_organic(self, client: TestClient, monkeypatch):
        async def fake_classify(video, api_key=None, model=None):
            return {"status": "ORGANIC"}

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        r = client.post(
            "/api/research/ubt-classify",
            headers=HEADERS,
            json={"title": "Котики милые", "url": "https://youtu.be/abc"},
        )
        assert r.status_code == 200
        data = r.json()
        # _json_ok merges: {"status":"ok"}.update({"status":"ORGANIC"}) → "ORGANIC" wins
        assert data.get("status") == "ORGANIC"

    def test_returns_ubt_found(self, client: TestClient, monkeypatch):
        async def fake_classify(video, api_key=None, model=None):
            return {
                "status": "UBT_FOUND",
                "niche": "гемблинг",
                "confidence": 88,
                "triggers": ["#cpa", "CTA в описании"],
                "download_url": "https://youtu.be/xyz",
            }

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        r = client.post(
            "/api/research/ubt-classify",
            headers=HEADERS,
            json={"title": "Заработок казино", "description": "ссылка в шапке #cpa"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("niche") == "гемблинг" or data.get("status") == "ok"

    def test_empty_body_still_calls_classifier(self, client: TestClient, monkeypatch):
        called_with = {}

        async def fake_classify(video, api_key=None, model=None):
            called_with.update(video)
            return {"status": "ORGANIC"}

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        r = client.post("/api/research/ubt-classify", headers=HEADERS, json={})
        assert r.status_code == 200
        # classify_video был вызван с пустым dict
        assert called_with == {}

    def test_classifier_error_becomes_500_or_error_status(self, client: TestClient, monkeypatch):
        async def fake_classify(video, api_key=None, model=None):
            raise RuntimeError("LLM недоступен")

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        r = client.post(
            "/api/research/ubt-classify",
            headers=HEADERS,
            json={"title": "test"},
        )
        # Сервер должен поймать исключение и вернуть 500
        assert r.status_code == 500


# ── /api/research/ubt-batch ────────────────────────────────────────────────────

class TestUbtBatchEndpoint:
    def test_returns_results_for_each_video(self, client: TestClient, monkeypatch):
        call_count = 0

        async def fake_classify(video, api_key=None, model=None):
            nonlocal call_count
            call_count += 1
            return {"status": "ORGANIC"}

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        videos = [{"title": f"video {i}"} for i in range(3)]
        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"videos": videos},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("total") == 3
        assert len(data.get("results", [])) == 3
        assert data.get("ubt_found") == 0

    def test_counts_ubt_found_correctly(self, client: TestClient, monkeypatch):
        async def fake_classify(video, api_key=None, model=None):
            if "арбитраж" in (video.get("title") or ""):
                return {"status": "UBT_FOUND", "niche": "гемблинг", "confidence": 80, "triggers": []}
            return {"status": "ORGANIC"}

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        videos = [
            {"title": "арбитраж схема 1"},
            {"title": "котики"},
            {"title": "арбитраж схема 2"},
        ]
        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"videos": videos},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("ubt_found") == 2
        assert data.get("total") == 3

    def test_empty_videos_list_returns_400(self, client: TestClient, monkeypatch):
        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"videos": []},
        )
        assert r.status_code == 400

    def test_missing_videos_key_returns_400(self, client: TestClient, monkeypatch):
        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"concurrency": 2},
        )
        assert r.status_code == 400

    def test_concurrency_clamped_to_max_5(self, client: TestClient, monkeypatch):
        """concurrency > 5 должен быть зажат до 5 (не падать)."""
        call_count = 0

        async def fake_classify(video, api_key=None, model=None):
            nonlocal call_count
            call_count += 1
            return {"status": "ORGANIC"}

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        videos = [{"title": "test"}]
        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"videos": videos, "concurrency": 999},
        )
        assert r.status_code == 200
        assert call_count == 1

    def test_concurrency_clamped_to_min_1(self, client: TestClient, monkeypatch):
        async def fake_classify(video, api_key=None, model=None):
            return {"status": "ORGANIC"}

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"videos": [{"title": "test"}], "concurrency": 0},
        )
        assert r.status_code == 200

    def test_videos_not_a_list_returns_400(self, client: TestClient, monkeypatch):
        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"videos": "not a list"},
        )
        assert r.status_code == 400

    def test_batch_error_in_one_video_still_returns_200(self, client: TestClient, monkeypatch):
        """Ошибка одного классификатора не должна ронять весь батч."""
        call_count = 0

        async def fake_classify(video, api_key=None, model=None):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return {"status": "ERROR", "message": "timeout"}
            return {"status": "ORGANIC"}

        monkeypatch.setattr(ubt, "classify_video", fake_classify)

        videos = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
        r = client.post(
            "/api/research/ubt-batch",
            headers=HEADERS,
            json={"videos": videos},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("total") == 3
