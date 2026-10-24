"""Repro (openminion 0.1.10): the documented minimal config fails from the SDK.

Docs (getting-started/configuration, "Minimal config") show:
  {"default_agent":"default","agents":{"default":{"name":"default","provider":"echo"}}}
Passing that file to Agent(config_path=...) raises
  RuntimeError: inbound authenticity denied (reason=invalid_channel, mode=warn)
because the agent has no default_channel, so the gateway sees an empty
channel. The error is a bare RuntimeError (not a public exception type) and
says mode=warn while still denying. Adding "default_channel": "console"
(what `openminion setup` writes) makes it pass.

Side effect: the denied turn still persists the session with channel ''. Re-using
that session id after fixing the config fails with
  ValueError: Session 'repro' belongs to channel '', not 'console'
so the failed turn poisons the session id.

Run: python repro/repro_minimal_config_channel.py   (no API key needed)
"""
import json
import os
import tempfile

from openminion import Agent

home = tempfile.mkdtemp(prefix="om-repro-")
os.environ["OPENMINION_HOME"] = home
os.environ["OPENMINION_DATA_ROOT"] = os.path.join(home, ".openminion")

def write(name, agent_cfg):
    path = os.path.join(home, name)
    with open(path, "w") as f:
        json.dump({"default_agent": "default", "agents": {"default": agent_cfg}}, f)
    return path


def attempt(label, path, session):
    try:
        with Agent(config_path=path, session_id=session) as agent:
            print(f"{label}: OK -> {agent.run('hello', timeout_seconds=30).text!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: {type(exc).__name__}: {exc}")


minimal = write("minimal.json", {"name": "default", "provider": "echo"})
fixed = write("fixed.json", {"name": "default", "provider": "echo", "default_channel": "console"})
attempt("1. documented minimal config, session s1", minimal, "s1")
attempt("2. + default_channel=console, fresh session s2", fixed, "s2")
attempt("3. + default_channel=console, re-using s1", fixed, "s1")
