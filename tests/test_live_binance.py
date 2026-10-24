"""Live checks against the real Binance API. Run: pytest -m live"""
import pytest

from airdrop_scout import binance_feed as bf

pytestmark = pytest.mark.live


def test_live_list_and_detail():
    rows, errors = bf.scan(7)
    assert rows, f"no campaigns in 7 days? errors={errors}"
    d = bf.fetch_detail(rows[0]["url"])
    assert d["title"] and len(d["text"]) > 200


def test_live_tools(tmp_path, monkeypatch):
    from airdrop_scout import tools
    from airdrop_scout.memory import SeenStore
    monkeypatch.setattr(tools, "SEEN", SeenStore(tmp_path / "seen.json"))
    listing = tools.list_recent_campaigns(days=7)
    assert listing["total"] > 0
    detail = tools.fetch_campaign_details(url_or_code=listing["campaigns"][0]["code"])
    assert "error" not in detail and detail["text_chunks"]
