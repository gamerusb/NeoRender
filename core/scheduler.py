"""
Планировщик заливки NeoRender Pro.

Фоновый поллер опрашивает БД каждые POLL_INTERVAL секунд и ставит в очередь
задачи, у которых scheduled_at <= now(). Управляется через API:

  POST /api/tasks/{id}/schedule   — назначить время публикации
  DELETE /api/tasks/{id}/schedule — снять расписание (запустить немедленно)
  GET  /api/tasks/scheduled       — список задач в ожидании по расписанию

Планировщик стартует/стопает вместе с AutomationPipeline через:
  pipeline.scheduler.start()
  pipeline.scheduler.stop()
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

# Интервал опроса БД на предмет наступивших задач (секунд).
POLL_INTERVAL = 30.0

if TYPE_CHECKING:
    from .main_loop import AutomationPipeline


class TaskScheduler:
    """
    Фоновый поллер: каждые POLL_INTERVAL секунд проверяет наступившие
    scheduled_at и добавляет их в очередь AutomationPipeline.
    """

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
        self._task = asyncio.create_task(self._loop(), name="scheduler-poller")
        logger.info("TaskScheduler started (poll every %ss)", POLL_INTERVAL)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("TaskScheduler stopped")

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("scheduler tick error: %s", exc)
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=POLL_INTERVAL,
                )
                break  # stop_event сработал
            except asyncio.TimeoutError:
                pass  # нормальный тик

    async def _tick(self) -> None:
        """Найти наступившие задачи и поставить в очередь."""
        try:
            from . import database as dbmod
            from . import notifier
        except ImportError:
            import database as dbmod  # type: ignore
            import notifier  # type: ignore

        pipe = self._pipeline
        res = await dbmod.get_due_scheduled_tasks(pipe.tenant_id, pipe.db_path)
        if res.get("status") != "ok":
            return
        due = res.get("tasks") or []
        for row in due:
            tid = row.get("id")
            if tid is None:
                continue
            retry_count = int(row.get("retry_count") or 0)
            # Снимаем scheduled_at чтобы задача попала в обычный get_pending_tasks
            unschedule = await dbmod.schedule_task(tid, None, pipe.tenant_id, pipe.db_path)
            if unschedule.get("status") != "ok":
                logger.error(
                    "scheduler: failed to clear schedule for task %s: %s",
                    tid,
                    unschedule,
                )
                continue
            await pipe.enqueue(int(tid))
            if retry_count == 0:
                # Только пользовательское расписание — не спамим при авто-ретраях
                logger.info("scheduler: enqueued task %s (was scheduled at %s)", tid, row.get("scheduled_at"))
                await notifier.notify_scheduled_task_due(int(tid), pipe.tenant_id)
            else:
                logger.info(
                    "scheduler: retry enqueued task %s (attempt %d, was scheduled at %s)",
                    tid, retry_count, row.get("scheduled_at"),
                )
