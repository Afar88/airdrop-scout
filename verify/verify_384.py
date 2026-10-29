"""Installed-package verification for openminion#384 (fixed by #405).

Each case runs in its own temporary OPENMINION_HOME and its own session, then
reads that exact session back through the public run reader
(openminion.api.queries.runs.list_runs / list_run_events), asserts the session
holds exactly one run, correlates it with the SDK result's run_id when the run
returned one, and asserts the persisted terminal event. Nothing is swallowed:
any unexpected exception or assertion is a FAIL. Exit code = number of failed
cases (0 = all pass).

Cases
  1 fatal: tool returns a non-JSON-serializable object -> failed
  2 recoverable: tool raises, model answers -> completed with EXEC_ERROR
  3 success control -> completed
  4 timeout (provider slower than timeout_seconds) -> TurnTimeoutError, failed
  5 cancellation via cancel_event while waiting on the provider
  6 cancellation via cancel_event while a tool is running
  7 approval pause: dangerous tool, no approval_callback -> confirmation
    prompt, tool not run
  8 approval_callback deny / allow
  9 submit_turn stream: approval requested before the tool runs, then
    allow_once / deny / cancel; a stale approval id is refused afterwards
 10 cancel during the approval wait, repeated (VERIFY_CANCEL_REPEAT, default
    8): the persisted run must be failed/cancelled every time, matching the
    caller's cancelled (empty) result

Self-contained: needs only the installed openminion and om_mock.py (same
folder, standard library). No API key or network.

Run: python verify_384.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pydantic

import om_mock
import openminion
from openminion import Agent, APIRuntime, tool
from openminion.api.queries.runs import list_run_events, list_runs

print(f"openminion {openminion.__version__} from {openminion.__file__}")
print(f"python {sys.version.split()[0]}  pydantic {pydantic.VERSION}  provider: local scripted "
      f"OpenAI-compatible mock (om_mock.py), model 'mock-model'")

RESULTS: list[tuple[str, bool]] = []
CALLS: list[str] = []


class NotJSON:
    pass


@tool(idempotent=True, min_scope="READ_ONLY")
def bad_return() -> str:
    """Returns an object that cannot be JSON-serialized."""
    CALLS.append("bad_return")
    return NotJSON()  # type: ignore[return-value]


@tool(idempotent=True, min_scope="READ_ONLY")
def raises() -> str:
    """Raises."""
    CALLS.append("raises")
    raise RuntimeError("tool exploded")


@tool(idempotent=True, min_scope="READ_ONLY")
def good() -> str:
    """Fine."""
    CALLS.append("good")
    return "GOOD_RESULT"


@tool(idempotent=True, min_scope="READ_ONLY")
def slow() -> str:
    """Slow tool."""
    CALLS.append("slow:start")
    time.sleep(5)
    CALLS.append("slow:end")
    return "slow done"


@tool(dangerous=True)
def lookup_order(order_id: str) -> str:
    """Look up an order (dangerous, needs approval)."""
    CALLS.append(f"lookup_order:{order_id}")
    return "ORDER_READY"


def persisted(cfg: str, session: str, sdk_run_id: str | None = None) -> tuple[dict, list[dict]]:
    runs = list_runs(cfg, session_id=session)["runs"]
    assert len(runs) == 1, f"expected exactly 1 run in session {session}, got {len(runs)}"
    run = runs[0]
    if sdk_run_id:
        assert run["run_id"] == sdk_run_id, (run["run_id"], sdk_run_id)
    events = list_run_events(cfg, session_id=session, run_id=run["run_id"])["events"]
    assert events and all(e["run_id"] == run["run_id"] and e["session_id"] == session for e in events)
    return run, events


def terminal(events: list[dict]) -> dict:
    term = [e for e in events if e["event_type"] in ("run.completed", "run.failed", "run.cancelled")]
    assert len(term) == 1, f"expected one terminal event, got {[e['event_type'] for e in events]}"
    assert events[-1] is term[0], "terminal event is not the last event"
    return term[0]


ONLY = os.environ.get("VERIFY_ONLY")  # optional: run only cases whose number is listed, e.g. "9"


def case(name):
    def deco(fn):
        if ONLY and name.split()[0] not in ONLY.split(","):
            return fn
        CALLS.clear()
        try:
            detail = fn()
            RESULTS.append((name, True))
            print(f"PASS {name}\n     {detail}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            RESULTS.append((name, False))
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        return fn
    return deco


def sdk(session, script, tools, **kw):
    srv, cfg = om_mock.make_env(script)
    try:
        with Agent(config_path=cfg, tools=tools, session_id=session) as agent:
            return agent.run("call the tool", **kw), cfg
    finally:
        srv.shutdown()


def sdk_raises(session, script, tools, **kw):
    srv, cfg = om_mock.make_env(script)
    t0 = time.monotonic()
    try:
        with Agent(config_path=cfg, tools=tools, session_id=session) as agent:
            r = agent.run("call the tool", **kw)
        raise AssertionError(f"expected an exception, got run_state={r.run_state!r} text={r.text[:80]!r}")
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001 - the exception is the observation
        return exc, time.monotonic() - t0, cfg
    finally:
        srv.shutdown()


@case("1 fatal: non-JSON-serializable tool result -> failed (SDK + persisted)")
def _():
    r, cfg = sdk("v384-fatal", om_mock.Script("bad_return"), [bad_return], timeout_seconds=60)
    md = r.metadata
    assert r.run_state == "failed", r.run_state
    assert md.get("error_code") == "RUNTIME_ERROR" and md.get("brain_status") == "error", md
    assert "not JSON serializable" in json.dumps(md, default=str) + r.text
    run, ev = persisted(cfg, "v384-fatal", r.run_id)
    t = terminal(ev)
    assert run["state"] == "failed" and t["event_type"] == "run.failed", (run["state"], t["event_type"])
    return (f"SDK run_state={r.run_state} error_code={md.get('error_code')} brain_status={md.get('brain_status')}; "
            f"persisted run {run['run_id'][:8]} (== SDK run_id) state={run['state']}, terminal={t['event_type']}")


@case("2 recoverable: tool raises, model answers -> completed with EXEC_ERROR")
def _():
    r, cfg = sdk("v384-recover", om_mock.Script("raises"), [raises], timeout_seconds=60)
    md = r.metadata
    assert CALLS == ["raises"] and r.run_state == "completed", (CALLS, r.run_state)
    assert md.get("error_code") == "EXEC_ERROR", md
    run, ev = persisted(cfg, "v384-recover", r.run_id)
    t = terminal(ev)
    assert run["state"] == "completed" and t["event_type"] == "run.completed"
    return (f"SDK run_state={r.run_state} error_code={md.get('error_code')} "
            f"tool_loop_termination_reason={md.get('tool_loop_termination_reason')}; "
            f"persisted {run['state']}, terminal={t['event_type']}")


@case("3 success control -> completed")
def _():
    r, cfg = sdk("v384-ok", om_mock.Script("good"), [good], timeout_seconds=60)
    assert CALLS == ["good"] and r.run_state == "completed", (CALLS, r.run_state)
    assert r.metadata.get("brain_status") == "done" and not r.metadata.get("error_code"), r.metadata
    run, ev = persisted(cfg, "v384-ok", r.run_id)
    t = terminal(ev)
    assert run["state"] == "completed" and t["event_type"] == "run.completed"
    return (f"SDK run_state={r.run_state} brain_status={r.metadata.get('brain_status')} text={r.text!r}; "
            f"persisted {run['state']}, events={[e['event_type'] for e in ev]}")


@case("4 timeout: provider 6s, timeout_seconds=2 -> TurnTimeoutError, persisted failed")
def _():
    exc, dt, cfg = sdk_raises("v384-timeout", om_mock.Script(delay=6), [], timeout_seconds=2)
    assert isinstance(exc, openminion.TurnTimeoutError), type(exc)
    assert dt < 5, f"took {dt:.1f}s"
    run, ev = persisted(cfg, "v384-timeout")
    t = terminal(ev)
    assert run["state"] == "failed" and t["event_type"] == "run.failed", (run["state"], t["event_type"])
    return (f"raised openminion.TurnTimeoutError({exc}) after {dt:.1f}s; persisted state={run['state']}, "
            f"terminal={t['event_type']} error_code={t['payload'].get('error_code')}")


@case("5 cancel_event set at 1.5s while waiting on provider -> raises, persisted failed")
def _():
    ev_ = threading.Event()
    threading.Timer(1.5, ev_.set).start()
    exc, dt, cfg = sdk_raises("v384-cancel", om_mock.Script(delay=5), [], cancel_event=ev_, timeout_seconds=60)
    assert "cancel" in str(exc).lower(), exc
    assert dt < 4, f"took {dt:.1f}s"
    run, ev = persisted(cfg, "v384-cancel")
    t = terminal(ev)
    assert run["state"] in ("failed", "cancelled") and run["state"] != "completed"
    return (f"raised {type(exc).__name__}({exc}) after {dt:.1f}s; persisted state={run['state']}, "
            f"terminal={t['event_type']} error_code={t['payload'].get('error_code')}")


@case("6 cancel_event set at 2.5s while a 5s tool runs -> raises, persisted failed")
def _():
    ev_ = threading.Event()
    threading.Timer(2.5, ev_.set).start()
    exc, dt, cfg = sdk_raises("v384-cancel-tool", om_mock.Script("slow"), [slow], cancel_event=ev_,
                              timeout_seconds=60)
    assert "cancel" in str(exc).lower(), exc
    assert "slow:start" in CALLS, CALLS
    run, ev = persisted(cfg, "v384-cancel-tool")
    t = terminal(ev)
    assert run["state"] in ("failed", "cancelled") and run["state"] != "completed"
    # Observation only (not asserted): does the in-flight synchronous tool keep running?
    time.sleep(3.5)
    finished = "slow:end" in CALLS
    run2, _ = persisted(cfg, "v384-cancel-tool")
    assert run2["state"] == run["state"], "persisted state changed after the tool finished"
    return (f"tool started; raised {type(exc).__name__}({exc}) after {dt:.1f}s; persisted state={run['state']}, "
            f"terminal={t['event_type']} error_code={t['payload'].get('error_code')}; "
            f"note: the in-flight sync tool body {'still ran to completion in the background' if finished else 'did not finish'}"
            f" after cancel; persisted state unchanged afterwards")


@case("7 approval pause: dangerous tool, no approval_callback -> confirmation prompt, tool not run")
def _():
    r, cfg = sdk("v384-pause", om_mock.Script("lookup_order", {"order_id": "A-1"}), [lookup_order],
                 timeout_seconds=60)
    assert CALLS == [], CALLS
    assert "Policy confirmation required" in r.text and "Risk: destructive" in r.text, r.text
    assert r.metadata.get("brain_status") == "waiting_user", r.metadata
    run, ev = persisted(cfg, "v384-pause", r.run_id)
    t = terminal(ev)
    assert run["state"] == "completed" and "run.waiting_tool" not in [e["event_type"] for e in ev]
    return (f"tool not called; brain_status={r.metadata.get('brain_status')}; text starts "
            f"{r.text.splitlines()[0]!r} and lists 'Risk: destructive'; SDK run_state={r.run_state}; "
            f"persisted {run['state']} ({t['event_type']}), no run.waiting_tool")


@case("8 approval_callback deny -> not run; allow -> run")
def _():
    seen = []
    r, cfg = sdk("v384-deny", om_mock.Script("lookup_order", {"order_id": "A-1"}), [lookup_order],
                 timeout_seconds=60, approval_callback=lambda n, a, i: seen.append((n, a)) or False)
    assert CALLS == [] and seen == [("lookup_order", {"order_id": "A-1"})], (CALLS, seen)
    run_d, _ev = persisted(cfg, "v384-deny", r.run_id)
    deny = f"deny: callback got {seen[0]}, tool not called, text={r.text!r}, persisted {run_d['state']}"
    r2, cfg2 = sdk("v384-allow", om_mock.Script("lookup_order", {"order_id": "A-2"}), [lookup_order],
                   timeout_seconds=60, approval_callback=lambda *a: True)
    assert CALLS == ["lookup_order:A-2"] and r2.run_state == "completed", (CALLS, r2.run_state)
    run_a, ev_a = persisted(cfg2, "v384-allow", r2.run_id)
    assert run_a["state"] == "completed" and "run.waiting_tool" in [e["event_type"] for e in ev_a]
    return f"{deny}\n     allow: tool ran once, run_state={r2.run_state}, persisted {run_a['state']}"


def submit_turn_case(decision: str) -> str:
    CALLS.clear()
    session = f"v384-stream-{decision}"
    script = om_mock.Script("lookup_order", {"order_id": "A-104"})
    srv, cfg = om_mock.make_env(script)
    rt = APIRuntime.from_config_path(cfg)
    try:
        from openminion.modules.tool.framework import build_registrar
        build_registrar(lookup_order.tool_family_spec()).register(rt.tools)
        rt.tools.get("lookup_order").prompt_visible_runtime_name = True
        h = rt.submit_turn(payload={"message": "Check A-104", "session_id": session,
                                    "allowed_tools": ["lookup_order"], "forced_tools": ["lookup_order"],
                                    "timeout_seconds": 20})
        requested, phases = [], []
        for chunk in h.stream(timeout_s=25):
            if chunk.kind != "approval":
                continue
            phases.append(chunk.data.get("phase"))
            if chunk.data.get("phase") != "requested":
                continue
            requested.append(chunk.data)
            assert CALLS == [], f"tool ran before approval: {CALLS}"
            assert chunk.data.get("tool_name") == "lookup_order"
            if decision == "cancel":
                assert h.cancel(), "handle.cancel() returned False"
            else:
                assert h.resolve_approval(approval_id=chunk.data["approval_id"], decision=decision), \
                    f"resolve_approval({decision}) returned False"
        res = h.result(timeout_s=5)
        stale = h.resolve_approval(approval_id=requested[0]["approval_id"], decision="allow_once")
    finally:
        rt.close()
        srv.shutdown()
    assert len(requested) == 1 and stale is False, (len(requested), stale)
    run, ev = persisted(cfg, session)
    t = terminal(ev)
    if decision == "allow_once":
        assert CALLS == ["lookup_order:A-104"] and run["state"] == "completed", (CALLS, run["state"])
    elif decision == "deny":
        assert CALLS == [] and run["state"] == "completed", (CALLS, run["state"])
    else:
        # tool never runs and the caller gets an empty result; the persisted
        # state is checked separately (case 10) because it is not deterministic
        assert CALLS == [] and res.final_text == "", (CALLS, res.final_text)
        assert run["state"] in ("failed", "cancelled", "completed"), run["state"]
    return (f"{decision}: approval phases={phases}, tool calls={CALLS}, final_text={res.final_text!r}, "
            f"stale approval id refused, persisted {run['state']} ({t['event_type']}"
            + (f", error_code={t['payload'].get('error_code')}" if t['event_type'] != 'run.completed' else "")
            + ")")


@case("9 submit_turn approval stream: allow_once / deny / cancel")
def _():
    return "\n     ".join(submit_turn_case(d) for d in ("allow_once", "deny", "cancel"))


CANCEL_REPEAT = int(os.environ.get("VERIFY_CANCEL_REPEAT", "8"))


@case("10 cancel during approval wait: persisted state agrees with the caller on every repeat")
def _():
    outcomes = []
    for i in range(CANCEL_REPEAT):
        outcomes.append(submit_turn_case("cancel").split("persisted ")[1])
    counts = {o: outcomes.count(o) for o in sorted(set(outcomes))}
    detail = f"{CANCEL_REPEAT} repeats, handle.cancel() returned True each time, tool never ran; persisted: {counts}"
    assert all(o.startswith(("failed", "cancelled")) for o in outcomes), detail
    return detail


failed = [n for n, ok in RESULTS if not ok]
print(f"\nSUMMARY {len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
      + (f"; FAILED: {failed}" if failed else ""))
sys.exit(len(failed))
