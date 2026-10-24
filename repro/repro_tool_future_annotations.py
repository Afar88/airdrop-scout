"""Repro (openminion 0.1.10): @tool + `from __future__ import annotations`.

`openminion.tools.decorator._build_args_model` passes raw `inspect.signature`
annotations to `pydantic.create_model`. Under PEP 563 they are strings, so
names like `Annotated` / `Field` / user types cannot be resolved and the
args model is never fully defined.

Run: python repro/repro_tool_future_annotations.py
"""
from __future__ import annotations

import os
import tempfile
from typing import Annotated

from pydantic import Field

from openminion import Agent, tool


@tool
def plain(days: int = 2) -> str:
    """Plain builtin annotation."""
    return f"days={days}"


@tool
def annotated(days: Annotated[int, Field(description="Look-back days")] = 2) -> str:
    """Annotated parameter (the documented way to describe args in pydantic)."""
    return f"days={days}"


for fn in (plain, annotated):
    try:
        fn.tool_args_model.model_json_schema()
        print(f"{fn.__name__}: schema OK")
    except Exception as exc:  # noqa: BLE001
        print(f"{fn.__name__}: schema FAILED -> {type(exc).__name__}: {str(exc)[:160]}")

# End-to-end against a local scripted OpenAI-compatible server: the schema
# failure does not raise. It comes back as the *reply text* of a run whose
# run_state is "completed", e.g. "a: State machine error: class-not-fully-defined ...".
import _mockenv  # noqa: E402

llm, srv, cfg = _mockenv.setup(first_tool=("annotated", {"days": 3}))
with Agent(config_path=cfg, tools=[annotated], session_id="repro") as agent:
    r = agent.run("call the tool please", timeout_seconds=60)
    print("run_state:", r.run_state, "| text:", r.text[:220])
srv.shutdown()

# Proposed fix (openminion/tools/decorator.py, _build_args_model): resolve
# annotations with typing.get_type_hints(func, include_extras=True) and fall
# back to the raw annotation only when resolution fails. Demonstrated here by
# patching the helper and re-decorating:
import inspect, typing  # noqa: E401,E402
from openminion.tools import decorator as _dec  # noqa: E402

_orig = _dec._build_args_model


def _fixed(func, model_name):
    try:
        hints = typing.get_type_hints(func, include_extras=True)
    except Exception:  # noqa: BLE001
        hints = {}
    sig = inspect.signature(func)
    params = [p.replace(annotation=hints.get(n, p.annotation)) for n, p in sig.parameters.items()]
    func.__signature__ = sig.replace(parameters=params)
    try:
        return _orig(func, model_name)
    finally:
        del func.__signature__


_dec._build_args_model = _fixed


def annotated2(days: Annotated[int, Field(description="Look-back days")] = 2) -> str:
    """Same tool, decorated after the fix."""
    return f"days={days}"


annotated2 = tool(annotated2)
print("after fix:", annotated2.tool_args_model.model_json_schema()["properties"]["days"])
