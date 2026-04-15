"""
Hot Folder — автоматический загрузчик видео из папки.

Схема работы:
  inbox/       ← пользователь кладёт сюда видео
  processing/  ← watcher переместил файл, создал задачу в БД
  done/        ← pipeline переместил после успешного залива
  error/       ← pipeline переместил после ошибки

Интеграция:
  pipeline.hot_folder.start()   — запускается вместе с пайплайном
  pipeline.hot_folder.stop()    — при остановке

Настройки хранятся в AutomationPipeline:
  pipeline.hot_folder_inbox     — Path к inbox (None = выключено)
  pipeline.hot_folder_profile   — профиль AdsPower по умолчанию
  pipeline.hot_folder_render_only — не заливать, только рендерить
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .main_loop import AutomationPipeline

logger = logging.getLogger(__name__)

# Поддерживаемые расширения видео.
_VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".ts", ".m4v", ".flv",
})

# Интервал опроса папки (секунд).
POLL_INTERVAL = 10.0

# Минимальный размер файла (байт) — меньше считаем незавершённой записью.
_MIN_FILE_SIZE = 4096

# Сколько раз подряд размер файла должен совпадать прежде чем считать его готовым.
_STABLE_CHECKS = 2
_SMALL_FILE_MAX_TICKS = 18  # ~3 минуты при poll=10с


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_EXTS


def _subdir(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return d


class HotFolder:
    """
    Фоновый watcher: каждые POLL_INTERVAL секунд сканирует inbox_dir,
    подхватывает новые видео, создаёт задачи в БД и ставит их в очередь.
    """

    def __init__(self, pipeline: "AutomationPipeline") -> None:
        self._pipeline = pipeline
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        # Файлы, которые уже подхвачены (по абс. пути), чтобы не создавать дубли.
        self._seen: set[str] = set()
        # Статистика текущей сессии.
        self.stats: dict[str, int] = {
            "detected": 0,
            "tasks_created": 0,
            "errors": 0,
        }

    # ── Публичный интерфейс ──────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def inbox_dir(self) -> Path | None:
        raw = getattr(self._pipeline, "hot_folder_inbox", None)
        return Path(raw) if raw else None

    async def start(self) -> None:
        if self.is_running:
            return
        if not self.inbox_dir:
            return  # не настроен — молча ничего не делаем
        await self._recover_processing_orphans()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="hot-folder-watcher")
        logger.info("HotFolder started: watching %s", self.inbox_dir)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("HotFolder stopped")

    def get_status(self) -> dict[str, Any]:
        """Статус для API: включён/нет, что лежит в каждой папке."""
        inbox = self.inbox_dir
        if not inbox:
            return {
                "enabled": False,
                "is_running": False,
                "inbox_dir": None,
                "stats": self.stats,
                "inbox_files": [],
                "processing_files": [],
                "done_files": [],
                "error_files": [],
            }
        base = inbox.parent if inbox.name == "inbox" else inbox
        inbox_files    = _list_videos(inbox)
        proc_files     = _list_videos(base / "processing") if (base / "processing").exists() else []
        done_files     = _list_videos(base / "done")       if (base / "done").exists()       else []
        error_files    = _list_videos(base / "error")      if (base / "error").exists()      else []
        return {
            "enabled":           True,
            "is_running":        self.is_running,
            "inbox_dir":         str(inbox),
            "processing_dir":    str(base / "processing"),
            "done_dir":          str(base / "done"),
            "error_dir":         str(base / "error"),
            "stats":             self.stats,
            "inbox_files":       inbox_files,
            "processing_files":  proc_files,
            "done_files":        done_files,
            "error_files":       error_files,
        }

    async def mark_done(self, original_video: str) -> None:
        """Вызывается из pipeline после успешного завершения задачи."""
        await self._move_file(original_video, "done")

    async def mark_error(self, original_video: str) -> None:
        """Вызывается из pipeline после ошибки задачи."""
        await self._move_file(original_video, "error")

    # ── Внутренняя логика ────────────────────────────────────────────────────

    async def _loop(self) -> None:
        inbox = self.inbox_dir
        if not inbox:
            return
        inbox.mkdir(parents=True, exist_ok=True)
        logger.info("HotFolder watcher loop started (poll=%.0fs)", POLL_INTERVAL)

        # Файлы ожидания стабильности: path → [size_prev, count_stable]
        _size_cache: dict[str, list[int]] = {}
        # Маленькие файлы: path -> число тиков подряд меньше порога.
        _small_ticks: dict[str, int] = {}

        while not self._stop_event.is_set():
            try:
                candidates = [f for f in inbox.iterdir() if f.is_file() and _is_video(f)]
                for fpath in candidates:
                    key = str(fpath.resolve())
                    if key in self._seen:
                        continue

                    # Проверяем стабильность размера (файл не записывается).
                    try:
                        cur_size = fpath.stat().st_size
                    except OSError:
                        continue

                    if cur_size < _MIN_FILE_SIZE:
                        cur_ticks = _small_ticks.get(key, 0) + 1
                        _small_ticks[key] = cur_ticks
                        if cur_ticks >= _SMALL_FILE_MAX_TICKS:
                            await self._move_too_small_to_error(fpath)
                            self._seen.add(key)
                            _small_ticks.pop(key, None)
                        continue  # слишком мал — ждём

                    _small_ticks.pop(key, None)
                    prev_info = _size_cache.get(key, [0, 0])
                    if prev_info[0] == cur_size:
                        prev_info[1] += 1
                    else:
                        prev_info = [cur_size, 0]
                    _size_cache[key] = prev_info

                    if prev_info[1] < _STABLE_CHECKS:
                        continue  # файл ещё пишется

                    # Файл готов — подхватываем.
                    self._seen.add(key)
                    _size_cache.pop(key, None)
                    self.stats["detected"] += 1
                    asyncio.create_task(
                        self._ingest(fpath),
                        name=f"hot-ingest-{fpath.name}",
                    )

            except Exception as exc:
                logger.exception("HotFolder scan error: %s", exc)

            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=POLL_INTERVAL,
                )
                break
            except asyncio.TimeoutError:
                pass  # нормальный тик

    async def _ingest(self, fpath: Path) -> None:
        """Переместить файл в processing/, создать задачу в БД, поставить в очередь."""
        pipe = self._pipeline
        inbox = self.inbox_dir
        if not inbox:
            return

        base = inbox.parent if inbox.name == "inbox" else inbox
        proc_dir = _subdir(base, "processing")
        dest = proc_dir / fpath.name

        # Если файл с таким именем уже есть — добавляем суффикс.
        if dest.exists():
            stem, suf = fpath.stem, fpath.suffix
            dest = proc_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suf}"

        try:
            shutil.move(str(fpath), str(dest))
            logger.info("HotFolder: moved %s → %s", fpath.name, dest)
        except Exception as exc:
            logger.error("HotFolder: failed to move %s: %s", fpath, exc)
            self.stats["errors"] += 1
            self._seen.discard(str(fpath.resolve()))
            return

        # Создаём задачу.
        try:
            from core import database as dbmod
        except ImportError:
            import database as dbmod  # type: ignore

        profile = getattr(pipe, "hot_folder_profile", "") or ""
        render_only = bool(getattr(pipe, "hot_folder_render_only", False))
        template = getattr(pipe, "template", None) or None

        result = await dbmod.create_task(
            original_video=str(dest),
            target_profile=profile,
            render_only=render_only,
            template=template,
            tenant_id=pipe.tenant_id,
            db_path=pipe.db_path,
        )

        if result.get("status") != "ok":
            logger.error("HotFolder: create_task failed for %s: %s", dest, result)
            self.stats["errors"] += 1
            return

        task_id = result.get("id")
        self.stats["tasks_created"] += 1
        logger.info("HotFolder: created task #%s for %s", task_id, dest.name)

        # Ставим в очередь если пайплайн запущен.
        if pipe._started and task_id is not None:
            await pipe.queue.put(int(task_id))
            logger.info("HotFolder: task #%s enqueued", task_id)

    async def _move_file(self, original_video: str, target: str) -> None:
        """Переместить файл из processing/ в done/ или error/."""
        try:
            src = Path(original_video)
            if not src.is_file():
                return
            inbox = self.inbox_dir
            if not inbox:
                return
            base = inbox.parent if inbox.name == "inbox" else inbox
            proc_dir = base / "processing"
            # Только если файл действительно в processing/
            if src.parent.resolve() != proc_dir.resolve():
                return
            dst_dir = _subdir(base, target)
            dst = dst_dir / src.name
            if dst.exists():
                dst = dst_dir / f"{src.stem}_{uuid.uuid4().hex[:8]}{src.suffix}"
            shutil.move(str(src), str(dst))
            # Разрешаем повторную обработку нового файла с тем же именем в inbox.
            self._seen.discard(str(src.resolve()))
            logger.info("HotFolder: %s → %s/", src.name, target)
        except Exception as exc:
            logger.warning("HotFolder: _move_file error: %s", exc)

    async def _recover_processing_orphans(self) -> None:
        inbox = self.inbox_dir
        if not inbox:
            return
        base = inbox.parent if inbox.name == "inbox" else inbox
        proc_dir = base / "processing"
        if not proc_dir.exists():
            return
        recovered = 0
        for src in proc_dir.iterdir():
            if not src.is_file() or not _is_video(src):
                continue
            dst = inbox / src.name
            if dst.exists():
                dst = inbox / f"{src.stem}_{uuid.uuid4().hex[:8]}{src.suffix}"
            try:
                shutil.move(str(src), str(dst))
                recovered += 1
            except Exception as exc:
                logger.warning("HotFolder: orphan recover failed for %s: %s", src, exc)
        if recovered:
            logger.info("HotFolder: recovered %d orphan file(s) from processing/", recovered)

    async def _move_too_small_to_error(self, src: Path) -> None:
        inbox = self.inbox_dir
        if not inbox:
            return
        try:
            base = inbox.parent if inbox.name == "inbox" else inbox
            err_dir = _subdir(base, "error")
            dst = err_dir / src.name
            if dst.exists():
                dst = err_dir / f"{src.stem}_{uuid.uuid4().hex[:8]}{src.suffix}"
            shutil.move(str(src), str(dst))
            self.stats["errors"] += 1
            self._seen.discard(str(src.resolve()))
            logger.warning(
                "HotFolder: moved too-small file to error after timeout: %s",
                src.name,
            )
        except Exception as exc:
            logger.warning("HotFolder: failed to move too-small file %s: %s", src, exc)


# ── Утилиты ─────────────────────────────────────────────────────────────────

def _list_videos(directory: Path) -> list[dict[str, Any]]:
    """Список видеофайлов в папке для API."""
    try:
        files = []
        for f in sorted(directory.iterdir()):
            if f.is_file() and _is_video(f):
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                files.append({
                    "name": f.name,
                    "size_mb": round(size / 1024 / 1024, 2),
                    "path": str(f),
                })
        return files
    except Exception:
        return []
