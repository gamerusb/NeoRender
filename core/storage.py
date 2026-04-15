"""
Абстракция хранилища медиафайлов: сейчас локальный диск, позже S3 / MinIO.

Все публичные методы возвращают dict (status ok/error) — без traceback наружу.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO

from core.tenancy import normalize_tenant_id

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
_MIN_FREE_BYTES = 512 * 1024 * 1024  # 512 MB reserve


def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


class MediaStorage(ABC):
    """Контракт для смены бэкенда без переписывания API."""

    @abstractmethod
    async def save_upload(
        self,
        tenant_id: str,
        filename_hint: str,
        data: bytes,
        allowed_ext: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        """Сохранить загруженный файл; вернуть path или object_key для БД."""

    @abstractmethod
    def render_output_path(self, tenant_id: str, task_id: int) -> Path:
        """Путь к уникализированному mp4 (локально) или заглушка для облака."""


class LocalMediaStorage(MediaStorage):
    """
    Локальные каталоги: data/uploads/{tenant}/..., data/rendered/{tenant}/...

    В object storage позже: save_upload возвращает key, render — presigned URL pipeline.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._root = Path(base_dir) if base_dir else ROOT / "data"
        self._uploads = self._root / "uploads"
        self._rendered = self._root / "rendered"

    def _safe_tenant(self, tenant_id: str) -> str:
        # tenant_id уже нормализован в tenancy; дополнительно убираем path traversal
        t = (tenant_id or "default").replace("..", "").replace("/", "").replace("\\", "")
        return t or "default"

    def _has_enough_disk_space(self, target_dir: Path, incoming_bytes: int) -> bool:
        try:
            usage = shutil.disk_usage(target_dir)
            return usage.free - incoming_bytes >= _MIN_FREE_BYTES
        except OSError:
            return False

    async def save_upload(
        self,
        tenant_id: str,
        filename_hint: str,
        data: bytes,
        allowed_ext: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        try:
            t = self._safe_tenant(tenant_id)
            ext = Path(filename_hint or "video.mp4").suffix.lower() or ".mp4"
            allowed = allowed_ext or frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm"})
            if ext not in allowed:
                ext = ".mp4"
            name = f"{uuid.uuid4().hex}{ext}"
            dir_path = self._uploads / t
            dir_path.mkdir(parents=True, exist_ok=True)
            if not self._has_enough_disk_space(dir_path, len(data)):
                return _error("Недостаточно свободного места на диске для загрузки файла.")
            path = dir_path / name
            await asyncio.to_thread(path.write_bytes, data)
            return _ok({"path": str(path.resolve()), "filename": name, "tenant_id": t})
        except OSError:
            return _error("Не удалось сохранить файл на диск. Проверьте место и права.")
        except Exception as exc:
            logger.exception("save_upload: %s", exc)
            return _error("Ошибка сохранения файла.")

    async def save_upload_stream(
        self,
        tenant_id: str,
        filename_hint: str,
        chunks: AsyncIterator[bytes],
        allowed_ext: frozenset[str] | None = None,
        chunk_size: int = 1 << 20,  # 1 МБ
    ) -> dict[str, Any]:
        """Сохранить загрузку потоком чанков — не держит весь файл в памяти."""
        t = self._safe_tenant(tenant_id)
        ext = Path(filename_hint or "video.mp4").suffix.lower() or ".mp4"
        allowed = allowed_ext or frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm"})
        if ext not in allowed:
            ext = ".mp4"
        name = f"{uuid.uuid4().hex}{ext}"
        dir_path = self._uploads / t
        dir_path.mkdir(parents=True, exist_ok=True)
        path = dir_path / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            loop = asyncio.get_running_loop()
            fh = await loop.run_in_executor(None, lambda: open(tmp, "wb"))  # noqa: SIM115
            total = 0
            try:
                async for chunk in chunks:
                    if chunk:
                        total += len(chunk)
                        if not self._has_enough_disk_space(dir_path, total):
                            raise OSError("not enough disk space")
                        await loop.run_in_executor(None, fh.write, chunk)
            finally:
                await loop.run_in_executor(None, fh.close)
            await loop.run_in_executor(None, tmp.rename, path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return _error("Не удалось сохранить файл на диск. Проверьте место и права.")
        except Exception as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            logger.exception("save_upload_stream: %s", exc)
            return _error("Ошибка потокового сохранения файла.")
        return _ok({"path": str(path.resolve()), "filename": name, "tenant_id": t})

    def render_output_path(self, tenant_id: str, task_id: int) -> Path:
        t = self._safe_tenant(tenant_id)
        out_dir = self._rendered / t
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"task_{task_id}.mp4"


# Синглтон по умолчанию (в тестах можно подменить)
_default_storage: LocalMediaStorage | None = None


def get_default_storage() -> LocalMediaStorage:
    global _default_storage
    if _default_storage is None:
        _default_storage = LocalMediaStorage()
    return _default_storage


_UPLOAD_VIDEO_FILENAME_RE = re.compile(
    r"^[a-f0-9]{32}\.(mp4|mov|webm|mkv|avi)$",
    re.IGNORECASE,
)


def is_stored_upload_video_filename(filename: str) -> bool:
    s = (filename or "").strip()
    return bool(s and _UPLOAD_VIDEO_FILENAME_RE.match(s))


def resolve_uploaded_video_file(tenant_id: str, filename: str) -> Path | None:
    """
    Абсолютный путь к видео в data/uploads/{tenant}/, только для имён вида {uuid32}.{ext}.
    """
    if not is_stored_upload_video_filename(filename):
        return None
    st = get_default_storage()
    t = st._safe_tenant(normalize_tenant_id(tenant_id))
    base = (st._uploads / t).resolve()
    raw = filename.strip()
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate
