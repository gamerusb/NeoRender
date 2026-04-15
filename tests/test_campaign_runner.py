from __future__ import annotations

from pathlib import Path

import pytest

from core import campaign_runner as cr
from core import database as db


@pytest.mark.asyncio
async def test_start_campaign_run_validation_empty_profiles(temp_db_path: Path):
    assert (await db.init_db(temp_db_path)).get("status") == "ok"
    res = await cr.start_campaign_run(
        cr.CampaignRunConfig(
            preset="farm_cookies",
            profile_ids=[],
            db_path=temp_db_path,
        )
    )
    assert res.get("status") == "error"


@pytest.mark.asyncio
async def test_start_and_cancel_campaign_run(monkeypatch: pytest.MonkeyPatch, temp_db_path: Path):
    assert (await db.init_db(temp_db_path)).get("status") == "ok"

    async def _fake_run_one_profile(profile_id: str, cfg: cr.CampaignRunConfig):
        return {"profile_id": profile_id, "status": "ok", "steps": {"warmup": {"status": "ok"}}}

    monkeypatch.setattr(cr, "_run_one_profile", _fake_run_one_profile)
    started = await cr.start_campaign_run(
        cr.CampaignRunConfig(
            preset="farm_cookies",
            profile_ids=["p1", "p2"],
            db_path=temp_db_path,
            concurrency=1,
        )
    )
    assert started.get("status") == "ok"
    run_id = int(started["run_id"])
    stopped = await cr.cancel_campaign_run(run_id, db_path=temp_db_path)
    assert stopped.get("status") == "ok"
    got = await db.get_campaign_run(run_id, db_path=temp_db_path)
    assert got.get("status") == "ok"
    assert got["run"]["status"] in {"cancelled", "done", "error"}


@pytest.mark.asyncio
async def test_cancel_campaign_run_rejects_foreign_tenant(monkeypatch: pytest.MonkeyPatch, temp_db_path: Path):
    assert (await db.init_db(temp_db_path)).get("status") == "ok"

    async def _fake_run_one_profile(profile_id: str, cfg: cr.CampaignRunConfig):
        return {"profile_id": profile_id, "status": "ok", "steps": {}}

    monkeypatch.setattr(cr, "_run_one_profile", _fake_run_one_profile)
    started = await cr.start_campaign_run(
        cr.CampaignRunConfig(
            preset="farm_cookies",
            profile_ids=["p1"],
            tenant_id="tenant_a",
            db_path=temp_db_path,
        )
    )
    assert started.get("status") == "ok"
    run_id = int(started["run_id"])
    denied = await cr.cancel_campaign_run(run_id, tenant_id="tenant_b", db_path=temp_db_path)
    assert denied.get("status") == "error"
