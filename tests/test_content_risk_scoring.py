from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from core import content_scraper as cs


def test_enrich_video_risk_adds_standard_fields():
    video = {
        "id": "v1",
        "title": "Aviator x100 big win link in bio",
        "description": "promo code in profile",
        "channel": "WinCash999",
        "url": "https://www.youtube.com/shorts/v1",
        "source": "youtube",
    }
    out = cs.enrich_video_risk(video, query_patterns=["aviator big win shorts"], watchlist_hit=True)
    assert isinstance(out.get("risk_score"), int)
    assert out.get("risk_tier") in {"low", "medium", "high"}
    assert isinstance(out.get("risk_confidence"), float)
    assert isinstance(out.get("risk_signals"), list)
    assert isinstance(out.get("risk_signal_map"), dict)
    assert "ubt_mask_score" in out
    assert "ubt_flags" in out


def test_risk_golden_set_regression():
    dataset = Path(__file__).resolve().parent / "data" / "risk_golden_set.json"
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    for i, row in enumerate(rows):
        out = cs.enrich_video_risk(
            {
                "id": f"golden-{i}",
                "title": row.get("title", ""),
                "description": row.get("description", ""),
                "channel": row.get("channel", ""),
                "url": f"https://example.test/{i}",
                "source": "youtube",
            }
        )
        expected = str(row.get("expected_tier") or "low")
        if expected == "high":
            assert out["risk_score"] >= 50
        elif expected == "medium":
            assert out["risk_score"] >= 35
        else:
            assert out["risk_score"] < 65


def test_risk_label_and_telemetry_endpoints():
    client = TestClient(api_server.app)
    label_resp = client.post(
        "/api/research/risk-label",
        headers={"X-Tenant-ID": "default"},
        json={
            "video_id": "vid-1",
            "url": "https://youtube.com/shorts/vid-1",
            "source": "youtube",
            "label": "likely_ubt",
            "risk_score": 82,
        },
    )
    assert label_resp.status_code == 200
    assert label_resp.json().get("status") == "ok"

    tel = client.get("/api/research/risk-telemetry", headers={"X-Tenant-ID": "default"})
    assert tel.status_code == 200
    body = tel.json()
    assert body.get("status") == "ok"
    assert isinstance(body.get("tier_counts"), dict)
    assert isinstance(body.get("top_signals"), list)
    assert isinstance(body.get("label_counts"), dict)
