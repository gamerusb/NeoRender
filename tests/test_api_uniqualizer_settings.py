"""
API-тесты для /api/uniqualizer/settings.

Критичный кейс: POST с частичным телом не должен сбрасывать остальные настройки пайплайна.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from core import database as dbmod
from core.main_loop import AutomationPipeline


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


def test_uniqualizer_settings_get_includes_options(client: TestClient):
    r = client.get("/api/uniqualizer/settings", headers={"X-Tenant-ID": "default"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert isinstance(data.get("available_presets"), dict)
    assert isinstance(data.get("available_templates"), dict)
    assert isinstance(data.get("available_overlay_blends"), dict)
    assert isinstance(data.get("available_geo_profiles"), dict)
    assert isinstance(data.get("available_device_models"), dict)
    assert data.get("available_device_models")
    assert isinstance(data.get("available_effects"), dict)
    assert isinstance(data.get("available_effect_levels"), dict)
    assert data.get("uniqualize_intensity") in ("low", "med", "high")
    assert isinstance(data.get("available_uniqualize_intensity"), dict)


def test_uniqualizer_settings_post_partial_does_not_reset_other_fields(client: TestClient):
    # Ставим нестандартные значения в пайплайн, чтобы словить «сброс на дефолты».
    pipe = api_server._pipelines["default"]
    pipe.preset = "soft"  # не дефолт (deep)
    pipe.template = "story"  # не дефолт (default)
    pipe.geo_profile = "busan"
    pipe.overlay_opacity = 1.0

    r = client.post(
        "/api/uniqualizer/settings",
        headers={"X-Tenant-ID": "default"},
        json={"overlay_opacity": 0.55},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert abs(float(data.get("overlay_opacity")) - 0.55) < 1e-6
    # Ключевое: preset/template не должны измениться от частичного POST.
    assert data.get("preset") == "soft"
    assert data.get("template") == "story"


def test_uniqualizer_settings_post_validates_overlay_mode_alias(client: TestClient):
    r = client.post(
        "/api/uniqualizer/settings",
        headers={"X-Tenant-ID": "default"},
        json={"overlay_mode": "behind"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    # alias behind => under_video
    assert data.get("overlay_mode") == "under_video"


def test_uniqualizer_settings_post_effects_roundtrip(client: TestClient):
    r = client.post(
        "/api/uniqualizer/settings",
        headers={"X-Tenant-ID": "default"},
        json={
            "effects": {
                "mirror": True,
                "noise": False,
                "speed": True,
                "crop_reframe": True,
                "gamma_jitter": True,
                "audio_tone": True,
                "unknown": True,
            },
            "effect_levels": {
                "crop_reframe": "high",
                "gamma_jitter": "low",
                "audio_tone": "med",
                "unknown": "high",
                "mirror": "high",
                "bad_value": "extreme",
            },
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    eff = data.get("effects") or {}
    # неизвестные ключи должны быть отфильтрованы
    assert eff.get("mirror") is True
    assert eff.get("speed") is True
    assert eff.get("crop_reframe") is True
    assert eff.get("gamma_jitter") is True
    assert eff.get("audio_tone") is True
    assert "unknown" not in eff
    levels = data.get("effect_levels") or {}
    assert levels.get("crop_reframe") == "high"
    assert levels.get("gamma_jitter") == "low"
    assert levels.get("audio_tone") == "med"
    assert "unknown" not in levels
    assert "mirror" not in levels

