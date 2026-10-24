"""Shared helper: start the scripted OpenAI-compatible server from tests/ and
write an isolated OpenMinion config pointing at it (no API key needed)."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from mock_openai import ScriptedLLM, serve  # noqa: E402


def setup(final_fn=lambda msgs: {"ok": True}, **kw):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    home = tempfile.mkdtemp(prefix="om-repro-")
    os.environ["OPENMINION_HOME"] = home
    os.environ["OPENMINION_DATA_ROOT"] = os.path.join(home, ".openminion")
    os.environ["MOCK_KEY"] = "mock"
    llm = ScriptedLLM(final_fn, **kw)
    srv, url = serve(llm)
    cfg = {
        "default_agent": "a",
        "agents": {"a": {"name": "a", "provider": "openai", "default_channel": "console"}},
        "providers": {"openai": {"model": "mock-model", "base_url": url, "api_key_env": "MOCK_KEY"}},
        "runtime": {"memory_enabled": False},
    }
    path = os.path.join(home, "agents.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    return llm, srv, path
