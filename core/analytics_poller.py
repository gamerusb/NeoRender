"""
Фоновый поллер аналитики NeoRender Pro.

Каждые POLL_INTERVAL секунд (по умолчанию 6 ч) проверяет все active-видео
из таблицы analytics через analytics_scraper.check_video и обновляет:
  - views, likes — свежие данные
  - status       — active / shadowban / banned
При смене статуса на shadowban/banned шлёт Telegram-уведомление.

Управление: AnalyticsPoller.start() / .stop() — вместе с AutomationPipeline.
Переопределение интервала: NEORENDER_ANALYTICS_POLL_INTERVAL_SEC=3600
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 6 * 3600.0  # 6 часов
_DEFAULT_PER_VIDEO_DELAY = 2.0
_DEFAULT_CONCURRENCY = 5


def _poll_interval() -> float:
    raw = (os.environ.get("NEORENDER_ANALYTICS_POLL_INTERVAL_SEC") or "").strip()
    try:
        v = float(raw)
        return v if v >= 60 else _DEFAULT_INTERVAL
    except (ValueError, TypeError):
        return _DEFAULT_INTERVAL


def _per_video_delay() -> float:
    raw = (os.environ.get("NEORENDER_ANALYTICS_PER_VIDEO_DELAY_SEC") or "").strip()
    try:
        v = float(raw)
        return v if v >= 0 else _DEFAULT_PER_VIDEO_DELAY
    except (ValueError, TypeError):
        return _DEFAULT_PER_VIDEO_DELAY


def _concurrency() -> int:
    raw = (os.environ.get("NEORENDER_ANALYTICS_CONCURRENCY") or "").strip()
    try:
        v = int(raw)
        return max(1, min(v, 20))
    except (ValueError, TypeError):
        return _DEFAULT_CONCURRENCY


if TYPE_CHECKING:
    from .main_loop import AutomationPipeline


class AnalyticsPoller:
    """Фоновый воркер автоматической проверки аналитики."""

    def __init__(self, pipeline: "AutomationPipeline") -> None:
        self._pipeline = pipeline
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="analytics-poller")
        logger.info("AnalyticsPoller started (interval %.0fs)", _poll_interval())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("AnalyticsPoller stopped")

    async def _loop(self) -> None:
        # Первый прогон — сразу при старте (через 30 сек, чтобы дать БД подняться).
        try:
            await asyncio.wait_for(
                asyncio.shield(self._stop_event.wait()),
                timeout=30.0,
            )
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("analytics poller tick: %s", exc)
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=_poll_interval(),
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        try:
            from . import database as dbmod
            from . import analytics_scraper
            from . import notifier
        except ImportError:
            import database as dbmod  # type: ignore
            import analytics_scraper  # type: ignore
            import notifier  # type: ignore

        pipe = self._pipeline
        res = await dbmod.list_active_analytics(pipe.tenant_id, pipe.db_path)
        if res.get("status") != "ok":
            return
        items = res.get("analytics") or []
        if not items:
            return

        logger.info("analytics poller: checking %d active videos", len(items))
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=25, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            sem = asyncio.Semaphore(_concurrency())

            async def _check_one(row: dict[str, Any]) -> None:
                if self._stop_event.is_set():
                    return
                url = row.get("video_url") or ""
                if not url:
                    return
                async with sem:
                    try:
                        result = await analytics_scraper.check_video(
                            url,
                            published_at=row.get("published_at"),
                            session=session,
                        )
                    except Exception as exc:
                        logger.warning("analytics poller check_video %s: %s", url[:60], exc)
                        return
                    finally:
                        await asyncio.sleep(_per_video_delay())

                if result.get("status") == "error":
                    return

                new_status = str(result.get("status") or "active")
                new_views = int(result.get("views") or row.get("views") or 0)
                old_status = str(row.get("status") or "active")

                await dbmod.upsert_analytics(
                    url,
                    views=new_views,
                    likes=int(row.get("likes") or 0),
                    status=new_status if new_status in ("active", "shadowban", "banned") else "active",
                    tenant_id=pipe.tenant_id,
                    db_path=pipe.db_path,
                )

                if new_status != old_status and new_status in ("shadowban", "banned"):
                    icon = "🚫" if new_status == "banned" else "⚠️"
                    label = "заблокировано" if new_status == "banned" else "shadowban"
                    logger.warning("analytics poller: %s → %s (%s)", url[:60], new_status, label)
                    await notifier.send_text(
                        f"{icon} <b>Видео {label}</b>\n"
                        f"<a href=\"{url}\">{url[:80]}</a>\n"
                        f"Просмотров: {new_views}"
                    )

            await asyncio.gather(*(_check_one(r) for r in items), return_exceptions=True)

        logger.info("analytics poller: tick done")
