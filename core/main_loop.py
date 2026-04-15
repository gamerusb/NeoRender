"""
Центральный оркестратор NeoRender Pro: очередь asyncio и полный пайплайн задачи.

Одна задача упала — записали в БД, безопасно остановили профиль AdsPower,
следующая в очереди продолжается. Очередь не «умирает» от единичной ошибки.
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from pathlib import Path
from typing import Any

try:
    from core import adspower_sync
    from core import ai_copywriter
    from core import database as dbmod
    from core import luxury_engine
    from core import notifier
    from core import srt_paths
    from core import storage as storage_mod
    from core import youtube_automator
    from core import ai_dubber
    from core import subtitle_generator
    from core.hot_folder import HotFolder
except ImportError:  # запуск из папки core
    import adspower_sync  # type: ignore
    import ai_copywriter  # type: ignore
    import database as dbmod  # type: ignore
    import luxury_engine  # type: ignore
    import notifier  # type: ignore
    import srt_paths  # type: ignore
    import storage as storage_mod  # type: ignore
    import youtube_automator  # type: ignore
    import ai_dubber  # type: ignore
    import subtitle_generator  # type: ignore
    from hot_folder import HotFolder  # type: ignore

logger = logging.getLogger(__name__)

# Пути по умолчанию для рендера (PNG можно положить в data/overlay.png).
_DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"
_DEFAULT_OVERLAY = _DEFAULT_DATA / "overlay.png"
_DEFAULT_RENDER_DIR = _DEFAULT_DATA / "rendered"


def _render_task_timeout_sec() -> float | None:
    raw = os.environ.get("NEORENDER_RENDER_TASK_TIMEOUT_SEC")
    if raw is None:
        return 1800.0  # 30 мин
    s = str(raw).strip().lower()
    if s in ("0", "", "none", "off", "inf"):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return 1800.0


def _short_err(exc: BaseException) -> str:
    """Краткое сообщение для поля error_message в БД (без traceback)."""
    msg = str(exc).strip()
    if len(msg) > 400:
        msg = msg[:397] + "..."
    return msg or "Неизвестная ошибка"


# ── Retry-логика ─────────────────────────────────────────────────────────────

# Задержки между попытками (секунды): 1-я ретрай, 2-я, 3-я и далее.
_RETRY_DELAYS: list[int] = [60, 120, 300]
_MAX_RETRIES_DEFAULT = 3


def _max_retries() -> int:
    """Максимум авто-ретраев (env NEORENDER_MAX_RETRIES, default 3). 0 = выключено."""
    raw = (os.environ.get("NEORENDER_MAX_RETRIES") or "").strip()
    try:
        return max(0, int(raw))
    except (ValueError, TypeError):
        return _MAX_RETRIES_DEFAULT


def _is_retryable_error(error_type: str | None, error_message: str) -> bool:
    """
    Retryable: ошибки AdsPower и загрузки на YouTube (сетевые, временные сбои).
    Non-retryable: конфигурационные ошибки, рендер, Google-верификация, отмена.
    """
    retryable_types = {
        "adspower",
        "upload",
        "publish_timeout",
        "publish_click_failed",
        "title_timeout",
    }
    if error_type not in retryable_types:
        return False
    # Верификация Google требует ручного действия — retry бесполезен.
    msg_lower = error_message.lower()
    if "верификац" in msg_lower or "verify" in msg_lower:
        return False
    return True


class AutomationPipeline:
    """
    Очередь идентификаторов задач (int). Воркеры забирают task_id и гоняют пайплайн.

    Параметры:
      db_path — путь к SQLite (как в database.py).
      overlay_png — путь к слою (картинка или видео) для luxury_engine.
      render_dir — куда складывать уникальные mp4.
      groq_api_key — ключ Groq для копирайтера (или env GROQ_API_KEY).
      niche — ниша для AI (корейские тексты).
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        overlay_png: str | Path | None = None,
        render_dir: str | Path | None = None,
        groq_api_key: str | None = None,
        niche: str = "YouTube Shorts",
        num_workers: int | None = None,
        tenant_id: str | None = None,
    ) -> None:
        from .tenancy import normalize_tenant_id

        self.tenant_id = normalize_tenant_id(tenant_id)
        if num_workers is None:
            _env = (os.environ.get("NEORENDER_WORKERS") or "").strip()
            try:
                num_workers = max(1, int(_env)) if _env else 1
            except ValueError:
                num_workers = 1
        self.db_path = db_path
        self.overlay_media_path = Path(overlay_png) if overlay_png else _DEFAULT_OVERLAY
        # render_dir оставлен для обратной совместимости; фактический путь — storage per tenant
        self.render_dir = Path(render_dir) if render_dir else _DEFAULT_RENDER_DIR
        self.groq_api_key = groq_api_key
        self.niche = niche
        self.geo_enabled = True
        self.geo_profile = "busan"
        self.geo_jitter = 0.05
        self.device_model = "Samsung SM-S928N"
        self.preset = "deep"
        self.template = "default"
        self.subtitle = ""
        self.subtitle_srt_path: str | None = None
        self.overlay_mode = "on_top"
        self.overlay_position = "center"
        self.subtitle_style = "default"
        self.subtitle_font: str = ""
        self.subtitle_font_size: int = 0  # 0 = auto (template default)
        self.overlay_blend_mode = "normal"
        self.overlay_opacity = 1.0
        # Дополнительные эффекты (поверх пресета/шаблона). Ключ -> bool.
        self.effects: dict[str, bool] = {}
        # Уровни интенсивности эффектов (low/med/high), по ключам эффекта.
        self.effect_levels: dict[str, str] = {}
        # Хэштеги для описания YouTube (список строк без #).
        self.tags: list[str] = []
        # Путь к кастомному thumbnail (PNG/JPG).
        self.thumbnail_path: str | None = None
        _env_uq = (os.environ.get("NEORENDER_UNIQUIZE_INTENSITY") or "").strip().lower()
        self.uniqualize_intensity = (
            _env_uq if _env_uq in ("low", "med", "high") else "med"
        )
        _env_trim = (os.environ.get("NEORENDER_AUTO_TRIM") or "").strip().lower()
        self.auto_trim_lead_tail: bool = _env_trim not in ("0", "false", "no", "off")
        _env_phash = (os.environ.get("NEORENDER_PERCEPTUAL_HASH_CHECK") or "").strip().lower()
        self.perceptual_hash_check: bool = _env_phash not in ("0", "false", "no", "off")
        
        # Настройки авто-субтитров/дубляжа
        self.auto_subtitles: bool = (os.environ.get("NEORENDER_AUTO_SUBTITLES", "").lower() in ("1", "true", "yes", "on"))
        self.auto_dubbing: bool = (os.environ.get("NEORENDER_AUTO_DUBBING", "").lower() in ("1", "true", "yes", "on"))
        self.hot_folder_inbox: str = (os.environ.get("NEORENDER_HOT_FOLDER_INBOX") or "").strip()
        self.hot_folder_profile: str = (os.environ.get("NEORENDER_HOT_FOLDER_PROFILE") or "").strip()
        self.hot_folder_render_only: bool = (
            (os.environ.get("NEORENDER_HOT_FOLDER_RENDER_ONLY") or "").strip().lower()
            in ("1", "true", "yes", "on")
        )

        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._stop = asyncio.Event()
        self._workers: list[asyncio.Task[Any]] = []
        self._num_workers = max(1, num_workers)
        self._started = False
        self._current_task_id: int | None = None  # последняя активная задача (для диагностики)
        self._task_cancel_event: asyncio.Event | None = None  # compat: ссылка на событие последней задачи
        # Словарь активных задач: task_id → cancel_event (корректен при num_workers > 1).
        self._active_tasks: dict[int, asyncio.Event] = {}
        # Мьютексы по профилю: гарантируют, что один профиль AdsPower не откроется
        # одновременно двумя воркерами при NEORENDER_WORKERS > 1.
        self._profile_locks: dict[str, asyncio.Lock] = {}
        self._encode_progress: dict[str, Any] = {
            "active": False,
            "task_id": None,
            "percent": 0.0,
            "label": "",
        }
        self._metrics: dict[str, int] = {
            "tasks_processed": 0,
            "tasks_success": 0,
            "tasks_error": 0,
            "tasks_retried": 0,
            "uploads_failed": 0,
            "adspower_failed": 0,
            "render_failed": 0,
        }
        # Планировщик заливки по времени.
        try:
            from .scheduler import TaskScheduler
            from .analytics_poller import AnalyticsPoller
        except ImportError:
            from scheduler import TaskScheduler  # type: ignore
            from analytics_poller import AnalyticsPoller  # type: ignore
        self.scheduler = TaskScheduler(self)
        self.analytics_poller = AnalyticsPoller(self)
        self.hot_folder = HotFolder(self)

    async def start(self) -> dict[str, Any]:
        """Инициализация БД и запуск фоновых воркеров."""
        try:
            init = await dbmod.init_db(self.db_path)
            if init.get("status") != "ok":
                return init
            rec = await dbmod.recover_interrupted_tasks(self.tenant_id, self.db_path)
            if rec.get("status") != "ok":
                logger.warning("start: recover_interrupted_tasks failed: %s", rec)
            elif int(rec.get("recovered") or 0) > 0:
                logger.warning(
                    "start: recovered %s interrupted tasks back to pending",
                    int(rec.get("recovered") or 0),
                )

            if self._started:
                # Восстанавливаем runtime-очередь из БД (после рестартов UI/сервера).
                enq = await self.enqueue_pending_from_db()
                return {
                    "status": "ok",
                    "message": "Пайплайн уже запущен.",
                    "enqueued_pending": int(enq.get("enqueued") or 0) if enq.get("status") == "ok" else 0,
                }

            self._stop.clear()
            self._started = True
            for i in range(self._num_workers):
                t = asyncio.create_task(self._worker_loop(worker_id=i), name=f"pipeline-worker-{i}")
                self._workers.append(t)
            await self.scheduler.start()
            await self.analytics_poller.start()
            await self.hot_folder.start()
            enq = await self.enqueue_pending_from_db()
            return {
                "status": "ok",
                "workers": self._num_workers,
                "enqueued_pending": int(enq.get("enqueued") or 0) if enq.get("status") == "ok" else 0,
            }
        except Exception as exc:
            logger.exception("AutomationPipeline.start: %s", exc)
            return {"status": "error", "message": "Не удалось запустить обработку задач."}

    async def stop(self) -> dict[str, Any]:
        """Мягкая остановка: воркеры завершат текущую задачу и выйдут."""
        try:
            await self.scheduler.stop()
            await self.analytics_poller.stop()
            await self.hot_folder.stop()
            self._stop.set()
            for t in self._workers:
                t.cancel()
            if self._workers:
                await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
            self._started = False
            return {"status": "ok"}
        except Exception as exc:
            logger.exception("AutomationPipeline.stop: %s", exc)
            return {"status": "error", "message": "Ошибка при остановке пайплайна."}

    async def enqueue(self, task_id: int) -> None:
        """Поставить задачу в очередь (оркестратор сам подхватит)."""
        await self.queue.put(int(task_id))

    async def enqueue_pending_from_db(self) -> dict[str, Any]:
        """Добавить в очередь все задачи со статусом pending из БД."""
        try:
            res = await dbmod.get_pending_tasks(self.tenant_id, self.db_path)
            if res.get("status") != "ok":
                return res
            tasks = res.get("tasks") or []
            for t in tasks:
                tid = t.get("id")
                if tid is not None:
                    await self.enqueue(int(tid))
            return {"status": "ok", "enqueued": len(tasks)}
        except Exception as exc:
            logger.exception("enqueue_pending_from_db: %s", exc)
            return {"status": "error", "message": "Не удалось загрузить очередь из базы."}

    def _clear_encode_progress(self) -> None:
        self._encode_progress = {
            "active": False,
            "task_id": None,
            "percent": 0.0,
            "label": "",
        }

    def get_encode_progress_snapshot(self) -> dict[str, Any]:
        return dict(self._encode_progress)

    def get_metrics_snapshot(self) -> dict[str, int]:
        return dict(self._metrics)

    def cancel_task_request(self, task_id: int) -> bool:
        """Сигнал отмены для задачи воркера. Работает корректно при num_workers > 1."""
        try:
            tid = int(task_id)
        except (TypeError, ValueError):
            return False
        ev = self._active_tasks.get(tid)
        if ev is not None:
            ev.set()
            return True
        return False

    def _task_cancelled(self, cancel_event: asyncio.Event | None = None) -> bool:
        ev = cancel_event if cancel_event is not None else self._task_cancel_event
        return ev is not None and ev.is_set()

    async def _fail_task_cancelled(self, task_id: int, unique_path: str | None = None) -> None:
        msg = "Отменено пользователем"
        if unique_path:
            try:
                Path(unique_path).unlink(missing_ok=True)
            except OSError:
                pass
        await dbmod.update_task_status(
            task_id,
            "error",
            error_message=msg,
            tenant_id=self.tenant_id,
            db_path=self.db_path,
        )

    def is_running(self) -> bool:
        """Воркеры пайплайна запущены (очередь обрабатывается)."""
        return self._started

    def update_uniqualizer_settings(
        self,
        *,
        geo_enabled: bool | None = None,
        geo_profile: str | None = None,
        geo_jitter: float | None = None,
        device_model: str | None = None,
        niche: str | None = None,
        preset: str | None = None,
        template: str | None = None,
        subtitle: str | None = None,
        subtitle_srt_path: str | None = None,
        overlay_mode: str | None = None,
        overlay_position: str | None = None,
        subtitle_style: str | None = None,
        subtitle_font: str | None = None,
        subtitle_font_size: int | None = None,
        overlay_media_path: str | None = None,
        overlay_blend_mode: str | None = None,
        overlay_opacity: float | None = None,
        effects: dict[str, bool] | None = None,
        effect_levels: dict[str, str] | None = None,
        uniqualize_intensity: str | None = None,
        auto_trim_lead_tail: bool | None = None,
        perceptual_hash_check: bool | None = None,
        tags: list[str] | None = None,
        thumbnail_path: str | None = None,
    ) -> dict[str, Any]:
        """Обновить runtime-настройки рендера для текущего tenant."""
        try:
            if geo_enabled is not None:
                self.geo_enabled = bool(geo_enabled)
            if geo_profile is not None:
                self.geo_profile = str(geo_profile).strip().lower() or "busan"
            if geo_jitter is not None:
                self.geo_jitter = max(0.01, min(0.5, float(geo_jitter)))
            if device_model is not None:
                self.device_model = str(device_model).strip() or "Samsung SM-S928N"
            if niche is not None:
                self.niche = str(niche).strip() or "YouTube Shorts"
            if preset is not None:
                from .luxury_engine import _normalize_preset
                self.preset = _normalize_preset(preset)
            if template is not None:
                from .luxury_engine import _normalize_template
                self.template = _normalize_template(template)
            if subtitle is not None:
                self.subtitle = str(subtitle)[:5000]
            if subtitle_srt_path is not None:
                from .srt_paths import validate_srt_path_for_tenant

                raw = str(subtitle_srt_path).strip()
                if not raw:
                    self.subtitle_srt_path = None
                else:
                    ok = validate_srt_path_for_tenant(raw, self.tenant_id)
                    self.subtitle_srt_path = ok
            if overlay_mode is not None:
                from .luxury_engine import _normalize_overlay_mode

                self.overlay_mode = _normalize_overlay_mode(overlay_mode)
            if overlay_position is not None:
                from .luxury_engine import _normalize_overlay_position

                self.overlay_position = _normalize_overlay_position(overlay_position)
            if subtitle_style is not None:
                from .luxury_engine import _normalize_subtitle_style

                self.subtitle_style = _normalize_subtitle_style(subtitle_style)
            if subtitle_font is not None:
                self.subtitle_font = str(subtitle_font).strip()[:128]
            if subtitle_font_size is not None:
                self.subtitle_font_size = max(0, min(200, int(subtitle_font_size)))
            if overlay_media_path is not None:
                from .overlay_paths import validate_overlay_media_path

                raw = str(overlay_media_path).strip()
                if not raw:
                    self.overlay_media_path = _DEFAULT_OVERLAY
                else:
                    ok = validate_overlay_media_path(raw, self.tenant_id)
                    if ok:
                        self.overlay_media_path = Path(ok)
                    else:
                        logger.warning(
                            "update_uniqualizer_settings: путь к слою вне uploads или неверный тип: %s",
                            raw,
                        )
            if overlay_blend_mode is not None:
                from .luxury_engine import _normalize_overlay_blend

                self.overlay_blend_mode = _normalize_overlay_blend(overlay_blend_mode)
            if overlay_opacity is not None:
                self.overlay_opacity = max(0.0, min(1.0, float(overlay_opacity)))
            if effects is not None:
                # Только известные ключи; неизвестные игнорируем.
                allow = {"mirror", "noise", "speed", "crop_reframe", "gamma_jitter", "audio_tone"}
                cleaned: dict[str, bool] = {}
                if isinstance(effects, dict):
                    for k, v in effects.items():
                        kk = str(k).strip().lower().replace("-", "_")
                        if kk in allow:
                            cleaned[kk] = bool(v)
                self.effects = cleaned
            if effect_levels is not None:
                allow = {"crop_reframe", "gamma_jitter", "audio_tone"}
                lvl_allow = {"low", "med", "high"}
                cleaned_levels: dict[str, str] = {}
                if isinstance(effect_levels, dict):
                    for k, v in effect_levels.items():
                        kk = str(k).strip().lower().replace("-", "_")
                        vv = str(v).strip().lower()
                        if kk in allow and vv in lvl_allow:
                            cleaned_levels[kk] = vv
                self.effect_levels = cleaned_levels
            if uniqualize_intensity is not None:
                from .luxury_engine import _normalize_uniqualize_intensity

                self.uniqualize_intensity = _normalize_uniqualize_intensity(
                    uniqualize_intensity
                )
            if auto_trim_lead_tail is not None:
                self.auto_trim_lead_tail = bool(auto_trim_lead_tail)
            if perceptual_hash_check is not None:
                self.perceptual_hash_check = bool(perceptual_hash_check)
            if tags is not None:
                if isinstance(tags, list):
                    self.tags = [str(t).strip().lstrip("#") for t in tags if str(t).strip()][:30]
                else:
                    self.tags = []
            if thumbnail_path is not None:
                raw_thumb = str(thumbnail_path).strip()
                if not raw_thumb:
                    self.thumbnail_path = None
                else:
                    from pathlib import Path as _Path
                    tp = _Path(raw_thumb)
                    self.thumbnail_path = str(tp.resolve()) if tp.is_file() else None
                    if not self.thumbnail_path:
                        logger.warning("update_uniqualizer_settings: thumbnail не найден: %s", raw_thumb)
            
            # Если в UI добавят чекбоксы, можно будет передавать их сюда
            # if auto_subtitles is not None: self.auto_subtitles = bool(auto_subtitles)
            # if auto_dubbing is not None: self.auto_dubbing = bool(auto_dubbing)
            
            return {
                "status": "ok",
                "geo_enabled": self.geo_enabled,
                "geo_profile": self.geo_profile,
                "geo_jitter": self.geo_jitter,
                "device_model": self.device_model,
                "niche": self.niche,
                "preset": self.preset,
                "template": self.template,
                "subtitle": self.subtitle,
                "subtitle_srt_path": self.subtitle_srt_path or "",
                "overlay_mode": self.overlay_mode,
                "overlay_position": self.overlay_position,
                "subtitle_style": self.subtitle_style,
                "subtitle_font": self.subtitle_font,
                "subtitle_font_size": self.subtitle_font_size,
                "overlay_media_path": str(self.overlay_media_path.resolve()),
                "overlay_blend_mode": self.overlay_blend_mode,
                "overlay_opacity": self.overlay_opacity,
                "effects": dict(self.effects),
                "effect_levels": dict(self.effect_levels),
                "uniqualize_intensity": self.uniqualize_intensity,
                "auto_trim_lead_tail": self.auto_trim_lead_tail,
                "perceptual_hash_check": self.perceptual_hash_check,
                "tags": list(self.tags),
                "thumbnail_path": self.thumbnail_path or "",
            }
        except Exception as exc:
            logger.exception("update_uniqualizer_settings: %s", exc)
            return {"status": "error", "message": "Не удалось обновить настройки уникализатора."}

    async def _fail_or_retry(
        self,
        task_id: int,
        error_message: str,
        error_type: str | None,
        retry_count: int,
        unique_path: str | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        """
        Решает судьбу упавшей задачи: авто-ретрай с задержкой или финальная ошибка.

        Retryable error_type: "adspower", "upload" (кроме Google-верификации).
        Non-retryable: конфигурационные ошибки (error_type=None), "render", отмена.
        """
        max_r = _max_retries()
        if max_r > 0 and _is_retryable_error(error_type, error_message) and retry_count < max_r:
            delay = _RETRY_DELAYS[min(retry_count, len(_RETRY_DELAYS) - 1)]
            attempt_label = f"{retry_count + 1}/{max_r}"
            logger.warning(
                "task %s failed [%s] (attempt %s): %s — retry in %ds",
                task_id, error_type or "?", attempt_label, error_message[:120], delay,
            )
            await dbmod.reschedule_task_for_retry(
                task_id,
                delay_seconds=delay,
                error_message=f"[попытка {attempt_label}] {error_message}",
                tenant_id=self.tenant_id,
                db_path=self.db_path,
            )
            # Удаляем незавершённый рендер — при повторе он пересоздастся.
            self._metrics["tasks_retried"] += 1
            if unique_path:
                self._try_delete_file(unique_path)
        else:
            await dbmod.update_task_status(
                task_id,
                "error",
                error_message=error_message,
                error_type=error_type,
                tenant_id=self.tenant_id,
                db_path=self.db_path,
            )
            await notifier.notify_task_error(
                task_id, error_message,
                screenshot_path=screenshot_path,
                tenant_id=self.tenant_id,
            )
            self._metrics["tasks_error"] += 1
            if error_type == "upload":
                self._metrics["uploads_failed"] += 1
            elif error_type == "adspower":
                self._metrics["adspower_failed"] += 1
            elif error_type == "render":
                self._metrics["render_failed"] += 1

    async def _worker_loop(self, worker_id: int) -> None:
        logger.info("worker %s started", worker_id)
        _processed = 0
        while not self._stop.is_set():
            try:
                task_id = await asyncio.wait_for(self.queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                # Если очередь пуста и worker 0 обработал хотя бы одну задачу — проверим итог
                if worker_id == 0 and _processed > 0 and self.queue.empty():
                    await self._maybe_notify_queue_finished()
                    _processed = 0
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("worker %s queue get: %s", worker_id, exc)
                continue

            try:
                await self._process_task(task_id)
                _processed += 1
            except Exception as exc:
                # Двойная страховка: тело процесса уже в try/except, сюда почти не попадём
                logger.error("worker %s fatal: %s\n%s", worker_id, exc, traceback.format_exc())
                _processed += 1
            finally:
                try:
                    self.queue.task_done()
                except Exception:
                    pass

        logger.info("worker %s stopped", worker_id)

    async def _maybe_notify_queue_finished(self) -> None:
        """Отправить сводку в Telegram когда очередь опустела."""
        try:
            res = await dbmod.list_tasks(500, self.tenant_id, self.db_path)
            tasks = res.get("tasks") or []
            if not tasks:
                return
            # Считаем только недавние: pending/rendering/uploading должны быть 0
            in_flight = sum(1 for t in tasks if t.get("status") in ("pending", "rendering", "uploading"))
            if in_flight > 0:
                return
            total = len(tasks)
            success = sum(1 for t in tasks if t.get("status") == "success")
            errors = sum(1 for t in tasks if t.get("status") == "error")
            await notifier.notify_queue_finished(total, success, errors, self.tenant_id)
        except Exception as exc:
            logger.warning("_maybe_notify_queue_finished: %s", exc)

    async def _process_task(self, task_id: int) -> None:
        """Один полный проход: рендер → AI → AdsPower → загрузка → стоп профиля."""
        profile_id: str | None = None
        ws: str | None = None
        original_video_for_hotfolder: str | None = None

        try:
            got = await dbmod.get_task_by_id(task_id, self.tenant_id, self.db_path)
            if got.get("status") != "ok":
                return
            task = got.get("task") or {}
            # Дубликаты в runtime-очереди безопасно игнорируем.
            # Обрабатываем только задачи, которые всё ещё pending.
            if str(task.get("status") or "").lower() != "pending":
                return
            retry_count = int(task.get("retry_count") or 0)
            profile_id = str(task.get("target_profile") or "").strip()
            original = task.get("original_video")
            render_only = bool(task.get("render_only", 0))
            original_video_for_hotfolder = str(original) if original else None
            if not original:
                await dbmod.update_task_status(
                    task_id,
                    "error",
                    error_message="В задаче не указано исходное видео.",
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )
                return
            if not render_only and not profile_id:
                await dbmod.update_task_status(
                    task_id,
                    "error",
                    error_message="Для залива в антидетект не указан профиль AdsPower.",
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )
                return

            # 1) AI метаданные — до рендера, чтобы overlay_text использовался как субтитр.
            meta = await ai_copywriter.generate_metadata(self.groq_api_key, self.niche)
            title = str(meta.get("title", "Shorts"))
            description = str(meta.get("description", ""))
            comment = str(meta.get("comment", ""))
            ai_overlay_text = str(meta.get("overlay_text", "")).strip()

            # 1.5) Авто-субтитры (subtitle_generator / Groq Whisper) и ИИ-дубляж (ai_dubber)
            target_lang = "ko" if "busan" in self.geo_profile.lower() or "seoul" in self.geo_profile.lower() else "en"

            out_file = storage_mod.get_default_storage().render_output_path(self.tenant_id, task_id)
            dub_audio_path: str | None = None
            ass_path_for_render: str | None = None

            task_auto_subs = int(task.get("auto_subtitles") or 0) > 0 or self.auto_subtitles
            task_auto_dub = int(task.get("auto_dubbing") or 0) > 0 or self.auto_dubbing

            srt_for_render: str | None = self.subtitle_srt_path

            if task_auto_subs or task_auto_dub:
                await dbmod.update_task_status(task_id, "transcribing", tenant_id=self.tenant_id, db_path=self.db_path)

            # ── Авто-субтитры через subtitle_generator (Groq Whisper API) ─────
            if task_auto_subs:
                logger.info("Task %s: Groq Whisper транскрибация для субтитров…", task_id)
                try:
                    sub_res = await subtitle_generator.generate_subtitles(
                        video_path=str(original),
                        output_dir=str(Path(out_file).parent),
                        api_key=self.groq_api_key or "",
                        source_lang=None,
                        target_lang=target_lang if target_lang != "en" else None,
                        burn=False,  # сжигаем сами в luxury_engine через ass= фильтр
                    )
                    if sub_res.get("status") == "ok":
                        if sub_res.get("ass_path"):
                            ass_path_for_render = sub_res["ass_path"]
                            logger.info("Task %s: ASS субтитры готовы: %s", task_id, ass_path_for_render)
                        if sub_res.get("srt_path"):
                            srt_for_render = sub_res["srt_path"]
                    else:
                        logger.warning("Task %s subtitle_generator failed: %s", task_id, sub_res.get("message"))
                except Exception as _sub_exc:
                    logger.exception("Task %s subtitle_generator exception: %s", task_id, _sub_exc)

            # ── Дубляж через ai_dubber (edge-tts аудио) ───────────────────────
            if task_auto_dub:
                logger.info("Task %s: Генерация дублированного аудио…", task_id)
                try:
                    dub_res = await ai_dubber.transcribe_and_process(
                        original_video=original,
                        target_lang=target_lang if target_lang != "en" else None,
                        groq_key=self.groq_api_key,
                        generate_dub=True,
                        output_dir=Path(out_file).parent,
                    )
                    if dub_res.get("status") == "ok":
                        if dub_res.get("dub_path"):
                            dub_audio_path = dub_res["dub_path"]
                            logger.info("Task %s: дублированное аудио: %s", task_id, dub_audio_path)
                        # Если субтитры ещё не получены через subtitle_generator
                        if not srt_for_render and dub_res.get("srt_path"):
                            srt_for_render = dub_res["srt_path"]
                    else:
                        logger.warning("Task %s ai_dubber failed: %s", task_id, dub_res.get("message"))
                except Exception as _dub_exc:
                    logger.exception("Task %s ai_dubber exception: %s", task_id, _dub_exc)

            # 2) Рендер
            await dbmod.update_task_status(
                task_id, "rendering", tenant_id=self.tenant_id, db_path=self.db_path
            )
            self._current_task_id = task_id

            if not self.overlay_media_path.is_file():
                await dbmod.update_task_status(
                    task_id,
                    "error",
                    error_message="Нет файла слоя (картинка/видео). Положите data/overlay.png или загрузите слой в интерфейсе.",
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )
                return

            _cancel_ev = asyncio.Event()
            self._active_tasks[task_id] = _cancel_ev
            self._task_cancel_event = _cancel_ev  # compat: для single-worker диагностики
            self._encode_progress = {
                "active": True,
                "task_id": task_id,
                "percent": 2.0,
                "label": "Подготовка: ffprobe и сборка фильтров…",
            }

            # srt_for_render уже определен выше
            row_sub = task.get("subtitle")
            subtitle_for_render = (
                str(row_sub).strip()
                if isinstance(row_sub, str) and str(row_sub).strip()
                else self.subtitle
            )
            # Если субтитр не задан — используем AI CTA-текст как субтитр.
            if not subtitle_for_render and ai_overlay_text:
                subtitle_for_render = ai_overlay_text
            row_tpl = task.get("template")
            template_for_render = (
                luxury_engine._normalize_template(str(row_tpl).strip())
                if isinstance(row_tpl, str) and str(row_tpl).strip()
                else self.template
            )
            # Per-task effects override (из пакетной генерации с randomize_effects=True).
            effects_for_render = self.effects
            effect_levels_for_render = self.effect_levels
            intensity_for_render = self.uniqualize_intensity
            row_efx = task.get("effects_json")
            if isinstance(row_efx, str) and row_efx.strip():
                try:
                    import json as _json_rt
                    efx_data = _json_rt.loads(row_efx)
                    if isinstance(efx_data.get("effects"), dict):
                        effects_for_render = efx_data["effects"]
                    if isinstance(efx_data.get("effect_levels"), dict):
                        effect_levels_for_render = efx_data["effect_levels"]
                    if isinstance(efx_data.get("intensity"), str):
                        intensity_for_render = luxury_engine._normalize_uniqualize_intensity(
                            efx_data["intensity"]
                        )
                except (ValueError, KeyError, TypeError):
                    pass

            async def _on_encode_progress(pct: float, label: str, metrics: dict[str, Any] | None = None) -> None:
                self._encode_progress = {
                    "active": True,
                    "task_id": task_id,
                    "percent": float(pct),
                    "label": str(label),
                    "metrics": metrics or {},
                }

            # Per-task device/geo override (из пакетной генерации с randomize_device_geo=True).
            device_model_for_render = self.device_model
            geo_profile_for_render = self.geo_profile
            row_dev = task.get("device_model")
            if isinstance(row_dev, str) and row_dev.strip():
                device_model_for_render = row_dev.strip()
            row_geo = task.get("geo_profile")
            if isinstance(row_geo, str) and row_geo.strip():
                geo_profile_for_render = row_geo.strip()

            render_coro = luxury_engine.render_unique_video(
                str(original),
                str(self.overlay_media_path),
                str(out_file),
                preset=self.preset,
                template=template_for_render,
                subtitle=subtitle_for_render,
                srt_path=srt_for_render,
                ass_path=ass_path_for_render,
                dub_audio_path=dub_audio_path,
                overlay_mode=self.overlay_mode,
                overlay_position=self.overlay_position,
                overlay_blend_mode=self.overlay_blend_mode,
                overlay_opacity=self.overlay_opacity,
                subtitle_style=self.subtitle_style,
                subtitle_font=self.subtitle_font or None,
                subtitle_font_size=self.subtitle_font_size or None,
                effects=effects_for_render,
                effect_levels=effect_levels_for_render,
                uniqualize_intensity=intensity_for_render,
                geo_enabled=self.geo_enabled,
                geo_profile=geo_profile_for_render,
                geo_jitter=self.geo_jitter,
                device_model=device_model_for_render,
                auto_trim_lead_tail=self.auto_trim_lead_tail,
                perceptual_hash_check=self.perceptual_hash_check,
                progress_callback=_on_encode_progress,
                cancel_event=_cancel_ev,
            )
            tmo = _render_task_timeout_sec()
            if tmo is None:
                rend = await render_coro
            else:
                try:
                    rend = await asyncio.wait_for(render_coro, timeout=tmo)
                except asyncio.TimeoutError:
                    rend = {
                        "status": "error",
                        "message": f"Рендер завис и был остановлен по таймауту ({int(tmo)} c).",
                    }
            self._clear_encode_progress()
            if rend.get("status") != "ok":
                await dbmod.update_task_status(
                    task_id,
                    "error",
                    error_message=str(rend.get("message", "Ошибка рендера")),
                    error_type="render",
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )
                return

            unique_path = str(rend.get("output_path") or out_file)

            # Сохраняем предупреждение perceptual hash, если видео слишком похоже на оригинал.
            phash_warning = rend.get("perceptual_warning")
            if phash_warning:
                await dbmod.update_task_warning(
                    task_id,
                    str(phash_warning),
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )
                logger.warning("task %s perceptual_warning: %s", task_id, phash_warning)

            # Если режим "только рендер" — сохраняем результат и завершаем.
            if render_only:
                if self._task_cancelled(_cancel_ev):
                    await self._fail_task_cancelled(task_id, unique_path)
                    return
                await dbmod.update_task_status(
                    task_id,
                    "success",
                    unique_video=unique_path,
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )
                logger.info("task %s render-only: done → %s", task_id, unique_path)
                return

            await dbmod.update_task_status(
                task_id,
                "rendering",
                unique_video=unique_path,
                tenant_id=self.tenant_id,
                db_path=self.db_path,
            )

            if self._task_cancelled(_cancel_ev):
                await self._fail_task_cancelled(task_id, unique_path)
                return

            # 3) AdsPower — с мьютексом по профилю (один профиль = один воркер за раз).
            _profile_lock = self._get_profile_lock(profile_id)
            async with _profile_lock:
                start = await adspower_sync.start_profile_with_retry(profile_id)
                if start.get("status") != "ok":
                    await self._fail_or_retry(
                        task_id,
                        error_message=str(start.get("message", "AdsPower")),
                        error_type="adspower",
                        retry_count=retry_count,
                        unique_path=unique_path,
                    )
                    return
                ws = str(start.get("ws_endpoint") or "")

                if self._task_cancelled(_cancel_ev):
                    await self._fail_task_cancelled(task_id, unique_path)
                    return

                # 4) Загрузка с retry (до 3 попыток, backoff 5s→10s→20s)
                #    Верификация Google — не retryable; прочие ошибки — retryable.
                # Спиннинг YouTube-метаданных — уникальные гомоглифы/ZWS для каждого таска.
                title, description = luxury_engine.spin_yt_metadata(title, description)
                await dbmod.update_task_status(
                    task_id, "uploading", tenant_id=self.tenant_id, db_path=self.db_path
                )
                _upload_attempts = int(os.environ.get("NEORENDER_UPLOAD_RETRIES") or "3")
                _upload_backoff = 5.0
                up: dict[str, Any] = {"status": "error", "message": "Загрузка не выполнена"}
                for _attempt in range(max(1, _upload_attempts)):
                    if self._task_cancelled(_cancel_ev):
                        await self._fail_task_cancelled(task_id, unique_path)
                        return
                    up = await youtube_automator.upload_and_publish(
                        ws,
                        unique_path,
                        title,
                        description,
                        comment=comment or None,
                        tags=self.tags or None,
                        thumbnail_path=self.thumbnail_path or None,
                    )
                    if up.get("status") == "ok":
                        break
                    _err_msg_attempt = str(up.get("message") or "")
                    # Верификация Google — нет смысла повторять
                    if "верификац" in _err_msg_attempt.lower() or "verify" in _err_msg_attempt.lower():
                        break
                    if _attempt < _upload_attempts - 1:
                        logger.warning(
                            "task %s upload attempt %d/%d failed: %s — retry in %.0fs",
                            task_id, _attempt + 1, _upload_attempts, _err_msg_attempt[:120], _upload_backoff,
                        )
                        await asyncio.sleep(_upload_backoff)
                        _upload_backoff = min(_upload_backoff * 2, 60.0)
            # --- конец async with _profile_lock ---


            if up.get("status") != "ok":
                _err_msg = str(up.get("message", "YouTube"))
                _shot = up.get("screenshot_path")
                _up_type = str(up.get("error_type") or "upload")
                await self._fail_or_retry(
                    task_id,
                    error_message=_err_msg,
                    error_type=_up_type,
                    retry_count=retry_count,
                    unique_path=unique_path,
                    screenshot_path=_shot,
                )
                return

            await dbmod.update_task_status(
                task_id, "success", tenant_id=self.tenant_id, db_path=self.db_path
            )
            self._metrics["tasks_success"] += 1

            vurl = up.get("video_url")
            if vurl:
                from datetime import datetime, timezone
                _published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await dbmod.add_analytics_row(
                    str(vurl),
                    views=0,
                    likes=0,
                    status="active",
                    published_at=_published_at,
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )

            await notifier.notify_task_success(
                task_id, video_url=vurl, tenant_id=self.tenant_id
            )
            # Notify if video gets significant views quickly
            if vurl:
                try:
                    from core import analytics_scraper as _asc
                    _metrics = await _asc.check_video(vurl)
                    _views = int(_metrics.get("views", 0) or 0)
                    if _views >= 1000:
                        await notifier.notify_task_success_with_views(
                            task_id, vurl, _views, tenant_id=self.tenant_id
                        )
                except Exception:
                    pass

            # 5) Очистка файлов после успешного залива
            if self._cleanup_enabled():
                self._try_delete_file(unique_path)
                _orig = task.get("original_video")
                # Удаляем исходник только если он в data/uploads/ (загруженный через UI)
                if _orig and str(_orig).find("uploads") != -1:
                    self._try_delete_file(str(_orig))

        except Exception as exc:
            logger.exception("task %s: %s", task_id, exc)
            _err = _short_err(exc)
            try:
                await dbmod.update_task_status(
                    task_id,
                    "error",
                    error_message=_err,
                    error_type="render",
                    tenant_id=self.tenant_id,
                    db_path=self.db_path,
                )
            except Exception:
                logger.exception("failed to write task error to db")
            await notifier.notify_task_error(task_id, _err, tenant_id=self.tenant_id)
            return
        finally:
            self._metrics["tasks_processed"] += 1
            self._active_tasks.pop(task_id, None)
            self._current_task_id = None
            self._task_cancel_event = None
            self._clear_encode_progress()
            # Для задач из hot-folder переносим файл из processing/ в done|error.
            if original_video_for_hotfolder and self.hot_folder:
                try:
                    got = await dbmod.get_task_by_id(task_id, self.tenant_id, self.db_path)
                    status = str((got.get("task") or {}).get("status") or "").lower()
                    if status == "success":
                        await self.hot_folder.mark_done(original_video_for_hotfolder)
                    elif status == "error":
                        await self.hot_folder.mark_error(original_video_for_hotfolder)
                except Exception as exc:
                    logger.warning("hot_folder finalize task %s: %s", task_id, exc)
            await self._safe_stop_profile(profile_id)

    def _get_profile_lock(self, profile_id: str) -> asyncio.Lock:
        """Lazy-создание мьютекса per-profile (предотвращает параллельный доступ к одному профилю)."""
        if profile_id not in self._profile_locks:
            self._profile_locks[profile_id] = asyncio.Lock()
        return self._profile_locks[profile_id]

    async def _safe_stop_profile(self, profile_id: str | None) -> None:
        if not profile_id:
            return
        try:
            await adspower_sync.stop_profile(profile_id)
        except Exception as exc:
            logger.warning("stop_profile %s: %s", profile_id, exc)

    @staticmethod
    def _cleanup_enabled() -> bool:
        raw = (os.environ.get("NEORENDER_CLEANUP_ON_SUCCESS") or "").strip().lower()
        return raw in ("1", "true", "yes", "on")

    @staticmethod
    def _try_delete_file(path: str | None) -> None:
        if not path:
            return
        try:
            p = Path(path)
            if p.is_file():
                p.unlink()
                logger.info("cleanup: удалён %s", path)
        except OSError as exc:
            logger.warning("cleanup unlink %s: %s", path, exc)


async def run_demo_enqueue(
    original_video: str,
    target_profile_adspower_id: str,
    db_path: str | Path | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Вспомогательная функция для теста: создать задачу, запустить пайплайн, поставить в очередь.
    """
    try:
        c = await dbmod.create_task(
            original_video=original_video,
            target_profile=target_profile_adspower_id,
            tenant_id=tenant_id,
            db_path=db_path,
        )
        if c.get("status") != "ok":
            return c
        tid = c.get("id")
        pipe = AutomationPipeline(db_path=db_path, tenant_id=tenant_id)
        st = await pipe.start()
        if st.get("status") != "ok":
            return st
        await pipe.enqueue(int(tid))
        return {"status": "ok", "task_id": tid}
    except Exception as exc:
        logger.exception("run_demo_enqueue: %s", exc)
        return {"status": "error", "message": "Не удалось поставить задачу в очередь."}
