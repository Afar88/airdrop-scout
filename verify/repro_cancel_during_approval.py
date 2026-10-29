"""Minimal repro: cancelling a submitted turn while it waits for tool approval
is sometimes persisted as a completed run.

APIRuntime.submit_turn -> approval 'requested' chunk -> handle.cancel()
returns True, the tool never runs and handle.result() is an empty
TurnResponse (final_text=''), but in roughly 1 run in 4 the persisted run
(public reader list_runs/list_run_events) ends run.completed with a 36-char
response ("a: Tool execution denied by operator") instead of run.failed
(error_code=CancelledError). Seen on openminion 0.1.15 and 0.1.12.

Self-contained (om_mock.py in the same folder). Run: python repro_cancel_during_approval.py [N]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import om_mock
import openminion
from openminion import APIRuntime, tool
from openminion.api.queries.runs import list_run_events, list_runs
from openminion.modules.tool.framework import build_registrar

CALLS = []


@tool(dangerous=True)
def lookup_order(order_id: str) -> str:
    """Look up an order (dangerous, needs approval)."""
    CALLS.append(order_id)
    return "ORDER_READY"


print("openminion", openminion.__version__)
counts = {}
for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 12):
    CALLS.clear()
    session = f"cancel-approval-{i}"
    srv, cfg = om_mock.make_env(om_mock.Script("lookup_order", {"order_id": "A-104"}))
    rt = APIRuntime.from_config_path(cfg)
    build_registrar(lookup_order.tool_family_spec()).register(rt.tools)
    rt.tools.get("lookup_order").prompt_visible_runtime_name = True
    h = rt.submit_turn(payload={"message": "Check A-104", "session_id": session,
                                "allowed_tools": ["lookup_order"], "forced_tools": ["lookup_order"],
                                "timeout_seconds": 20})
    cancelled = None
    for ch in h.stream(timeout_s=25):
        if ch.kind == "approval" and ch.data.get("phase") == "requested":
            cancelled = h.cancel()
    res = h.result(timeout_s=5)
    rt.close()
    srv.shutdown()
    run = list_runs(cfg, session_id=session)["runs"][0]
    last = list_run_events(cfg, session_id=session, run_id=run["run_id"])["events"][-1]
    counts[run["state"]] = counts.get(run["state"], 0) + 1
    print(f"#{i}: cancel()={cancelled} tool_calls={CALLS} final_text={res.final_text!r} "
          f"persisted={run['state']} last_event={last['event_type']} "
          f"error_code={last['payload'].get('error_code')} response_chars={last['payload'].get('response_chars')}")
print("persisted states:", counts)
sys.exit(1 if counts.get("completed") else 0)
