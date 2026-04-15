from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import adspower_profiles
from core import analytics_scraper
from core import database as dbmod
from core import warmup_automator
from core import youtube_automator
from core.antidetect_registry import get_registry
try:
    from core import notifier as _notifier
except ImportError:
    _notifier = None  # type: ignore

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt_utc(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        # SQLite формат: "YYYY-MM-DD HH:MM:SS"
        if "T" not in s and len(s) == 19 and " " in s:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _error(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "error", "message": message}
    if data:
        out.update(data)
    return out


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


async def _run_warmup(
    job: dict[str, Any],
    payload: dict[str, Any],
    tenant_id: str,
    db_path: str | None,
) -> dict[str, Any]:
    res = await warmup_automator.run_warmup_for_profile(
        profile_id=str(job["adspower_profile_id"]),
        intensity=str(payload.get("intensity") or "medium"),
        niche_keywords=payload.get("niche_keywords") if isinstance(payload.get("niche_keywords"), list) else None,
        tenant_id=tenant_id,
    )
    return res


async def _run_publish(
    job: dict[str, Any],
    payload: dict[str, Any],
    tenant_id: str,
    db_path: str | None,
) -> dict[str, Any]:
    # ── Проверка дневного лимита (KST) ────────────────────────────────────────
    profile_id = str(job.get("adspower_profile_id") or "").strip()
    if profile_id:
        limit_res = await dbmod.get_profile_daily_limit(profile_id, tenant_id=tenant_id, db_path=db_path)
        count_res = await dbmod.get_profile_daily_upload_count(profile_id, tenant_id=tenant_id, db_path=db_path)
        if limit_res.get("status") == "ok" and count_res.get("status") == "ok":
            daily_limit = int(limit_res.get("daily_upload_limit") or 3)
            used_today  = int(count_res.get("count") or 0)
            if used_today >= daily_limit:
                return _error(
                    f"Дневной лимит заливок исчерпан: {used_today}/{daily_limit} (KST). "
                    "Следующая заливка — завтра после 09:00 KST."
                )
            logger.info(
                "publish: профиль %s — заливок сегодня %d/%d (KST)",
                profile_id, used_today, daily_limit,
            )
    # ─────────────────────────────────────────────────────────────────────────

    task_id = payload.get("task_id")
    if not isinstance(task_id, int):
        return _error("Для publish job нужен task_id.")
    task_res = await dbmod.get_task_by_id(task_id, tenant_id=tenant_id, db_path=db_path)
    if task_res.get("status") != "ok":
        return _error("Рендер-задача для публикации не найдена.")
    task = task_res.get("task") or {}
    unique_video = str(task.get("unique_video") or "").strip()
    if not unique_video:
        return _error("У задачи нет unique_video. Сначала завершите рендер.")
    if not Path(unique_video).is_file():
        return _error("Файл unique_video не найден на диске.")

    title = str(payload.get("title") or f"Short {task_id}")
    description = str(payload.get("description") or "")
    comment = str(payload.get("comment") or "").strip() or None
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else None
    thumbnail_path = str(payload.get("thumbnail_path") or "").strip() or None

    pid = str(job["adspower_profile_id"])
    registry = get_registry()
    started = await registry.start_profile(pid, tenant_id=tenant_id)
    if started.get("status") != "ok":
        return _error(str(started.get("message") or "Не удалось запустить профиль для публикации."))
    ws_endpoint = str(started.get("ws_endpoint") or "")
    if not ws_endpoint:
        await registry.stop_profile(pid, tenant_id=tenant_id)
        return _error("Антидетект-браузер не вернул ws_endpoint.")
    try:
        publish = await youtube_automator.upload_and_publish(
            ws_endpoint,
            unique_video,
            title,
            description,
            comment=comment,
            tags=tags,
            thumbnail_path=thumbnail_path,
        )
    finally:
        await registry.stop_profile(pid, tenant_id=tenant_id)
    if publish.get("status") != "ok":
        return publish
    video_url = str(publish.get("video_url") or "").strip()
    if video_url:
        await dbmod.add_analytics_row(
            video_url,
            views=0,
            likes=0,
            status="active",
            published_at=_utc_now(),
            tenant_id=tenant_id,
            db_path=db_path,
        )
        await dbmod.update_adspower_profile_publish(
            str(job["adspower_profile_id"]),
            tenant_id=tenant_id,
            db_path=db_path,
        )
    return _ok({"video_url": video_url, "task_id": task_id, "comment_pinned": bool(publish.get("comment_pinned"))})


async def _run_verify(
    job: dict[str, Any],
    payload: dict[str, Any],
    tenant_id: str,
    db_path: str | None,
) -> dict[str, Any]:
    video_url = str(payload.get("video_url") or "").strip()
    if not video_url:
        return _error("Для verify job нужна video_url.")
    published_at = payload.get("published_at")
    checked = await analytics_scraper.check_video(video_url, published_at=published_at)
    if checked.get("status") in ("active", "shadowban", "banned"):
        views = int(checked.get("views") or 0)
        status_str = str(checked.get("status"))
        await dbmod.add_analytics_row(
            video_url,
            views=views,
            likes=0,
            status=status_str,
            published_at=str(published_at or ""),
            tenant_id=tenant_id,
            db_path=db_path,
        )
        # Telegram notifications
        if _notifier:
            profile_id = str(job.get("adspower_profile_id") or "")
            if status_str in ("shadowban", "banned"):
                try:
                    await _notifier.notify_shadowban_detected(profile_id, video_url, tenant_id)
                except Exception:
                    pass
            elif views >= 1000:
                try:
                    task_id = int(job.get("task_id") or 0)
                    await _notifier.notify_task_success_with_views(task_id, video_url, views, tenant_id)
                except Exception:
                    pass
        return _ok({"video_url": video_url, "verification": checked})
    return checked


async def _run_stats_sync(
    job: dict[str, Any],
    payload: dict[str, Any],
    tenant_id: str,
    db_path: str | None,
) -> dict[str, Any]:
    video_url = str(payload.get("video_url") or "").strip()
    if not video_url:
        return _error("Для stats_sync job нужна video_url.")
    checked = await analytics_scraper.check_video(video_url, published_at=payload.get("published_at"))
    if checked.get("status") in ("active", "shadowban", "banned"):
        await dbmod.add_analytics_row(
            video_url,
            views=int(checked.get("views") or 0),
            likes=0,
            status=str(checked.get("status")),
            published_at=str(payload.get("published_at") or ""),
            tenant_id=tenant_id,
            db_path=db_path,
        )
        return _ok({"video_url": video_url, "stats": checked})
    return checked


async def run_profile_job(
    job_id: int,
    tenant_id: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    job_res = await dbmod.get_profile_job(job_id, tenant_id=tenant_id, db_path=db_path)
    if job_res.get("status") != "ok":
        return job_res
    job = job_res.get("job") or {}
    job_status = str(job.get("status") or "")
    if job_status not in ("pending", "scheduled"):
        return _error(f"Задача уже в статусе {job_status}.")
    scheduled_at = str(job.get("scheduled_at") or "").strip()
    if scheduled_at:
        sched_dt = _parse_dt_utc(scheduled_at)
        if sched_dt is None:
            return _error("Некорректный scheduled_at в задаче профиля.")
        if sched_dt > datetime.now(timezone.utc):
            return _ok({"message": "Задача ещё не наступила по расписанию.", "job_id": job_id})

    payload_raw = str(job.get("payload_json") or "").strip()
    payload: dict[str, Any] = {}
    if payload_raw:
        try:
            parsed = json.loads(payload_raw)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}

    claimed = await dbmod.claim_profile_job_for_run(
        job_id,
        tenant_id=tenant_id,
        started_at=_utc_now(),
        db_path=db_path,
    )
    if claimed.get("status") != "ok":
        return claimed
    if not claimed.get("claimed"):
        return _error("Задача уже запущена другим воркером.")
    await adspower_profiles.record_profile_event(
        str(job.get("adspower_profile_id") or ""),
        "job_started",
        message=f"Запущена задача профиля {job.get('job_type')}.",
        payload={"job_id": job_id, "job_type": job.get("job_type")},
        tenant_id=tenant_id,
        db_path=db_path,
    )

    runner_map = {
        "warmup": _run_warmup,
        "publish": _run_publish,
        "verify": _run_verify,
        "stats_sync": _run_stats_sync,
    }
    runner = runner_map.get(str(job.get("job_type") or ""))
    if runner is None:
        err = "Неизвестный тип задачи профиля."
        await dbmod.update_profile_job_status(
            job_id,
            "error",
            error_type="unsupported_job_type",
            error_message=err,
            finished_at=_utc_now(),
            tenant_id=tenant_id,
            db_path=db_path,
        )
        return _error(err)

    try:
        result = await runner(job, payload, tenant_id, db_path)
        if result.get("status") == "ok":
            await dbmod.update_profile_job_status(
                job_id,
                "success",
                result_json=json.dumps(result, ensure_ascii=False),
                error_type=None,
                error_message=None,
                finished_at=_utc_now(),
                tenant_id=tenant_id,
                db_path=db_path,
            )
            await adspower_profiles.record_profile_event(
                str(job.get("adspower_profile_id") or ""),
                "job_success",
                message=f"Задача профиля {job.get('job_type')} завершена успешно.",
                payload={"job_id": job_id, "result": result},
                tenant_id=tenant_id,
                db_path=db_path,
            )
            return result
        error_message = str(result.get("message") or "Задача завершилась с ошибкой.")
        await dbmod.update_profile_job_status(
            job_id,
            "error",
            result_json=json.dumps(result, ensure_ascii=False),
            error_type=str(result.get("error_type") or "job_error"),
            error_message=error_message,
            finished_at=_utc_now(),
            tenant_id=tenant_id,
            db_path=db_path,
        )
        await adspower_profiles.record_profile_event(
            str(job.get("adspower_profile_id") or ""),
            "job_error",
            message=error_message,
            payload={"job_id": job_id, "result": result},
            tenant_id=tenant_id,
            db_path=db_path,
        )
        return result
    except Exception as exc:
        logger.exception("run_profile_job(%s): %s", job_id, exc)
        error_message = "Внутренняя ошибка выполнения задачи профиля."
        await dbmod.update_profile_job_status(
            job_id,
            "error",
            error_type="internal_error",
            error_message=error_message,
            finished_at=_utc_now(),
            tenant_id=tenant_id,
            db_path=db_path,
        )
        await adspower_profiles.record_profile_event(
            str(job.get("adspower_profile_id") or ""),
            "job_error",
            message=error_message,
            payload={"job_id": job_id},
            tenant_id=tenant_id,
            db_path=db_path,
        )
        return _error(error_message)
