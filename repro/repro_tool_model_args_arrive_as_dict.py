"""Repro (openminion 0.1.12 and dev 73ef9a38): a @tool argument typed as a
Pydantic model (or a dataclass) reaches the function as a plain dict.

@tool builds an args model from the signature, and the schema the model sees
correctly describes `f` as an object with typed fields. The runtime validates
the model's arguments against that args model, but then passes on
`model_dump()` (runtime validate_model_tool_args) and the decorator's
_handler splats a dict again (`args.model_dump()` / `dict(args)`). Nested
BaseModel / dataclass values are therefore dumped to dicts, so
`f.chain` / `f.describe()` raise AttributeError. Agent.run() does not raise:
the tool comes back to the model as a generic "Tool execution failed"
(EXEC_ERROR, error_type=AttributeError), so the agent quietly loses the tool.

No model provider or API key needed: it uses a local scripted
OpenAI-compatible server (tests/mock_openai.py) that asks for the tool once.

Run: python repro/repro_tool_model_args_arrive_as_dict.py
"""
import json
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel

import _mockenv
from openminion import Agent, tool


class Chain(str, Enum):
    solana = "solana"
    ethereum = "ethereum"


class Filter(BaseModel):
    chain: Chain
    min_score: int = 0


@dataclass
class Window:
    days: int


SEEN = {}


@tool(idempotent=True, min_scope="READ_ONLY")
def scan_campaigns(f: Filter, window: Window) -> str:
    """Scan airdrop campaigns matching a filter within a time window."""
    SEEN["f"], SEEN["window"] = type(f).__name__, type(window).__name__
    return f"{f.chain.value} >= {f.min_score} over {window.days}d"


# 1. Direct, no runtime: what the handler hands the function.
model = scan_campaigns.tool_args_model.model_validate(
    {"f": {"chain": "solana", "min_score": 3}, "window": {"days": 7}})
try:
    print("handler(validated model) ->", scan_campaigns.tool_decl.handler(model))
except AttributeError as exc:
    print(f"handler(validated model) -> AttributeError: {exc}   types seen: {SEEN}")

# 2. End to end through Agent.run.
SEEN.clear()
args = {"f": {"chain": "solana", "min_score": 3}, "window": {"days": 7}}
llm, srv, cfg = _mockenv.setup(first_tool=("scan_campaigns", args))
with Agent(config_path=cfg, tools=[scan_campaigns], session_id="repro-model-args") as agent:
    r = agent.run("scan campaigns", timeout_seconds=60)
srv.shutdown()

tools = next(q["tools"] for q in llm.requests if any(
    t["function"]["name"] == "scan_campaigns" for t in q.get("tools") or []))
schema = next(t["function"]["parameters"] for t in tools if t["function"]["name"] == "scan_campaigns")
tool_msg = next(m["content"] for q in llm.requests for m in q["messages"] if m["role"] == "tool")
env = json.loads(tool_msg)
print("schema sent for f:", sorted((schema.get("$defs") or {}).get("Filter", {}).get("properties", {})))
print("types the tool function received:", SEEN)
print("tool result the model saw:", env.get("status"), env.get("summary"),
      (env.get("error") or {}).get("code"), (env.get("error") or {}).get("details"))
print(f"run_state={r.run_state!r}")
