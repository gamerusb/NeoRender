from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

try:
    from . import database as dbmod
    from .campaign_runner import CampaignRunConfig, start_campaign_run
except ImportError:
    from core import database as dbmod
    from core.campaign_runner import CampaignRunConfig, start_campaign_run

logger = logging.getLogger(__name__)


@dataclass
class CookieFarmerConfig:
    tenant_id: str = "default"
    interval_sec: int = 1800
    batch_size: int = 5
    warmup_intensity: str = "light"
    niche: str = "general"
    adspower_api_url: str = "http://127.0.0.1:50325"


_tasks: dict[str, asyncio.Task[None]] = {}
_states: dict[str, dict[str, Any]] = {}


async def _run_cycle(cfg: CookieFarmerConfig) -> dict[str, Any]:
    profiles_res = await dbmod.list_adspower_profiles(tenant_id=cfg.tenant_id)
    if profiles_res.get("status") != "ok":
        return {"status": "error", "message": profiles_res.get("message", "list profiles failed")}

    profiles = profiles_res.get("profiles") or []
    active = [p for p in profiles if str(p.get("status", "")).lower() in {"ready", "active", "new"}]
    if not active:
        return {"status": "ok", "message": "no profiles to farm", "started": 0}

    profile_ids = [str(p.get("adspower_profile_id", "")).strip() for p in active]
    profile_ids = [pid for pid in profile_ids if pid][: max(1, cfg.batch_size)]
    if not profile_ids:
        return {"status": "ok", "message": "no profile ids", "started": 0}

    run = await start_campaign_run(
        CampaignRunConfig(
            preset="farm_cookies",
            profile_ids=profile_ids,
            tenant_id=cfg.tenant_id,
            niche=cfg.niche,
            warmup_intensity=cfg.warmup_intensity,
            concurrency=min(len(profile_ids), max(1, cfg.batch_size)),
            adspower_api_url=cfg.adspower_api_url,
        )
    )
    return run


def _tenant_state(tenant_id: str) -> dict[str, Any]:
    st = _states.get(tenant_id)
    if st is None:
        st = {
            "running": False,
            "last_run_id": None,
            "last_error": None,
            "cycles": 0,
            "tenant_id": tenant_id,
        }
        _states[tenant_id] = st
    return st


async def _worker(cfg: CookieFarmerConfig) -> None:
    state = _tenant_state(cfg.tenant_id)
    state["running"] = True
    state["tenant_id"] = cfg.tenant_id
    try:
        while True:
            last_run_id = state.get("last_run_id")
            if isinstance(last_run_id, int):
                run_res = await dbmod.get_campaign_run(last_run_id, tenant_id=cfg.tenant_id)
                if run_res.get("status") == "ok":
                    run_status = str(run_res["run"].get("status") or "").strip().lower()
                    if run_status == "running":
                        state["last_error"] = f"skip overlap: run {last_run_id} still running"
                        await asyncio.sleep(max(30, int(cfg.interval_sec)))
                        continue
            res = await _run_cycle(cfg)
            state["cycles"] = int(state.get("cycles") or 0) + 1
            if res.get("status") == "ok":
                if res.get("run_id") is not None:
                    state["last_run_id"] = res.get("run_id")
                state["last_error"] = None
            else:
                state["last_error"] = res.get("message", "unknown error")
                logger.warning("cookie_farmer cycle error: %s", state["last_error"])
            await asyncio.sleep(max(30, int(cfg.interval_sec)))
    except asyncio.CancelledError:
        logger.info("cookie_farmer stopped")
        raise
    except Exception as exc:
        logger.exception("cookie_farmer worker failed: %s", exc)
        state["last_error"] = str(exc)
    finally:
        state["running"] = False


def get_status(tenant_id: str = "default") -> dict[str, Any]:
    state = _tenant_state(tenant_id)
    task = _tasks.get(tenant_id)
    alive = task is not None and not task.done()
    return {**state, "running": alive}


async def start(cfg: CookieFarmerConfig) -> dict[str, Any]:
    task = _tasks.get(cfg.tenant_id)
    if task is not None and not task.done():
        return {"status": "ok", "message": "already running", "state": get_status(cfg.tenant_id)}
    _tasks[cfg.tenant_id] = asyncio.create_task(_worker(cfg), name=f"cookie_farmer_{cfg.tenant_id}")
    return {"status": "ok", "message": "started", "state": get_status(cfg.tenant_id)}


async def stop(tenant_id: str = "default") -> dict[str, Any]:
    state = _tenant_state(tenant_id)
    task = _tasks.get(tenant_id)
    if task is None or task.done():
        state["running"] = False
        return {"status": "ok", "message": "already stopped", "state": get_status(tenant_id)}
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    _tasks.pop(tenant_id, None)
    state["running"] = False
    return {"status": "ok", "message": "stopped", "state": get_status(tenant_id)}

