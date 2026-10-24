from openminion import Agent

from airdrop_scout import tools as T
from airdrop_scout.tools import (
    AGENT_TOOLS, check_seen, chunk_text, eligibility_lines, fetch_campaign_details,
    list_recent_campaigns, mark_seen,
)


def test_list_recent_campaigns_offline(offline_tools):
    out = list_recent_campaigns(days=2)
    assert out["days"] == 2 and out["total"] == len(out["campaigns"]) > 0
    assert out["next_offset"] is None
    assert all(c["seen"] is False for c in out["campaigns"])
    assert out["errors"]
    mark_seen(out["campaigns"][0]["code"])
    assert list_recent_campaigns(days=2)["campaigns"][0]["seen"] is True


def test_list_paging_respects_16_item_limit(offline_tools, monkeypatch):
    out = list_recent_campaigns(days=14)
    assert len(out["campaigns"]) <= 15
    if out["total"] > 15:
        nxt = list_recent_campaigns(days=14, offset=out["next_offset"])
        assert nxt["offset"] == 15
        assert {c["code"] for c in nxt["campaigns"]}.isdisjoint({c["code"] for c in out["campaigns"]})


def test_list_days_is_clamped(offline_tools):
    assert list_recent_campaigns(days=999)["days"] == 14
    assert list_recent_campaigns(days=0)["days"] == 1


def test_fetch_campaign_details_offline(offline_tools):
    url = "https://www.binance.com/en/support/announcement/detail/c453734d8dcc42d9af49c8f0627d67f7"
    d = fetch_campaign_details(url_or_code=url, max_chars=800)
    assert d["code"] == "c453734d8dcc42d9af49c8f0627d67f7"
    assert sum(len(c) for c in d["text_chunks"]) <= 800 and d["truncated"] is True
    assert {"utc": "2026-11-20 00:00", "wat": "2026-11-20 01:00 WAT"} in d["times"]
    assert any("0.01 RLUSD" in line for line in d["eligibility_lines"])
    assert d["mentions_nigeria"] is False


def test_fetch_output_fits_openminion_compaction_limits(offline_tools):
    d = fetch_campaign_details(url_or_code="c453734d8dcc42d9af49c8f0627d67f7", max_chars=50000)
    assert len(d) <= 16
    for v in d.values():
        if isinstance(v, str):
            assert len(v) <= 1200
        if isinstance(v, list):
            assert len(v) <= 16
            assert all(len(x) <= 1200 for x in v if isinstance(x, str))
    assert len(d["text_chunks"]) == T.MAX_CHUNKS  # long announcement -> full 14 chunks
    assert "Campaign Period" in d["text_chunks"][0]


def test_chunk_text_boundaries():
    text = "\n".join(["x" * 500] * 5 + ["y" * 2500])
    chunks = chunk_text(text, size=1100, max_chunks=50)
    assert all(len(c) <= 1100 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")


def test_fetch_campaign_details_bad_input_returns_error(offline_tools):
    assert "error" in fetch_campaign_details(url_or_code="not a link")


def test_seen_roundtrip(offline_tools):
    assert check_seen(code="abc")["seen"] is False
    assert mark_seen(code="abc")["added"] is True
    assert mark_seen(code="abc")["added"] is False
    assert check_seen(code="abc")["seen"] is True


def test_eligibility_lines_picks_region_lines():
    text = "Intro\nUsers in Nigeria are not eligible.\nHave fun\nMinimum hold 1 USDT"
    assert eligibility_lines(text) == ["Users in Nigeria are not eligible.", "Minimum hold 1 USDT"]


def test_agent_accepts_decorated_tools_without_runtime():
    # Public contract: Agent(tools=[decorated fns]) is accepted; runtime is lazy.
    agent = Agent(tools=AGENT_TOOLS, session_id="t")
    assert agent.tools == ["list_recent_campaigns", "fetch_campaign_details", "check_seen"]
    agent.close()
