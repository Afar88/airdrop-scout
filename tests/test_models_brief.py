from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from airdrop_scout.brief import render
from airdrop_scout.models import ScoutReport, schema_hint

SAMPLE = {
    "summary": "One cheap campaign worth doing.",
    "campaigns": [
        {"code": "a" * 32, "title": "Trade to win", "url": "https://x/a", "verdict": "SKIP",
         "est_cost_usd": None, "needs_trading_volume": True, "nigeria": "unclear",
         "reason": "Needs trading volume."},
        {"code": "b" * 32, "title": "Hold RLUSD", "url": "https://x/b", "verdict": "DO_IT",
         "est_cost_usd": 0.01, "needs_trading_volume": False, "nigeria": "available",
         "steps": ["Hold 0.01 RLUSD in Spot"], "reward": "600,000 XRP pool",
         "deadline_utc": "2026-11-20 00:00", "red_flags": ["weekly APR set by Binance"],
         "reason": "Only 0.01 RLUSD needed."},
    ],
}


def test_report_validates_from_json():
    import json
    r = ScoutReport.model_validate_json(json.dumps(SAMPLE))
    assert r.campaigns[1].verdict == "DO_IT"


def test_report_rejects_bad_verdict():
    bad = {**SAMPLE, "campaigns": [{**SAMPLE["campaigns"][0], "verdict": "YOLO"}]}
    with pytest.raises(ValidationError):
        ScoutReport.model_validate(bad)


def test_schema_hint_is_compact_json():
    s = schema_hint()
    assert '"verdict"' in s and "\n" not in s


def test_render_brief_wat_and_sections():
    md = render(ScoutReport.model_validate(SAMPLE), provider="mock",
                now=datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc))
    assert "_Generated 2026-10-23 22:00 WAT · model: mock_" in md
    assert "**Deadline:** 2026-11-20 01:00 WAT" in md
    assert md.index("DO IT") < md.index("## Skipped")
    assert "Trade to win" in md.split("## Skipped")[1]
    assert "1. Hold 0.01 RLUSD in Spot" in md


def test_render_empty():
    md = render(ScoutReport(summary="Quiet day.", campaigns=[]))
    assert "Nothing new today." in md
