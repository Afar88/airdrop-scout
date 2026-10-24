import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load(name):
    return json.loads((FIX / name).read_text())


def fake_opener(url: str):
    if "article/detail" in url:
        return load("detail_rlusd.json")
    if "catalogId=93" in url:
        return load("list_93.json")
    if "catalogId=128" in url:
        raise OSError("simulated network failure")
    return {"data": {"catalogs": [{"articles": []}]}}


# Fixture list was captured 2026-10-23 ~21:12 UTC; pin "now" to that.
FIXTURE_NOW = 1792789920.0


@pytest.fixture
def offline_tools(tmp_path, monkeypatch):
    from airdrop_scout import binance_feed, tools
    from airdrop_scout.memory import SeenStore

    monkeypatch.setattr(tools, "OPENER", fake_opener)
    monkeypatch.setattr(tools, "SEEN", SeenStore(tmp_path / "seen.json"))
    real_scan = binance_feed.scan
    monkeypatch.setattr(binance_feed, "scan",
                        lambda days, opener=None, now=None: real_scan(days, opener=opener, now=FIXTURE_NOW))
    return tools
