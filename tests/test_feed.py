import pytest

from airdrop_scout import binance_feed as bf
from conftest import FIXTURE_NOW, fake_opener, load


@pytest.mark.parametrize("title,tag", [
    ("Spot Trading Tournament Season 8: Trade to Share Up to 400 BNB", "PAID"),
    ("Hold RLUSD in Any Binance Accounts to Share 600,000 XRP Rewards", "CHEAP"),
    ("Binance Square: Write to Earn and share 5,000 USDC", "FREE"),
    ("Binance Will Add 5 bStocks Tokenized Securities as Collateral", "OTHER"),
    ("Hold BNB and trade to earn", "PAID"),  # PAID wins over CHEAP (radar.py rule)
])
def test_classify_reused_rules(title, tag):
    assert bf.classify(title) == tag


def test_extract_code_from_url_and_raw():
    code = "c453734d8dcc42d9af49c8f0627d67f7"
    assert bf.extract_code(code) == code
    assert bf.extract_code(f"https://www.binance.com/en/support/announcement/detail/{code}?ref=x") == code
    assert bf.extract_code(code.upper()) == code
    with pytest.raises(ValueError):
        bf.extract_code("https://www.binance.com/en/square")


def test_flatten_body_fixture():
    text = bf.flatten_body(load("detail_rlusd.json")["data"]["body"])
    assert "Campaign Period: 2026-10-23 00:00 (UTC) - 2026-11-20 00:00 (UTC)" in text
    assert "&nbsp;" not in text and "\xa0" not in text
    assert "0.01 RLUSD" in text
    assert " | " in text  # tables flattened


def test_flatten_body_empty():
    assert bf.flatten_body(None) == ""
    assert bf.flatten_body("") == ""


def test_scan_cutoff_dedupe_and_errors():
    rows, errors = bf.scan(2, opener=fake_opener, now=FIXTURE_NOW)
    assert rows, "fixture should contain campaigns in the last 2 days"
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    assert all(r["released_utc"] >= "2026-10-21 21:12" for r in rows)
    assert rows == sorted(rows, key=lambda r: r["released_utc"], reverse=True)
    assert any("Airdrop" in e for e in errors)  # catalog 128 failure is reported, not raised
    assert all(r["url"].endswith(r["code"]) for r in rows)


def test_fetch_detail_ok_and_missing():
    d = bf.fetch_detail("c453734d8dcc42d9af49c8f0627d67f7", opener=fake_opener)
    assert d["title"].startswith("Hold RLUSD")
    assert d["catalog"] == "Latest Activities"
    with pytest.raises(LookupError):
        bf.fetch_detail("c453734d8dcc42d9af49c8f0627d67f7",
                        opener=lambda u: {"code": "000000", "data": None, "success": True})
