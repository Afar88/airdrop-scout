"""Integration: a real openminion Agent (0.1.10) drives our decorated tools
against a local scripted OpenAI-compatible endpoint. Proves config wiring,
run-scoped tool registration, the tool-call loop, typed output and the three
documented failure types — without any API key or network."""
import json

import pytest

from mock_openai import ScriptedLLM, serve, unwrap_tool_content

pytestmark = pytest.mark.integration


def honest_final(msgs):
    """Build the final report only from what the tools actually returned."""
    listing, details = None, {}
    for m in msgs:
        if m.get("role") != "tool":
            continue
        data = unwrap_tool_content(m.get("content"))
        if "campaigns" in data:
            listing = data
        elif "code" in data:
            details[data["code"]] = data
    campaigns = []
    for c in (listing or {}).get("campaigns", []):
        d = details.get(c["code"])
        campaigns.append({
            "code": c["code"], "title": c["title"], "url": c["url"],
            "verdict": "SKIP" if c["keyword_hint"] == "PAID" else "MAYBE",
            "est_cost_usd": None, "needs_trading_volume": c["keyword_hint"] == "PAID",
            "nigeria": "unclear", "steps": [], "reward": "",
            "deadline_utc": (d["times"][-1]["utc"] if d and d.get("times") else ""),
            "red_flags": [], "reason": "scripted",
        })
    return {"summary": f"{len(campaigns)} campaigns reviewed.", "campaigns": campaigns}


@pytest.fixture
def mock_env(tmp_path, monkeypatch, offline_tools):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("OPENMINION_HOME", str(tmp_path))
    monkeypatch.setenv("OPENMINION_DATA_ROOT", str(tmp_path / ".openminion"))
    monkeypatch.setenv("SCOUT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")

    def start(**kw):
        llm = ScriptedLLM(honest_final, **kw)
        srv, url = serve(llm)
        monkeypatch.setenv("SCOUT_BASE_URL", url)
        from airdrop_scout.config import choose_provider
        return llm, srv, choose_provider()

    servers = []
    yield lambda **kw: (servers.append(start(**kw)) or servers[-1])
    for _, srv, _ in servers:
        srv.shutdown()


def test_full_loop_success(mock_env, tmp_path):
    from airdrop_scout.agent import run_scout
    llm, _, choice = mock_env()
    res = run_scout(choice, config_dir=tmp_path / ".openminion", days=2, timeout_seconds=60,
                    session_id="test-success")
    assert res.ok, res.error
    assert res.session_id == "test-success"
    called = [tc["function"]["name"] for r in llm.requests
              for m in r.get("messages", []) if m.get("role") == "assistant"
              for tc in (m.get("tool_calls") or [])]
    assert "list_recent_campaigns" in called and "fetch_campaign_details" in called
    assert res.report.campaigns and all(len(c.code) == 32 for c in res.report.campaigns)
    # our decorated tools reached the provider with real JSON-schema parameters
    tool_specs = {t["function"]["name"]: t["function"]["parameters"]
                  for r in llm.requests for t in (r.get("tools") or [])}
    assert "url_or_code" in tool_specs["fetch_campaign_details"]["properties"]
    # the run message (not the truncated identity block) carries the schema
    first_user = next(m["content"] for m in llm.requests[0]["messages"] if m["role"] == "user")
    assert '"CampaignVerdict"' in first_user


def test_provider_error_is_typed(mock_env, tmp_path):
    from airdrop_scout.agent import run_scout
    _, _, choice = mock_env(mode="auth_error")
    res = run_scout(choice, config_dir=tmp_path / ".openminion", timeout_seconds=60)
    assert not res.ok and res.error_kind == "provider"
    assert "AUTH_ERROR" in res.error


def test_turn_timeout_is_typed(mock_env, tmp_path):
    from airdrop_scout.agent import run_scout
    _, _, choice = mock_env(delay=6)
    res = run_scout(choice, config_dir=tmp_path / ".openminion", timeout_seconds=2)
    assert not res.ok and res.error_kind == "timeout", (res.error_kind, res.error)


def test_bad_json_is_validation_error(mock_env, tmp_path):
    from airdrop_scout.agent import run_scout
    _, _, choice = mock_env(mode="bad_json")
    res = run_scout(choice, config_dir=tmp_path / ".openminion", timeout_seconds=60)
    assert not res.ok and res.error_kind == "validation"
    assert "no JSON" in res.raw_text
