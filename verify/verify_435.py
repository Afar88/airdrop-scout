"""Installed-package verification for openminion#435 (fixed by #436).

@tool parameters typed as a Pydantic model, a standard dataclass or a Pydantic
dataclass must reach the decorated function as validated instances, both when
the handler is called directly and through an ordinary SDK Agent.run().

Self-contained: needs only the installed openminion and om_mock.py (same
folder, standard library). Every check asserts; exit code is the number of
failed checks (0 = all pass). Case I (#454, SDK nested alias) is reported for
information only and never counts as a pass or fail of #435.

Run: python verify_435.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pydantic
from pydantic import BaseModel, Field, ValidationError
from pydantic.dataclasses import dataclass as pyd_dataclass

import om_mock
import openminion
from openminion import Agent, tool

print(f"openminion {openminion.__version__} from {openminion.__file__}")
print(f"python {sys.version.split()[0]}  pydantic {pydantic.VERSION}")

RESULTS: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((name, True, detail))
        print(f"PASS {name} {detail}")
    except Exception as exc:  # noqa: BLE001 - report every failure, keep going
        RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=2)


def rejects(handler, payload):
    try:
        handler(payload)
    except ValidationError as exc:
        return exc.errors()[0]["type"]
    raise AssertionError(f"accepted invalid input {payload!r}")


# ---- tools -----------------------------------------------------------------
class Chain(str, Enum):
    solana = "solana"
    ethereum = "ethereum"


class Filter(BaseModel):
    chain: Chain
    min_score: int = 0


@dataclass
class Window:
    days: int


SEEN: dict = {}


@tool(idempotent=True, min_scope="READ_ONLY")
def scan_campaigns(f: Filter, window: Window) -> str:
    """Scan airdrop campaigns matching a filter within a time window (original #435 repro)."""
    SEEN["scan"] = (f, window)
    return f"{f.chain.value} >= {f.min_score} over {window.days}d"


@pyd_dataclass
class PdSpan:
    start: int
    end: int = Field(default=10, le=100)


@tool(idempotent=True, min_scope="READ_ONLY")
def span_tool(span: PdSpan) -> str:
    """Pydantic dataclass parameter."""
    SEEN["span"] = span
    return f"span {span.start}-{span.end}"


@dataclass
class Item:
    sku: str
    qty: int = 1


class Inner(BaseModel):
    level: Annotated[int, Field(ge=1, le=5)] = 3


class Order(BaseModel):
    inner: Inner
    items: list[Item]
    note: Optional[str] = None


@tool(idempotent=True, min_scope="READ_ONLY")
def place(order: Order, priority: Annotated[int, Field(ge=1)] = 2, tag: Optional[str] = None) -> str:
    """Nested structured values, constraints and defaults."""
    SEEN["place"] = (order, priority, tag)
    return f"items={len(order.items)} level={order.inner.level} prio={priority}"


@tool
def show(value: Annotated[int, Field(alias="external_value", ge=0)]) -> str:
    """Alias regression from the #436 review."""
    return str(value)


# ---- A-G: direct handler (runtime mapping contract) ------------------------
def case_a():
    SEEN.clear()
    m = scan_campaigns.tool_args_model.model_validate(
        {"f": {"chain": "solana", "min_score": 3}, "window": {"days": 7}})
    out = scan_campaigns.tool_decl.handler(m)
    f, w = SEEN["scan"]
    assert out == "solana >= 3 over 7d", out
    assert type(f) is Filter and type(w) is Window and f.chain is Chain.solana
    return f"-> {out!r}; received {type(f).__name__}, {type(w).__name__}"


def case_b():
    SEEN.clear()
    raw = {"f": {"chain": "ethereum"}, "window": {"days": 2}}
    out1 = scan_campaigns.tool_decl.handler(raw)
    t1 = tuple(type(x).__name__ for x in SEEN["scan"])
    dumped = scan_campaigns.tool_args_model.model_validate(raw).model_dump()
    out2 = scan_campaigns.tool_decl.handler(dumped)
    t2 = tuple(type(x).__name__ for x in SEEN["scan"])
    assert out1 == out2 == "ethereum >= 0 over 2d", (out1, out2)
    assert t1 == t2 == ("Filter", "Window"), (t1, t2)
    return f"raw mapping + model_dump() -> {out1!r}, types {t1}, default min_score=0 applied"


def case_c():
    SEEN.clear()
    out = span_tool.tool_decl.handler({"span": {"start": 4}})
    s = SEEN["span"]
    assert type(s) is PdSpan and (s.start, s.end) == (4, 10), s
    err = rejects(span_tool.tool_decl.handler, {"span": {"start": 4, "end": 500}})
    return f"-> {out!r}; received PdSpan(start=4, end=10 default); end=500 rejected ({err})"


def case_d():
    SEEN.clear()
    out = place.tool_decl.handler({"order": {"inner": {}, "items": [{"sku": "a"}, {"sku": "b", "qty": 4}]}})
    order, prio, tag = SEEN["place"]
    assert type(order) is Order and type(order.inner) is Inner
    assert [type(i) for i in order.items] == [Item, Item]
    assert order.items[1].qty == 4 and order.items[0].qty == 1 and order.inner.level == 3
    assert prio == 2 and tag is None and order.note is None
    return (f"-> {out!r}; Order/Inner/[Item, Item] instances; defaults level=3 qty=1 "
            f"priority=2 tag=None note=None")


def case_e():
    h = place.tool_decl.handler
    base = {"inner": {}, "items": []}
    errs = {
        "wrong type (items='x')": rejects(h, {"order": {**base, "items": "x"}}),
        "nested constraint (level=9)": rejects(h, {"order": {**base, "inner": {"level": 9}}}),
        "top-level constraint (priority=0)": rejects(h, {"order": base, "priority": 0}),
        "missing required (order)": rejects(h, {}),
        "missing nested (items)": rejects(h, {"order": {"inner": {}}}),
        "extra top-level input": rejects(h, {"order": base, "surprise": 1}),
        "invalid enum": rejects(scan_campaigns.tool_decl.handler,
                                {"f": {"chain": "btc"}, "window": {"days": 1}}),
        "dataclass missing field": rejects(scan_campaigns.tool_decl.handler,
                                           {"f": {"chain": "solana"}, "window": {}}),
    }
    return "rejected with ValidationError: " + "; ".join(f"{k}={v}" for k, v in errs.items())


def case_f():
    v = show.tool_args_model.model_validate({"external_value": 3})
    got = [show.tool_decl.handler(v), show.tool_decl.handler(v.model_dump()),
           show.tool_decl.handler(v.model_dump(by_alias=True)),
           show.tool_decl.handler({"external_value": 4}), show.tool_decl.handler({"value": 5})]
    assert got == ["3", "3", "3", "4", "5"], got
    try:
        show.tool_args_model.model_validate({"value": 3})
        raise AssertionError("args model now accepts field name; it should stay alias-only")
    except ValidationError:
        pass
    errs = [rejects(show.tool_decl.handler, p) for p in ({"value": -1}, {"value": 1, "other": 2}, {})]
    return f"handler results {got}; args model still alias-only; rejected -1/extra/empty: {errs}"


# ---- G-H: ordinary SDK invocation through Agent.run ------------------------
def sdk_run(fn, args, session):
    script = om_mock.Script(fn.__name__, args)
    srv, cfg = om_mock.make_env(script)
    try:
        with Agent(config_path=cfg, tools=[fn], session_id=session) as agent:
            r = agent.run("call the tool", timeout_seconds=60)
    finally:
        srv.shutdown()
    msgs = script.tool_messages()
    env = json.loads(msgs[0]["content"]) if msgs else {}
    return r, env


def case_g():
    SEEN.clear()
    r, env = sdk_run(scan_campaigns, {"f": {"chain": "solana", "min_score": 3}, "window": {"days": 7}},
                     "v435-scan")
    f, w = SEEN["scan"]
    assert type(f) is Filter and type(w) is Window
    assert env.get("status") == "success", env
    assert (env.get("outputs") or {}).get("data") == "solana >= 3 over 7d", env
    assert r.run_state == "completed", r.run_state
    return (f"tool received {type(f).__name__}/{type(w).__name__}; tool status={env.get('status')} "
            f"output={(env.get('outputs') or {}).get('data')!r}; run_state={r.run_state}")


def case_h():
    SEEN.clear()
    r, env = sdk_run(place, {"order": {"inner": {"level": 2}, "items": [{"sku": "z", "qty": 2}]}},
                     "v435-place")
    order, prio, _ = SEEN["place"]
    assert type(order) is Order and type(order.inner) is Inner and type(order.items[0]) is Item
    assert env.get("status") == "success" and r.run_state == "completed", (env.get("status"), r.run_state)
    SEEN.clear()
    r2, env2 = sdk_run(span_tool, {"span": {"start": 1}}, "v435-span")
    assert type(SEEN["span"]) is PdSpan and env2.get("status") == "success" and r2.run_state == "completed"
    return (f"nested Order/Inner/Item and Pydantic dataclass delivered as instances via Agent.run; "
            f"statuses {env.get('status')}/{env2.get('status')}; run_state {r.run_state}/{r2.run_state}")


class AliasedFilter(BaseModel):
    min_total: int = Field(alias="minTotal", ge=0)
    status: str = "open"


@tool(idempotent=True, min_scope="READ_ONLY")
def filter_orders(query: AliasedFilter) -> str:
    """SDK nested alias (#454, informational only)."""
    SEEN["alias"] = query
    return f"FILTER min={query.min_total}"


check("A original #435 repro, handler(validated args model)", case_a)
check("B handler(raw mapping) and handler(model_dump())", case_b)
check("C Pydantic dataclass parameter + constraint/default", case_c)
check("D nested structured values + defaults", case_d)
check("E invalid / extra inputs rejected", case_e)
check("F alias + canonical mappings (#436 review case)", case_f)
check("G SDK Agent.run, original repro (BaseModel + std dataclass)", case_g)
check("H SDK Agent.run, nested model + Pydantic dataclass", case_h)

# I. informational: #454 (tracked separately, not certified by #436)
SEEN.clear()
try:
    _r, _env = sdk_run(filter_orders, {"query": {"minTotal": 7}}, "v435-alias")
    print(f"INFO I (#454, not part of #435) SDK nested alias: tool status={_env.get('status')} "
          f"error={(_env.get('error') or {}).get('code')} handler_called={'alias' in SEEN}")
except Exception as exc:  # noqa: BLE001
    print(f"INFO I (#454) raised {type(exc).__name__}: {exc}")

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\nSUMMARY {len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
      + (f"; FAILED: {failed}" if failed else ""))
sys.exit(len(failed))
