"""Repro (openminion 0.1.10) for several SDK rough edges, observed by pointing
an Agent at a local scripted OpenAI-compatible server (no API key needed).

A. Agent(instructions=...) is truncated (~640-890 chars, "...[truncated]") in
   the [IDENTITY] system block; the docs do not mention a limit.
B. output_type= is validation-only: the JSON schema of the Pydantic model is
   never sent to the model; the runtime's own [TOOL RESULT FORMAT] block even
   says "Never expose raw JSON".
C. Tool outputs are compacted before the model sees them: every string is cut
   at 1200 chars, lists/dicts at 16 items (modules/brain/constants.py
   TOOL_MESSAGE_*). A tool returning one long string is silently cut. Dict
   returns are also duplicated into a JSON "summary" string.
D. AgentRunResult.text is "<agent name>: <reply>" (postprocess_response.py),
   so output_type only validates thanks to the _extract_json_object fallback.
E. AgentRunResult.stats["llm_calls"] (and token counts) under-report: one
   Agent.run issues several provider requests (decide, freshness, finalization,
   judge ...) but stats report llm_calls=1.

Run: python repro/repro_runtime_rough_edges.py
"""
import json

from pydantic import BaseModel

import _mockenv
from openminion import Agent, tool

LONG = "x" * 5000


@tool
def long_text() -> str:
    """Return a 5000-character string."""
    return LONG


class Out(BaseModel):
    answer: str


llm, srv, cfg = _mockenv.setup(lambda msgs: {"answer": "done"}, first_tool=("long_text", {}))
instructions = "You are a careful assistant. " + " ".join(f"Rule {i}: be precise." for i in range(80))
with Agent(config_path=cfg, instructions=instructions, output_type=Out,
           tools=[long_text], session_id="repro-edges") as agent:
    r = agent.run("Call long_text and answer.", timeout_seconds=60)
srv.shutdown()

systems = [m["content"] for q in llm.requests for m in q["messages"] if m["role"] == "system"]
ident = next(s for s in systems if "[IDENTITY]" in s)
ident = ident[ident.index("[IDENTITY]"):ident.index("You are the agent described above")]
print(f"A. instructions sent: {len(instructions)} chars; identity block: {len(ident)} chars; "
      f"truncated={'[truncated]' in ident}")
print(f"B. 'answer' schema present in any request: {any('\"answer\"' in json.dumps(q) for q in llm.requests[:-1])}; "
      f"'Never expose raw JSON' present: {any('Never expose raw JSON' in s for s in systems)}")
tool_msgs = [m["content"] for q in llm.requests for m in q["messages"] if m["role"] == "tool"]
body = json.loads(tool_msgs[0])
seen = body["outputs"]["data"]
print(f"C. tool returned {len(LONG)} chars; model saw {len(seen)} chars ending {seen[-16:]!r}")
print(f"D. result.text = {r.text!r}  output = {r.output!r}")
print(f"E. provider requests = {len(llm.requests)}; stats.llm_calls = {r.stats.get('llm_calls')}; "
      f"stats.input_tokens = {r.stats.get('input_tokens')} (mock reported 10/request)")
