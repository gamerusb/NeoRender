"""
Сохранение настроек в data/neo_settings.json — переживают перезапуск uvicorn.

Порядок загрузки при старте:
  1) .env в корне проекта (если есть python-dotenv)
  2) neo_settings.json поверх переменных окружения (пустой groq_api_key в JSON
     не сбрасывает GROQ_API_KEY из .env)
  3) снова .env с override=True — если в файле задан GROQ_API_KEY, он побеждает JSON

Не коммитьте neo_settings.json и .env с секретами (см. .gitignore).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import hashlib
import base64
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_FILE = ROOT / "data" / "neo_settings.json"
_MAX_SETTINGS_FILE_BYTES = 1_048_576  # 1 MB
_ENC_PREFIX = "enc:v1:"


def settings_file_path() -> Path:
    raw = (os.environ.get("NEORENDER_SETTINGS_PATH") or "").strip()
    return Path(raw).resolve() if raw else DEFAULT_SETTINGS_FILE


def load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path)
        logger.info("Загружен .env: %s", env_path)


def load_dotenv_override_if_present() -> None:
    """
    Загрузить .env поверх уже установленных переменных (override=True).

    Вызывать после apply_persisted_settings(), чтобы ключи из локального .env
    перекрывали устаревшие секреты из neo_settings.json (типичная причина 401 Groq).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=True)
        logger.info("Загружен .env с приоритетом над neo_settings: %s", env_path)


def _derive_local_secret_key() -> bytes:
    raw = (
        os.environ.get("NEORENDER_SETTINGS_KEY")
        or f"{socket.gethostname()}::{os.environ.get('USERNAME', '')}::neorender"
    ).encode("utf-8", errors="ignore")
    digest = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt(value: str) -> str:
    try:
        from cryptography.fernet import Fernet
        token = Fernet(_derive_local_secret_key()).encrypt(value.encode("utf-8"))
        return _ENC_PREFIX + token.decode("utf-8")
    except Exception:
        return value


def _decrypt(value: str) -> str:
    s = str(value or "")
    if not s.startswith(_ENC_PREFIX):
        return s
    token = s[len(_ENC_PREFIX):]
    try:
        from cryptography.fernet import Fernet
        plain = Fernet(_derive_local_secret_key()).decrypt(token.encode("utf-8"))
        return plain.decode("utf-8")
    except Exception:
        logger.warning("Не удалось расшифровать поле из neo_settings.json")
        return ""


def _mask_secret_fields(raw: dict[str, Any], *, decrypt: bool) -> dict[str, Any]:
    out = dict(raw)
    if "groq_api_key" in out and isinstance(out["groq_api_key"], str):
        out["groq_api_key"] = _decrypt(out["groq_api_key"]) if decrypt else _encrypt(out["groq_api_key"])

    ads = out.get("adspower")
    if isinstance(ads, dict) and isinstance(ads.get("api_key"), str):
        ads = dict(ads)
        ads["api_key"] = _decrypt(ads["api_key"]) if decrypt else _encrypt(ads["api_key"])
        out["adspower"] = ads

    tg = out.get("telegram")
    if isinstance(tg, dict) and isinstance(tg.get("bot_token"), str):
        tg = dict(tg)
        tg["bot_token"] = _decrypt(tg["bot_token"]) if decrypt else _encrypt(tg["bot_token"])
        out["telegram"] = tg
    return out


def apply_persisted_settings() -> None:
    path = settings_file_path()
    if not path.is_file():
        return
    try:
        if path.stat().st_size > _MAX_SETTINGS_FILE_BYTES:
            logger.warning("neo_settings.json слишком большой, загрузка отклонена: %s", path)
            return
    except OSError:
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("neo_settings.json не прочитан: %s", exc)
        return
    if not isinstance(raw, dict):
        return
    raw = _mask_secret_fields(raw, decrypt=True)

    if "groq_api_key" in raw:
        g = raw["groq_api_key"]
        if isinstance(g, str) and g.strip():
            os.environ["GROQ_API_KEY"] = g.strip()
        # Пустой groq в JSON не трогаем env: иначе затирается ключ из .env при старте.

    ads = raw.get("adspower")
    if isinstance(ads, dict):
        if "api_url" in ads:
            u = ads["api_url"]
            if isinstance(u, str) and u.strip():
                os.environ["ADSPOWER_API_URL"] = u.strip().rstrip("/")
            else:
                os.environ.pop("ADSPOWER_API_URL", None)
        if "api_key" in ads:
            k = ads["api_key"]
            if isinstance(k, str) and k.strip():
                os.environ["ADSPOWER_API_KEY"] = k.strip()
            else:
                os.environ.pop("ADSPOWER_API_KEY", None)
        if "use_auth" in ads:
            os.environ["ADSPOWER_USE_AUTH"] = "1" if bool(ads["use_auth"]) else "0"

    tg = raw.get("telegram")
    if isinstance(tg, dict):
        if "bot_token" in tg:
            t = tg["bot_token"]
            if isinstance(t, str) and t.strip():
                os.environ["TELEGRAM_BOT_TOKEN"] = t.strip()
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        if "chat_id" in tg:
            c = tg["chat_id"]
            if isinstance(c, str) and c.strip():
                os.environ["TELEGRAM_CHAT_ID"] = c.strip()
            else:
                os.environ.pop("TELEGRAM_CHAT_ID", None)

    if raw.get("neorender_disable_nvenc") is True:
        os.environ["NEORENDER_DISABLE_NVENC"] = "1"
    elif raw.get("neorender_disable_nvenc") is False:
        os.environ.pop("NEORENDER_DISABLE_NVENC", None)

    for _env_key, _json_key in (
        ("NEORENDER_AUDIO_LAME_ROUNDTRIP_P", "neorender_audio_lame_roundtrip_p"),
        ("NEORENDER_FONTS_DIR", "neorender_fonts_dir"),
        ("NEORENDER_SUBTITLE_EMOJI_FONT", "neorender_subtitle_emoji_font"),
        ("GROQ_MODEL", "groq_model"),
    ):
        if _json_key in raw:
            v = raw[_json_key]
            if isinstance(v, str) and v.strip():
                os.environ[_env_key] = v.strip()
            else:
                os.environ.pop(_env_key, None)

    logger.info("Применён neo_settings.json: %s", path)


def persist_current_settings(*, clear_groq: bool = False) -> None:
    """Снять снимок текущих env и записать в JSON.

    clear_groq=True — явно убрать ключ Groq из файла (кнопка очистки в UI).
    Иначе при пустом GROQ_API_KEY в env сохранённый в JSON ключ не затирается
    (чтобы сохранение Telegram/AdsPower/уникализатора не стирало Groq).
    """
    path = settings_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Читаем существующий файл, чтобы не стереть раздел uniqualizer.
        existing: dict[str, Any] = {}
        if path.is_file():
            try:
                if path.stat().st_size <= _MAX_SETTINGS_FILE_BYTES:
                    existing = json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, json.JSONDecodeError):
                pass
        existing_decrypted = (
            _mask_secret_fields(dict(existing), decrypt=True)
            if isinstance(existing, dict)
            else {}
        )
        groq_env = (os.environ.get("GROQ_API_KEY") or "").strip()
        if groq_env:
            groq_to_store = groq_env
        elif clear_groq:
            groq_to_store = ""
        else:
            prev = existing_decrypted.get("groq_api_key")
            groq_to_store = (prev or "").strip() if isinstance(prev, str) else ""

        data: dict[str, Any] = {
            **existing,
            "version": 1,
            "groq_api_key": groq_to_store,
            "telegram": {
                "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
            },
            "adspower": {
                "api_url": os.environ.get("ADSPOWER_API_URL", ""),
                "api_key": os.environ.get("ADSPOWER_API_KEY", ""),
                "use_auth": os.environ.get("ADSPOWER_USE_AUTH", "").strip().lower()
                in ("1", "true", "yes", "on"),
            },
            "neorender_disable_nvenc": os.environ.get("NEORENDER_DISABLE_NVENC", "")
            .strip()
            .lower()
            in ("1", "true", "yes", "on"),
            "neorender_audio_lame_roundtrip_p": os.environ.get("NEORENDER_AUDIO_LAME_ROUNDTRIP_P", ""),
            "neorender_fonts_dir": os.environ.get("NEORENDER_FONTS_DIR", ""),
            "neorender_subtitle_emoji_font": os.environ.get("NEORENDER_SUBTITLE_EMOJI_FONT", ""),
            "groq_model": os.environ.get("GROQ_MODEL", ""),
        }
        data = _mask_secret_fields(data, decrypt=False)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Настройки сохранены: %s", path)
    except OSError as exc:
        logger.warning("Не удалось записать neo_settings.json: %s", exc)


def save_uniqualizer_settings(settings: dict[str, Any]) -> None:
    """Сохранить рантайм-настройки уникализатора в neo_settings.json."""
    path = settings_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if path.is_file():
            try:
                if path.stat().st_size <= _MAX_SETTINGS_FILE_BYTES:
                    existing = json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, json.JSONDecodeError):
                pass
        # Фильтруем только известные ключи уникализатора; не пишем служебные поля.
        _UNIQUALIZER_KEYS = frozenset({
            "geo_enabled", "geo_profile", "geo_jitter", "device_model", "niche",
            "preset", "template", "subtitle", "subtitle_srt_path",
            "overlay_mode", "overlay_position", "subtitle_style", "subtitle_font",
            "subtitle_font_size", "overlay_media_path", "overlay_blend_mode",
            "overlay_opacity", "effects", "effect_levels", "uniqualize_intensity",
            "auto_trim_lead_tail", "perceptual_hash_check",
            "tags", "thumbnail_path",
        })
        clean = {k: v for k, v in settings.items() if k in _UNIQUALIZER_KEYS}
        existing["uniqualizer"] = clean
        existing = _mask_secret_fields(existing, decrypt=False)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Настройки уникализатора сохранены: %s", path)
    except OSError as exc:
        logger.warning("Не удалось сохранить настройки уникализатора: %s", exc)


def load_uniqualizer_settings() -> dict[str, Any] | None:
    """Загрузить сохранённые настройки уникализатора из neo_settings.json. None если нет."""
    path = settings_file_path()
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > _MAX_SETTINGS_FILE_BYTES:
            logger.warning("neo_settings.json слишком большой, загрузка настроек отключена: %s", path)
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = _mask_secret_fields(raw, decrypt=True)
        if isinstance(raw, dict) and isinstance(raw.get("uniqualizer"), dict):
            return raw["uniqualizer"]
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Не удалось прочитать настройки уникализатора: %s", exc)
    return None
