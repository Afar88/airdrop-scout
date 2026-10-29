Follow-up to the probe review: release checks on the published **openminion==0.1.15** (contains #405 merge `f9c4f65b`), with the probe made self-contained and asserting.

**Environment**: clean `uv venv` outside any checkout, Linux aarch64, Python 3.11.17, pydantic 2.14.1. Provider: none, a local scripted OpenAI-compatible server (`om_mock.py`, stdlib, pinned below), model `mock-model`.

**Commands**
```
uv venv -p 3.11 /tmp/v15 && uv pip install -p /tmp/v15/bin/python "openminion==0.1.15"
git clone https://github.com/Afar88/airdrop-scout && cd airdrop-scout && git checkout de65965c
/tmp/v15/bin/python verify/verify_384.py            # exit code = failed cases
/tmp/v15/bin/python verify/repro_cancel_during_approval.py 12
```
Script: https://github.com/Afar88/airdrop-scout/blob/de65965c948938efaea50400addf12f3ad9ded29/verify/verify_384.py

What changed in the probe: each case gets its own temp home and session. It reads that session through `openminion.api.queries.runs.list_runs` / `list_run_events` and asserts exactly one run, `run_id ==` the SDK result's `run_id` where one is returned, and exactly one terminal event, which must be the last. Nothing is caught silently.

**Results: 9/10 pass (exit 1)**
1. Fatal non-serializable result: PASS. SDK `failed`, `error_code=RUNTIME_ERROR`, `brain_status=error`; persisted `failed`, terminal `run.failed`
2. Recoverable tool raise: PASS. `completed`, `EXEC_ERROR`, `tool_loop_termination_reason=tool_no_success`; persisted `run.completed`
3. Success: PASS. `completed`, `brain_status=done`; events queued→running→waiting_tool→responding→completed
4. Timeout (provider 6 s, `timeout_seconds=2`): PASS. Raises `openminion.TurnTimeoutError` after 2.2 s; persisted `failed` (`error_code=CancelledError`)
5. `cancel_event` while waiting on the provider: PASS. Raises `RuntimeError("Turn cancelled.")` after 1.5 s; persisted `failed` (`CancelledError`)
6. `cancel_event` during a 5 s tool: PASS. Raises after 2.5 s; persisted `failed`
7. Approval pause (dangerous tool, no callback): PASS. Tool not run, `brain_status=waiting_user`, text "Policy confirmation required." with "Risk: destructive"; run `completed`
8. `approval_callback` deny / allow: PASS. Deny: callback got `('lookup_order', {'order_id': 'A-1'})`, tool not run. Allow: tool ran once, `completed`, with `run.waiting_tool`
9. `submit_turn` stream: PASS. `requested` arrives before the tool runs. allow_once → tool ran, `completed`; deny → not run, `completed`; cancel → not run, empty result; stale approval id refused afterwards
10. Cancel during the approval wait, repeated 8×: **FAIL**. `handle.cancel()` returns True, the tool never runs and `result().final_text == ''`, but the persisted run was `completed` 3/8 times (the 36-char "Tool execution denied by operator" reply) and `failed`/`CancelledError` 5/8 times

**On 10**: the minimal repro (`verify/repro_cancel_during_approval.py`) gave 7/12 `completed` on 0.1.15 and 4/12 on published **0.1.12**, so it predates #405. The #405 paths (1-3) hold. Happy to file it as a separate issue if you'd prefer.

**Other observations (not asserted)**
- Cancellation and timeout persist `failed` with `error_code=CancelledError` and `error: ""`. None of these runs wrote the `cancelled` run state, and a `cancel_event` cancel raises a plain `RuntimeError`, not a typed error.
- After a cancel during a synchronous tool, the tool body still runs to completion in the background; the persisted state stays `failed`.
- After cancelled `submit_turn` runs and `APIRuntime.close()`, late telemetry writes log `sqlite3.ProgrammingError: Cannot operate on a closed database` (logged, not raised).

**Not run**: a real model provider, macOS and Windows, and provider-error paths.

Outputs: https://github.com/Afar88/airdrop-scout/tree/de65965c948938efaea50400addf12f3ad9ded29/verify/results
