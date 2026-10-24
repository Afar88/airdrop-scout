from airdrop_scout.timeutil import find_utc_times, utc_to_wat
from airdrop_scout import binance_feed as bf
from conftest import load


def test_utc_to_wat_basic_and_rollover():
    assert utc_to_wat("2026-11-20 00:00") == "2026-11-20 01:00 WAT"
    assert utc_to_wat("2026-10-31 23:30 (UTC)") == "2026-11-01 00:30 WAT"
    assert utc_to_wat("2026-12-31") == "2026-12-31 01:00 WAT"


def test_utc_to_wat_unknown_is_blank():
    for v in ("", None, "unknown", "N/A", "soon"):
        assert utc_to_wat(v) == ""


def test_find_utc_times_fixture():
    text = bf.flatten_body(load("detail_rlusd.json")["data"]["body"])
    times = find_utc_times(text)
    utcs = [t["utc"] for t in times]
    assert "2026-10-23 00:00" in utcs and "2026-11-20 00:00" in utcs
    assert len(utcs) == len(set(utcs))
    assert {"utc": "2026-11-20 00:00", "wat": "2026-11-20 01:00 WAT"} in times
