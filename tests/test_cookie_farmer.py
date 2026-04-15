from __future__ import annotations

import asyncio

import pytest

from core import cookie_farmer as cf


@pytest.mark.asyncio
async def test_cookie_farmer_tenant_scoped_start_stop(monkeypatch: pytest.MonkeyPatch):
    async def _fake_run_cycle(_cfg):
        return {"status": "ok", "run_id": 123}

    monkeypatch.setattr(cf, "_run_cycle", _fake_run_cycle)
    r1 = await cf.start(cf.CookieFarmerConfig(tenant_id="t1", interval_sec=30))
    r2 = await cf.start(cf.CookieFarmerConfig(tenant_id="t2", interval_sec=30))
    assert r1.get("status") == "ok"
    assert r2.get("status") == "ok"
    s1 = cf.get_status("t1")
    s2 = cf.get_status("t2")
    assert s1.get("running") is True
    assert s2.get("running") is True
    await cf.stop("t1")
    await cf.stop("t2")


@pytest.mark.asyncio
async def test_cookie_farmer_skips_overlap(monkeypatch: pytest.MonkeyPatch):
    called = {"cycles": 0}

    async def _fake_run_cycle(_cfg):
        called["cycles"] += 1
        return {"status": "ok", "run_id": 777}

    async def _fake_get_campaign_run(run_id: int, tenant_id: str = "default", db_path=None):
        if run_id == 777:
            return {"status": "ok", "run": {"status": "running"}}
        return {"status": "error", "message": "not found"}

    monkeypatch.setattr(cf, "_run_cycle", _fake_run_cycle)
    monkeypatch.setattr(cf.dbmod, "get_campaign_run", _fake_get_campaign_run)
    await cf.start(cf.CookieFarmerConfig(tenant_id="t-overlap", interval_sec=30))
    await asyncio.sleep(0.1)
    await asyncio.sleep(0.1)
    # Первый цикл должен случиться, второй должен пропуститься из-за overlap.
    assert called["cycles"] == 1
    await cf.stop("t-overlap")
