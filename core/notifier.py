"""
Telegram-уведомления для NeoRender Pro.

Настройка (env или neo_settings.json):
  TELEGRAM_BOT_TOKEN  — токен бота от @BotFather
  TELEGRAM_CHAT_ID    — chat_id получателя (личка, группа, канал)

Все функции — fire-and-forget: сбой отправки пишется в лог, не поднимается
наружу и не ломает основной пайплайн.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"
_TIMEOUT = 15.0  # секунд


def _token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def _chat_id() -> str:
    return (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()


def is_configured() -> bool:
    """True если оба ключа заданы."""
    return bool(_token() and _chat_id())


async def _post(method: str, **kwargs: Any) -> bool:
    """HTTP POST к Bot API. Возвращает True при успехе."""
    token = _token()
    chat_id = _chat_id()
    if not token or not chat_id:
        return False
    url = f"{_API_BASE.format(token=token)}/{method}"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, **kwargs)
            if not r.is_success:
                logger.warning("Telegram %s: HTTP %s — %s", method, r.status_code, r.text[:200])
                return False
            data = r.json()
            if not data.get("ok"):
                logger.warning("Telegram %s not ok: %s", method, data)
                return False
            return True
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


async def send_text(text: str, parse_mode: str = "HTML") -> bool:
    """Отправить текстовое сообщение."""
    return await _post(
        "sendMessage",
        json={"chat_id": _chat_id(), "text": text[:4096], "parse_mode": parse_mode},
    )


async def send_photo(path: str | Path, caption: str = "") -> bool:
    """Отправить изображение с подписью (для скриншотов верификации)."""
    p = Path(path)
    if not p.is_file():
        logger.warning("send_photo: файл не найден: %s", path)
        return False
    try:
        import httpx
        token = _token()
        chat_id = _chat_id()
        if not token or not chat_id:
            return False
        url = f"{_API_BASE.format(token=token)}/sendPhoto"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            with open(p, "rb") as f:
                r = await client.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption[:1024]},
                    files={"photo": (p.name, f, "image/png")},
                )
            if not r.is_success:
                logger.warning("Telegram sendPhoto HTTP %s", r.status_code)
                return False
            return bool(r.json().get("ok"))
    except Exception as exc:
        logger.warning("send_photo failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Высокоуровневые уведомления пайплайна
# ---------------------------------------------------------------------------

async def notify_task_success(
    task_id: int,
    video_url: str | None = None,
    tenant_id: str = "default",
) -> None:
    """Задача завершена успешно."""
    if not is_configured():
        return
    url_line = f"\n🔗 <a href=\"{video_url}\">{video_url}</a>" if video_url else ""
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    text = (
        f"✅ <b>Задача #{task_id} — успех</b>{tenant_line}"
        f"{url_line}"
    )
    await send_text(text)


async def notify_task_error(
    task_id: int,
    error_message: str,
    screenshot_path: str | Path | None = None,
    tenant_id: str = "default",
) -> None:
    """Задача упала с ошибкой. Если есть скриншот верификации — шлём его."""
    if not is_configured():
        return
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    text = (
        f"❌ <b>Задача #{task_id} — ошибка</b>{tenant_line}\n"
        f"<code>{error_message[:800]}</code>"
    )
    if screenshot_path and Path(screenshot_path).is_file():
        # Скриншот верификации Google — самая важная нотификация
        caption = f"🔐 Требуется подтверждение Google (задача #{task_id})\n{error_message[:200]}"
        await send_photo(screenshot_path, caption=caption)
    else:
        await send_text(text)


async def notify_verification_required(
    screenshot_path: str | Path,
    task_id: int | None = None,
    tenant_id: str = "default",
) -> None:
    """Специальное уведомление: Google требует верификацию — скриншот сразу в чат."""
    if not is_configured():
        return
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    task_line = f" задача #{task_id}" if task_id is not None else ""
    caption = (
        f"🔐 <b>Google требует верификацию</b>{tenant_line}\n"
        f"Требуется ручное подтверждение{task_line}. "
        f"Откройте браузер AdsPower и подтвердите вход."
    )
    sent = await send_photo(screenshot_path, caption=caption)
    if not sent:
        # Fallback: текстом с путём к скриншоту
        await send_text(
            f"🔐 <b>Google верификация</b>{tenant_line}\n"
            f"Скриншот: <code>{screenshot_path}</code>"
        )


async def notify_queue_finished(
    total: int,
    success: int,
    errors: int,
    tenant_id: str = "default",
) -> None:
    """Вся очередь обработана."""
    if not is_configured():
        return
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    text = (
        f"🏁 <b>Очередь завершена</b>{tenant_line}\n"
        f"Всего: {total} | ✅ Успех: {success} | ❌ Ошибок: {errors}"
    )
    await send_text(text)


async def notify_scheduled_task_due(task_id: int, tenant_id: str = "default") -> None:
    """Запланированная задача стартовала по расписанию."""
    if not is_configured():
        return
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    await send_text(f"⏰ <b>Задача #{task_id} запущена по расписанию</b>{tenant_line}")


async def notify_shadowban_detected(
    profile_id: str,
    video_url: str | None = None,
    tenant_id: str = "default",
) -> None:
    """Shadowban detected on a channel/video."""
    if not is_configured():
        return
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    url_line = f"\n🔗 <a href=\"{video_url}\">{video_url}</a>" if video_url else ""
    text = (
        f"⚠️ <b>Shadowban detected</b>{tenant_line}\n"
        f"Профиль: <code>{profile_id}</code>{url_line}"
    )
    await send_text(text)


async def notify_proxy_failed(
    proxy_addr: str,
    profile_id: str | None = None,
    tenant_id: str = "default",
) -> None:
    """Proxy check failed."""
    if not is_configured():
        return
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    profile_line = f"\nПрофиль: <code>{profile_id}</code>" if profile_id else ""
    text = (
        f"🔴 <b>Прокси недоступен</b>{tenant_line}\n"
        f"<code>{proxy_addr}</code>{profile_line}"
    )
    await send_text(text)


async def notify_task_success_with_views(
    task_id: int,
    video_url: str,
    views: int,
    tenant_id: str = "default",
    views_threshold: int = 1000,
) -> None:
    """Task succeeded and video reached views_threshold — notify with metrics."""
    if not is_configured():
        return
    if views < views_threshold:
        return
    tenant_line = f" | tenant: <code>{tenant_id}</code>" if tenant_id != "default" else ""
    text = (
        f"🚀 <b>Задача #{task_id} — вирусный старт!</b>{tenant_line}\n"
        f"👁 Просмотры: <b>{views:,}</b>\n"
        f"🔗 <a href=\"{video_url}\">{video_url}</a>"
    )
    await send_text(text)
