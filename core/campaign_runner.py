"""
Campaign Runner — полная автоматизация за пару кликов.

Поддерживаемые пресеты (preset):
  warmup_only  — только прогрев профиля через warmup_automator
  farm_cookies — прогрев + сохранение cookies через AdsPower API
  upload_only  — загрузка видео (AI-заголовок + YouTube upload)
  full         — прогрев → загрузка → 30 сек → проверка аналитики

Все профили обрабатываются параллельно, с ограничением concurrency.
Состояние пишется в campaign_runs (SQLite) после каждого профиля.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import database as dbmod
    from .tenancy import normalize_tenant_id
except ImportError:
    from core import database as dbmod
    from core.tenancy import normalize_tenant_id

logger = logging.getLogger(__name__)

_COOKIE_BACKUPS_DIR = Path(__file__).resolve().parent.parent / "data" / "cookie_backups"
_DEFAULT_ADSPOWER_URL = "http://local.adspower.net:50325"

VALID_PRESETS = frozenset({"warmup_only", "farm_cookies", "upload_only", "full"})
VALID_INTENSITIES = frozenset({"light", "medium", "deep"})

# ── In-memory registry of running asyncio tasks ───────────────────────────────
_active_tasks: dict[int, asyncio.Task[None]] = {}


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class CampaignRunConfig:
    """Параметры одного запуска кампании."""
    preset: str                          # warmup_only / farm_cookies / upload_only / full
    profile_ids: list[str]               # AdsPower profile IDs
    tenant_id: str = "default"
    video_path: str | None = None        # абсолютный путь к видео (для upload/full)
    niche: str = ""                      # ниша для AI-заголовка и прогрева
    warmup_intensity: str = "medium"     # light / medium / deep
    concurrency: int = 3                 # макс. профилей одновременно
    campaign_id: int | None = None       # необязательная ссылка на campaigns.id
    adspower_api_url: str = _DEFAULT_ADSPOWER_URL
    db_path: Path | None = None


# ── Step: Warmup ──────────────────────────────────────────────────────────────

async def _step_warmup(
    profile_id: str,
    niche: str,
    intensity: str,
    tenant_id: str,
) -> dict[str, Any]:
    try:
        from .warmup_automator import run_warmup_for_profile
    except ImportError:
        from core.warmup_automator import run_warmup_for_profile

    keywords = [kw.strip() for kw in niche.split(",") if kw.strip()] or None
    return await run_warmup_for_profile(
        profile_id=profile_id,
        intensity=intensity,
        niche_keywords=keywords,
        tenant_id=tenant_id,
    )


# ── Step: Farm Cookies ────────────────────────────────────────────────────────

async def _step_farm_cookies(
    profile_id: str,
    tenant_id: str,
    adspower_api_url: str,
) -> dict[str, Any]:
    """Запрашивает cookies у AdsPower и сохраняет файл-бэкап."""
    import httpx

    backup_dir = _COOKIE_BACKUPS_DIR / normalize_tenant_id(tenant_id)
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{profile_id}_backup_{ts}.json"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{adspower_api_url}/api/v1/browser/cookies",
                params={"user_id": profile_id},
            )
            data = resp.json()
        backup_file.write_text(
            json.dumps(
                {"profile_id": profile_id, "cookies": data, "backed_up_at": ts},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        return {"status": "ok", "filename": backup_file.name}
    except Exception as exc:
        logger.exception("farm_cookies %s: %s", profile_id, exc)
        backup_file.write_text(
            json.dumps(
                {"profile_id": profile_id, "cookies": [], "backed_up_at": ts, "error": str(exc)},
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"status": "partial", "filename": backup_file.name, "message": str(exc)}


# ── Step: Upload ──────────────────────────────────────────────────────────────

async def _step_upload(
    profile_id: str,
    video_path: str,
    niche: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Стартует профиль, генерирует метаданные, публикует видео, останавливает профиль."""
    try:
        from .antidetect_registry import get_registry
        from .youtube_automator import upload_and_publish
        from .ai_copywriter import generate_metadata
    except ImportError:
        from core.antidetect_registry import get_registry
        from core.youtube_automator import upload_and_publish
        from core.ai_copywriter import generate_metadata

    registry = get_registry()
    start_res = await registry.start_profile(profile_id, tenant_id=tenant_id)
    if start_res.get("status") != "ok":
        return start_res

    ws_endpoint: str = start_res.get("ws_endpoint", "")
    try:
        meta = await generate_metadata(
            api_key=os.environ.get("GROQ_API_KEY"),
            niche=niche or "general",
        )
        title: str = str(meta.get("title") or niche or "Video")
        description: str = str(meta.get("description") or "")
        comment: str | None = meta.get("comment")

        return await upload_and_publish(
            ws_endpoint=ws_endpoint,
            video_path=video_path,
            title=title,
            description=description,
            comment=comment,
        )
    finally:
        try:
            await registry.stop_profile(profile_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("stop_profile after upload %s: %s", profile_id, exc)


# ── Step: Analytics ───────────────────────────────────────────────────────────

async def _step_analytics(video_url: str) -> dict[str, Any]:
    try:
        from .analytics_scraper import check_video
    except ImportError:
        from core.analytics_scraper import check_video
    return await check_video(video_url)


# ── Per-profile orchestration ─────────────────────────────────────────────────

async def _run_one_profile(
    profile_id: str,
    cfg: CampaignRunConfig,
) -> dict[str, Any]:
    """Выполняет все шаги пресета для одного профиля."""
    result: dict[str, Any] = {"profile_id": profile_id, "steps": {}}

    # ── Warmup ────────────────────────────────────────────────────────────────
    if cfg.preset in ("warmup_only", "farm_cookies", "full"):
        r = await _step_warmup(
            profile_id, cfg.niche, cfg.warmup_intensity, cfg.tenant_id
        )
        result["steps"]["warmup"] = {
            "status": r.get("status"),
            "stats": r.get("stats"),
            "warnings": r.get("warnings"),
            "message": r.get("message"),
        }
        if r.get("status") != "ok":
            result["status"] = "error"
            result["error"] = r.get("message", "warmup failed")
            return result

    # ── Farm Cookies ──────────────────────────────────────────────────────────
    if cfg.preset == "farm_cookies":
        r = await _step_farm_cookies(
            profile_id, cfg.tenant_id, cfg.adspower_api_url
        )
        result["steps"]["farm_cookies"] = r

    # ── Upload ────────────────────────────────────────────────────────────────
    if cfg.preset in ("upload_only", "full"):
        if not cfg.video_path:
            result["steps"]["upload"] = {
                "status": "error",
                "message": "video_path не указан",
            }
            result["status"] = "error"
            return result

        r = await _step_upload(
            profile_id, cfg.video_path, cfg.niche, cfg.tenant_id
        )
        result["steps"]["upload"] = {
            "status": r.get("status"),
            "video_url": r.get("video_url"),
            "error_type": r.get("error_type"),
            "message": r.get("message"),
        }
        if r.get("status") == "ok":
            result["video_url"] = r.get("video_url")
        else:
            result["status"] = "error"
            result["error"] = r.get("message", "upload failed")
            if cfg.preset == "upload_only":
                return result

    # ── Analytics (only for full, and only if video_url obtained) ─────────────
    if cfg.preset == "full" and result.get("video_url"):
        await asyncio.sleep(30)  # дать YouTube время обработать видео
        r = await _step_analytics(result["video_url"])
        result["steps"]["analytics"] = r

    if "status" not in result:
        result["status"] = "ok"
    return result


# ── Campaign worker (async task) ──────────────────────────────────────────────

async def _campaign_worker(run_id: int, cfg: CampaignRunConfig) -> None:
    """Основной воркер: обрабатывает все профили параллельно, пишет прогресс в БД."""
    results: dict[str, dict] = {}
    sem = asyncio.Semaphore(max(1, cfg.concurrency))
    db_path = cfg.db_path

    async def _process_profile(pid: str) -> None:
        async with sem:
            try:
                res = await _run_one_profile(pid, cfg)
            except asyncio.CancelledError:
                results[pid] = {"status": "cancelled"}
                raise
            except Exception as exc:
                logger.exception("campaign_worker profile=%s run=%s: %s", pid, run_id, exc)
                res = {"status": "error", "error": str(exc)}
            results[pid] = res
            # Сохраняем промежуточный прогресс после каждого профиля
            await dbmod.update_campaign_run(
                run_id, tenant_id=cfg.tenant_id, results=results, db_path=db_path
            )

    try:
        await asyncio.gather(*[_process_profile(pid) for pid in cfg.profile_ids])

        errors = sum(1 for r in results.values() if r.get("status") == "error")
        total = len(cfg.profile_ids)
        if errors == total:
            final_status = "error"
        else:
            final_status = "done"

        await dbmod.update_campaign_run(
            run_id,
            tenant_id=cfg.tenant_id,
            status=final_status,
            results=results,
            db_path=db_path,
        )
        logger.info(
            "campaign run=%s finished: %s (%d/%d errors)",
            run_id, final_status, errors, total,
        )
    except asyncio.CancelledError:
        await dbmod.update_campaign_run(
            run_id,
            tenant_id=cfg.tenant_id,
            status="cancelled",
            results=results,
            db_path=db_path,
        )
        logger.info("campaign run=%s cancelled", run_id)
    except Exception as exc:
        logger.exception("_campaign_worker run=%s: %s", run_id, exc)
        await dbmod.update_campaign_run(
            run_id,
            tenant_id=cfg.tenant_id,
            status="error",
            results=results,
            error_message=str(exc),
            db_path=db_path,
        )
    finally:
        _active_tasks.pop(run_id, None)


# ── Public API ────────────────────────────────────────────────────────────────

async def start_campaign_run(cfg: CampaignRunConfig) -> dict[str, Any]:
    """
    Валидирует конфиг, создаёт запись в campaign_runs и запускает фоновый воркер.

    Возвращает {"status": "ok", "run_id": int, "profiles_count": int} или {"status": "error", ...}.
    """
    # ── Validation ────────────────────────────────────────────────────────────
    if cfg.preset not in VALID_PRESETS:
        return {
            "status": "error",
            "message": f"Неверный preset: {cfg.preset!r}. Доступны: {sorted(VALID_PRESETS)}",
        }
    if cfg.warmup_intensity not in VALID_INTENSITIES:
        return {
            "status": "error",
            "message": f"Неверная интенсивность: {cfg.warmup_intensity!r}. Доступны: {sorted(VALID_INTENSITIES)}",
        }
    if not cfg.profile_ids:
        return {"status": "error", "message": "Список профилей пуст"}
    if cfg.preset in ("upload_only", "full") and not cfg.video_path:
        return {
            "status": "error",
            "message": "video_path обязателен для preset upload_only и full",
        }
    if cfg.video_path and not Path(cfg.video_path).exists():
        return {"status": "error", "message": f"Файл видео не найден: {cfg.video_path}"}

    # ── Create DB record ──────────────────────────────────────────────────────
    create_res = await dbmod.create_campaign_run(
        tenant_id=cfg.tenant_id,
        preset=cfg.preset,
        profile_ids=cfg.profile_ids,
        video_path=cfg.video_path,
        niche=cfg.niche,
        warmup_intensity=cfg.warmup_intensity,
        concurrency=cfg.concurrency,
        campaign_id=cfg.campaign_id,
        db_path=cfg.db_path,
    )
    if create_res.get("status") != "ok":
        return create_res

    run_id: int = create_res["id"]

    # ── Spawn asyncio task ────────────────────────────────────────────────────
    task = asyncio.create_task(
        _campaign_worker(run_id, cfg),
        name=f"campaign_run_{run_id}",
    )
    _active_tasks[run_id] = task
    logger.info(
        "campaign run=%s started: preset=%s profiles=%d concurrency=%d",
        run_id, cfg.preset, len(cfg.profile_ids), cfg.concurrency,
    )
    return {
        "status": "ok",
        "run_id": run_id,
        "profiles_count": len(cfg.profile_ids),
    }


async def cancel_campaign_run(
    run_id: int,
    tenant_id: str = "default",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """
    Отменяет запущенный воркер. Если воркер уже завершился — просто помечает в БД.
    """
    # Важно: сначала проверяем принадлежность run к tenant.
    run_res = await dbmod.get_campaign_run(run_id, tenant_id=tenant_id, db_path=db_path)
    if run_res.get("status") != "ok":
        return {"status": "error", "message": run_res.get("message", "run not found")}

    task = _active_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Страхуемся: если воркер не успел выставить статус, выставляем сами.
        run_res_after = await dbmod.get_campaign_run(run_id, tenant_id=tenant_id, db_path=db_path)
        if run_res_after.get("status") == "ok":
            cur = str(run_res_after["run"].get("status") or "").strip().lower()
            if cur == "running":
                await dbmod.update_campaign_run(
                    run_id, tenant_id=tenant_id, status="cancelled", db_path=db_path
                )
        return {"status": "ok", "run_id": run_id, "cancelled": True}

    # Воркер уже завершился — принудительно обновляем статус в БД
    await dbmod.update_campaign_run(
        run_id, tenant_id=tenant_id, status="cancelled", db_path=db_path
    )
    return {"status": "ok", "run_id": run_id, "cancelled": False, "note": "задача уже завершена"}


def get_active_runs() -> list[int]:
    """Список run_id активных (незавершённых) воркеров."""
    return [rid for rid, t in _active_tasks.items() if not t.done()]
