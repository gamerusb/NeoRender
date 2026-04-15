from __future__ import annotations

from core import analytics_advisor as adv


def test_build_recommendations_marks_shadowban_with_steps():
    rows = [
        {
            "id": 10,
            "video_url": "https://youtu.be/a",
            "views": 0,
            "likes": 0,
            "status": "shadowban",
            "published_at": "2026-03-30T10:00:00+00:00",
        }
    ]
    out = adv.build_recommendations(rows)
    assert len(out) == 1
    r = out[0]
    assert r["status"] == "shadowban"
    assert r["health_score"] <= 40
    assert any("дистрибуц" in s.lower() or "shadowban" in s.lower() for s in r["diagnosis"])
    assert len(r["next_steps"]) >= 2


def test_build_recommendations_detects_low_engagement():
    rows = [
        {"id": 1, "video_url": "u1", "views": 5000, "likes": 20, "status": "active"},
        {"id": 2, "video_url": "u2", "views": 4500, "likes": 15, "status": "active"},
    ]
    out = adv.build_recommendations(rows)
    r = out[0]
    assert r["like_rate"] < 1.0
    assert any("вовлеч" in s.lower() for s in r["diagnosis"])

