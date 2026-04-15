"""Сохранение/загрузка neo_settings.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import persisted_config as pc


def test_apply_persisted_sets_groq_and_adspower(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "neo_settings.json"
    monkeypatch.setenv("NEORENDER_SETTINGS_PATH", str(cfg))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ADSPOWER_API_URL", raising=False)
    monkeypatch.delenv("ADSPOWER_API_KEY", raising=False)
    monkeypatch.delenv("ADSPOWER_USE_AUTH", raising=False)
    monkeypatch.delenv("NEORENDER_DISABLE_NVENC", raising=False)
    cfg.write_text(
        json.dumps(
            {
                "version": 1,
                "groq_api_key": "gsk_test_key",
                "adspower": {
                    "api_url": "http://127.0.0.1:59999",
                    "api_key": "ak",
                    "use_auth": True,
                },
                "neorender_disable_nvenc": True,
            }
        ),
        encoding="utf-8",
    )
    pc.apply_persisted_settings()
    assert os.environ.get("GROQ_API_KEY") == "gsk_test_key"
    assert os.environ.get("ADSPOWER_API_URL") == "http://127.0.0.1:59999"
    assert os.environ.get("ADSPOWER_API_KEY") == "ak"
    assert os.environ.get("ADSPOWER_USE_AUTH") == "1"
    assert os.environ.get("NEORENDER_DISABLE_NVENC") == "1"


def test_persist_current_roundtrip(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "neo_settings.json"
    monkeypatch.setenv("NEORENDER_SETTINGS_PATH", str(cfg))
    monkeypatch.setenv("GROQ_API_KEY", "saved_groq")
    monkeypatch.setenv("ADSPOWER_API_URL", "http://custom:50325")
    monkeypatch.setenv("ADSPOWER_API_KEY", "k2")
    monkeypatch.setenv("ADSPOWER_USE_AUTH", "0")
    monkeypatch.delenv("NEORENDER_DISABLE_NVENC", raising=False)
    pc.persist_current_settings()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    # Секреты должны храниться в зашифрованном виде.
    assert isinstance(data["groq_api_key"], str) and data["groq_api_key"].startswith("enc:v1:")
    assert data["adspower"]["api_url"] == "http://custom:50325"
    assert isinstance(data["adspower"]["api_key"], str) and data["adspower"]["api_key"].startswith("enc:v1:")
    assert data["adspower"]["use_auth"] is False
    assert data["neorender_disable_nvenc"] is False

    # И при применении должны корректно восстанавливаться в env.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ADSPOWER_API_KEY", raising=False)
    pc.apply_persisted_settings()
    assert os.environ.get("GROQ_API_KEY") == "saved_groq"
    assert os.environ.get("ADSPOWER_API_KEY") == "k2"


def test_apply_persisted_empty_groq_does_not_wipe_dotenv(monkeypatch, tmp_path: Path):
    """Пустой groq в neo_settings не должен удалять ключ, уже заданный в окружении (.env)."""
    cfg = tmp_path / "neo_settings.json"
    monkeypatch.setenv("NEORENDER_SETTINGS_PATH", str(cfg))
    monkeypatch.setenv("GROQ_API_KEY", "from_dotenv")
    cfg.write_text(
        json.dumps({"version": 1, "groq_api_key": ""}),
        encoding="utf-8",
    )
    pc.apply_persisted_settings()
    assert os.environ.get("GROQ_API_KEY") == "from_dotenv"


def test_persist_preserves_groq_when_env_empty(monkeypatch, tmp_path: Path):
    """Сохранение других настроек при пустом env не стирает Groq в JSON."""
    cfg = tmp_path / "neo_settings.json"
    monkeypatch.setenv("NEORENDER_SETTINGS_PATH", str(cfg))
    monkeypatch.setenv("GROQ_API_KEY", "keep_me")
    monkeypatch.setenv("ADSPOWER_API_URL", "http://127.0.0.1:50325")
    monkeypatch.setenv("ADSPOWER_API_KEY", "")
    monkeypatch.setenv("ADSPOWER_USE_AUTH", "0")
    pc.persist_current_settings()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    pc.persist_current_settings()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert isinstance(data["groq_api_key"], str) and data["groq_api_key"].startswith("enc:v1:")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    pc.apply_persisted_settings()
    assert os.environ.get("GROQ_API_KEY") == "keep_me"


def test_persist_keeps_arbitrage_monitor_section(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "neo_settings.json"
    monkeypatch.setenv("NEORENDER_SETTINGS_PATH", str(cfg))
    cfg.write_text(
        json.dumps(
            {
                "version": 1,
                "arbitrage_monitor": {
                    "alerts_enabled": True,
                    "score_threshold": 77,
                    "watchlist_channels": ["UCdemoChan"],
                },
            }
        ),
        encoding="utf-8",
    )
    pc.persist_current_settings()
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert "arbitrage_monitor" in saved
    assert saved["arbitrage_monitor"]["score_threshold"] == 77
