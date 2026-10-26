# [0.1.12] @tool arguments typed as a Pydantic model or dataclass reach the function as a plain dict

## Summary
When a `@tool` function has a parameter typed as a Pydantic `BaseModel` (or a dataclass), the function receives a plain `dict` instead of an instance. The tool schema sent to the model correctly describes the object and its typed fields, and the runtime validates the model's arguments against it. Then the validated model is turned back into dicts before the call, so `f.chain` or `f.describe()` raises `AttributeError`. `Agent.run()` does not raise. The model gets a generic `Tool execution failed` (`EXEC_ERROR`, `error_type=AttributeError`), so the agent quietly loses the tool.

Affects openminion 0.1.12 (PyPI) and `dev` at 73ef9a38.

## Repro (no API key; local scripted OpenAI-compatible server)
```python
from dataclasses import dataclass
from enum import Enum
from pydantic import BaseModel
from openminion import tool

class Chain(str, Enum):
    solana = "solana"

class Filter(BaseModel):
    chain: Chain
    min_score: int = 0

@dataclass
class Window:
    days: int

@tool
def scan_campaigns(f: Filter, window: Window) -> str:
    """Scan campaigns."""
    return f"{f.chain.value} >= {f.min_score} over {window.days}d"

args = scan_campaigns.tool_args_model.model_validate(
    {"f": {"chain": "solana", "min_score": 3}, "window": {"days": 7}})
scan_campaigns.tool_decl.handler(args)
# AttributeError: 'dict' object has no attribute 'chain'
```
The same thing happens end to end through `Agent(tools=[scan_campaigns]).run(...)`. A full script with a scripted model is in the linked PR.

**Expected:** `f` is a `Filter` instance and `window` is a `Window` instance. The handler returns `solana >= 3 over 7d`, and the model sees a successful tool result.

**Actual:** both arrive as `dict`. The tool raises `AttributeError`, and the model sees:
`{"status": "failed", "summary": "Tool execution failed", "error": {"code": "EXEC_ERROR", "details": {"error_type": "AttributeError"}}}`.
Meanwhile `run_state` is still `"completed"`.

## Root cause
- `src/openminion/tools/decorator.py`, `_decorate._handler` (lines 159-160 in 0.1.12):
  `values = args.model_dump() if isinstance(args, BaseModel) else dict(args); return func(**values)`.
  `model_dump()` recursively converts nested models and dataclasses into dicts.
- In the brain path, the handler never gets the model anyway: `modules/tool/runtime/argument_repair.py:173` (`validate_model_tool_args`) returns `args_model.model_validate(repaired).model_dump()`. `modules/brain/adapters/tool/results.py:174` then calls `spec.handler(validated_args, context)` with that dumped mapping, and `dict(args)` passes the nested dicts straight through. The MCP published server (`tools/mcp/server/published.py:81`) also passes a raw mapping.

Scalars, `Optional`, `list[str]`, `date` and `Enum` args look fine because `model_dump()` (python mode) keeps them. Only structured args, which are what typed agent tools tend to use, break.

## Proposed fix
In the decorator's `_handler`, use the args-model instance when one is given. Otherwise re-validate the mapping with `args_model`, then pass `getattr(validated, name)` for each field instead of `model_dump()`. This lives in the decorator only and doesn't change the shared runtime contract for built-in tools. A regression test covers a BaseModel arg (existing `summarize`/`Range` fixture) and a dataclass arg. It passes three inputs: the validated model, the dumped mapping the runtime passes, and a raw mapping.
