"""Repro (openminion 0.1.10 and dev 367aa481): an internal runtime error comes
back as a normal reply with run_state="completed".

A @tool that returns a non-JSON-serializable object makes the brain hit
"State machine error: RUNTIME_ERROR ...". Agent.run() does not raise; it
returns AgentRunResult(run_state="completed", text="a: State machine error ...")
with no structured error field, so callers treat the failure as the answer.

No model provider or API key needed: it uses a local scripted
OpenAI-compatible server (tests/mock_openai.py) that asks for the tool once.

Run: python repro/repro_run_state_completed_on_error.py
"""
import _mockenv
from openminion import Agent, tool


class NotJSON:
    pass


@tool(idempotent=True, min_scope="READ_ONLY")
def bad_return() -> str:
    """Returns an object that cannot be JSON-serialized."""
    return NotJSON()  # type: ignore[return-value]


@tool(idempotent=True, min_scope="READ_ONLY")
def raises() -> str:
    """Raises inside the tool."""
    raise RuntimeError("tool exploded")


for t in (bad_return, raises):
    llm, srv, cfg = _mockenv.setup(first_tool=(t.__name__, {}))
    with Agent(config_path=cfg, tools=[t], session_id=f"repro-{t.__name__}") as agent:
        r = agent.run("call the tool", timeout_seconds=60)
    srv.shutdown()
    print(f"{t.__name__}: run_state={r.run_state!r} text={r.text[:120]!r}")
