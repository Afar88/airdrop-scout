# What we learned

Notes from building Airdrop Scout on **openminion 0.1.10** (PyPI latest when we
started, 2026-10-23), Python 3.12.15, Linux aarch64. Each item says what we saw,
how to reproduce it, and what we did about it. Items marked **[bug]** are
candidates for an upstream issue and fix PR. Repro scripts are in `repro/` and
need **no API key**: they use the keyless `echo` provider or the scripted local
OpenAI-compatible server in `tests/mock_openai.py`.

---

## 1. `@tool` breaks with `from __future__ import annotations` + `Annotated` [bug, fixed upstream PR]

**Upstream:** reported as [openminion#376](https://github.com/openminion/openminion/issues/376) (a maintainer confirmed it in scope), fixed in [openminion#383](https://github.com/openminion/openminion/pull/383). Per the maintainer's review, the fix uses no blanket fallback. An unresolvable name raises a clear `TypeError`.

**Seen:** `openminion/tools/decorator.py::_build_args_model` passes the raw
`inspect.signature` annotations to `pydantic.create_model`. Under PEP 563 these
are strings, so `Annotated[int, Field(description=...)]` (or any name that is not
a builtin) can't be resolved and the args model stays "not fully defined".
Plain `int`/`str` still work, which is why the docs examples don't hit it.

**Repro:** `python repro/repro_tool_future_annotations.py`
```
plain: schema OK
annotated: schema FAILED -> PydanticUserError: `annotatedArgs` is not fully defined ...
run_state: completed | text: a: State machine error: class-not-fully-defined: `annotatedArgs` is not fully defined ...
after fix: {'default': 2, 'description': 'Look-back days', 'title': 'Days', 'type': 'integer'}
```
**Proposed fix (small PR):** in `_build_args_model`, resolve annotations with
`typing.get_type_hints(func, include_extras=True)` and fall back to the raw
annotation only if that fails. The repro script patches this in and shows the
schema comes out right, parameter descriptions included. Add a unit test that
decorates a function defined in a module using `from __future__ import annotations`.

**Workaround here:** `airdrop_scout/tools.py` doesn't use the future import.

## 2. Runtime errors come back as a "completed" reply, not an exception [bug]

**Upstream:** [openminion#384](https://github.com/openminion/openminion/issues/384). There's a standalone trigger with nothing to do with item 1: a tool that returns a non-JSON-serializable object (`repro/repro_run_state_completed_on_error.py`). It reproduces on 0.1.10 and on `dev` 367aa481. Fixed in [openminion#405](https://github.com/openminion/openminion/pull/405), merged into `dev` on 2026-10-25 (commit f9c4f65b) and released in [openminion 0.1.12](https://github.com/openminion/openminion/releases/tag/v0.1.12) on 2026-10-26. Re-checked on the published `openminion==0.1.12` in a fresh venv: the non-serializable tool result now returns `run_state="failed"` with `error_code=RUNTIME_ERROR`, while a recoverable tool failure and a normal tool turn still return `completed`.

**Seen:** in item 1 the run doesn't raise. `AgentRunResult.run_state == "completed"`
and `result.text == "a: State machine error: ..."`. Without `output_type` the
caller treats an internal failure as the agent's answer. 0.1.8 fixed the same
pattern for provider failures (`ProviderError`), but internal state-machine
errors still slip through.

**Repro:** same script as item 1 (the `run_state:` line).
**Suggestion:** raise a typed error (or at least set `run_state="failed"` and a
structured error) when the brain hits a state-machine error.

## 3. The documented minimal config fails from the SDK, and the failed session can't be reused [bug + docs]

**Seen:** the "Minimal config" on *Getting Started → Configuration*
(`{"default_agent":"default","agents":{"default":{"name":"default","provider":"echo"}}}`)
fails with `Agent(config_path=...)`:
`RuntimeError: inbound authenticity denied (reason=invalid_channel, mode=warn)`.
The agent has no `default_channel`, so the gateway sees an empty channel.
- It's a bare `RuntimeError`, not a public exception type.
- The message says `mode=warn`, but the turn is still denied.
- The denied turn still saves the session with channel `''`. Reusing that
  `session_id` after fixing the config fails with
  `ValueError: Session 's1' belongs to channel '', not 'console'`.

**Repro:** `python repro/repro_minimal_config_channel.py`
```
1. documented minimal config, session s1: RuntimeError: inbound authenticity denied (reason=invalid_channel, mode=warn)
2. + default_channel=console, fresh session s2: OK -> 'default: hello (thinking=minimal)'
3. + default_channel=console, re-using s1: ValueError: Session 's1' belongs to channel '', not 'console'
```
**Suggestion:** default SDK turns to the `console` channel when the agent has
none (or add `default_channel` to the documented minimal config). Don't save a
session for a turn that was denied before it started.
**Workaround here:** `config.py` always writes `"default_channel": "console"`.

## 4. `Agent(instructions=...)` gets cut to roughly 640–890 characters [rough edge, undocumented]

**Seen:** `instructions` becomes `override_system_prompt` and is rendered in
the `[IDENTITY]` block, which has a token budget. Longer text is cut with
`...[truncated]`: we saw about 890 chars kept in the `reflect` phase and about
660 in `decide`. Nothing in the docs mentions a limit. Our first prompt (task
method plus JSON schema) lost everything after the first few rules.

**Repro:** `python repro/repro_runtime_rough_edges.py` → line `A.`
```
A. instructions sent: 1698 chars; identity block: 667 chars; truncated=True
```
**Workaround here:** `instructions` is a 324-character persona. The full method
and the JSON schema go in the run message, which is sent whole.
**Suggestion:** document the limit, warn when `instructions` gets truncated, or
send caller instructions outside the identity budget.

## 5. `output_type=` only validates; the schema is never sent to the model [docs gap]

**Seen:** `Agent._coerce_output` checks the final text against the Pydantic
model, but the model's JSON schema isn't in any provider request. The runtime's
own `[TOOL RESULT FORMAT]` system block also tells the model *"Never expose raw
JSON"*, which works against asking for a JSON-only answer.

**Repro:** `repro_runtime_rough_edges.py` → line `B.`
```
B. 'answer' schema present in any request: False; 'Never expose raw JSON' present: True
```
**Workaround here:** `models.schema_hint()` puts the compact JSON schema in the run message.
**Suggestion:** inject the schema (or use provider-native `response_format`) when
`output_type` is a Pydantic model, and leave out the "never expose raw JSON"
line in that case.

## 6. Tool results are compacted to 1200 chars per string and 16 items per list or dict [rough edge, undocumented]

**Seen:** `modules/brain/loop/tools/messages.py` compacts tool outputs before the
model sees them (`TOOL_MESSAGE_STRING_LIMIT = 1200`,
`TOOL_MESSAGE_SEQUENCE_LIMIT = 16`, `TOOL_MESSAGE_DEPTH_LIMIT = 8`). A tool that
returns one long string, such as a JSON dump or an announcement, is quietly cut
to its first 1200 characters. Dict returns are also copied into a JSON
`summary` string, which spends tokens on duplicate content.

**Repro:** `repro_runtime_rough_edges.py` → line `C.`
```
C. tool returned 5000 chars; model saw 1214 chars ending 'xx...[truncated]'
```
**Workaround here:** the tools return dicts. Announcement text comes as up to 14
chunks of 1100 characters or less, and campaign lists are paged 15 at a time
(`offset` / `next_offset`). `tests/test_tools.py::test_fetch_output_fits_openminion_compaction_limits` checks this.
**Suggestion:** document the limits on the Tool System page, and either make them
configurable or tell the model the output was truncated in a way it can act on.

## 7. `AgentRunResult.text` starts with `"<agent name>: "` [bug vs docs]

**Seen:** the API reference calls `text` the "raw reply text", but
`services/brain/post_execution/postprocess_response.py` returns
`f"{agent_name}: {response_text}"`. Structured output still validates only
because of the `_extract_json_object` fallback.

**Repro:** `repro_runtime_rough_edges.py` → line `D.`
```
D. result.text = 'a: {"answer": "done"}'  output = Out(answer='done')
```

## 8. `stats` under-reports LLM calls and tokens [bug]

**Seen:** one `Agent.run` makes several provider requests (decide/act, plus
internal `FreshnessContract`, `FinalizationStatus` and `ClosureJudgment`
structured calls, and a memory fact-extraction call when memory is on), but
`result.stats["llm_calls"]` reports `1` and the token counts are short. This
matters for cost on paid providers and for latency on Cortensor Portal.

**Repro:** `repro_runtime_rough_edges.py` → line `E.`
```
E. provider requests = 5; stats.llm_calls = 1; stats.input_tokens = 30 (mock reported 10/request)
```
In our scout run against the mock: 7 provider requests for list → fetch →
answer, with `runtime.memory_enabled=false` (8–9 with memory on).
**Workaround here:** `config.py` sets `runtime.memory_enabled=false`, because the
scout keeps its own `seen.json`. That saves one LLM call per run.

## 9. Docs and package versions don't match

- The docs site (generated 2026-10-19) calls **v0.1.8** "the current public
  preview", and the quickstart pins `openminion==0.1.8`. PyPI ships **0.1.10**.
  We found no 0.1.9/0.1.10 notes on the docs pages we read.
- The quickstart creates the venv with `python3.11`. 3.12.15 worked fine.
- The public API we used (`Agent`, `tool`, `ProviderError`, `TurnTimeoutError`,
  `AgentOutputValidationError`, `APIRuntime`, `openminion.api.*`) matched the
  0.1.8 reference exactly in 0.1.10.
- `dir(openminion)` doesn't list the lazy exports, so they look missing in a
  REPL. `from openminion import Agent` still works.

## 10. Other observations

- **`forced_tools`:** on the first step only the forced tool is shown to the model,
  with `tool_choice: "auto"` (not `"required"`). Later steps show all tools.
- **Runtime construction needs the key:** `APIRuntime.from_config_path` raises
  `ProviderError("... API key is missing")` when the key env var is empty, so you
  can't even build a runtime to inspect without one. Tests set placeholder keys.
- **Log flood:** `Agent` builds its runtime with `logging_mode="interactive"`, and
  every run prints 100+ INFO lines (`registered via REGISTRAR ...`) to stderr.
  Setting `runtime.log_level: "WARNING"` in the config fixes it, so `config.py`
  does that (`SCOUT_LOG_LEVEL` to change it).
- **URL-grounding guard (good):** if the final answer cites a URL that isn't in
  any tool result, the runtime asks the model again ("Your previous reply cited
  source URLs that do not appear in the successful tool results ..."). That's why
  our tools include `url` in every campaign.
- **Cortensor Portal preset:** `openminion setup --provider cortensor-portal`
  maps Portal onto the `openai` adapter (base URL `https://api.cortensor.app/v1`,
  `CORTENSOR_API_KEY`, 480 s request timeout). `config show` therefore lists the
  provider as `openai`. Expect that when reading configs.
- **Proxies:** httpx follows `HTTP(S)_PROXY` even for `127.0.0.1`. Local Ollama or
  mock endpoints behind a proxy need `NO_PROXY=127.0.0.1,localhost`.
- **Real endpoints confirmed without a key:** with placeholder keys, both
  Cortensor Portal and OpenRouter returned a typed
  `ProviderError(code="AUTH_ERROR")` with `details.status_code == 401` and the
  upstream message, so the config and adapter wiring reach the real APIs.

## 11. First real-model run: Gemma 4 31B (free) on OpenRouter

Date 2026-10-24, `google/gemma-4-31b-it:free`, `--days 2`, openminion 0.1.10.

- **Free-tier 429s are upstream and bursty.** On the evening of 2026-10-23, both
  Gemma 4 free models (31B and 26B-A4B) returned `429 Provider returned error`.
  On the morning of 2026-10-24, one attempt hung for more than 115 s before we
  killed it. The next attempt failed after about 25 s with the same 429. The
  attempt after that, a minute later, succeeded. The 429s did **not** count
  toward the key's `free_model_daily_requests` (still 0/50 after them, per
  `GET /api/v1/key`). OpenMinion returns them as a typed
  `ProviderError(code="RATE_LIMITED", details.status_code=429,
  reason_code="provider_rate_limited")`, which made them easy to tell apart.
  Practical rule: retry a 429 after a short pause before you switch models.
- **Request cost:** the successful run used **2** free requests on
  OpenRouter's counter. That is the forced `list_recent_campaigns` call and
  then the final answer. Per item 8, `stats.llm_calls` reported 1. The
  closure/finalization structured calls we saw against the mock did not add to
  the OpenRouter count here. The 50 free requests a day are enough for many
  runs.
- **Latency:** about 29 s inside `Agent.run` (`duration_ms=29262`), about 35 s
  wall clock with startup. Tokens: 8,640 input, 612 output.
- **Tool calling:** Gemma called the forced tool correctly. Then it chose not to
  call `fetch_campaign_details`, because both campaigns had "Trade ..." titles.
  The method allows that ("titles that obviously require trading can be marked
  SKIP without fetching"). So `nigeria` stayed `"unclear"` and `deadline_utc`
  stayed `""` instead of being made up, which is the right behaviour.
- **JSON compliance:** the final answer passed `ScoutReport` validation on the
  first try, with no `AgentOutputValidationError` and no repair round, even
  with the runtime's "Never expose raw JSON" line (item 5). Putting the schema
  in the run message was enough.
- **Coverage check:** `binance_feed.scan(days=2)` returned exactly the same 2
  campaigns, so the model left nothing out. There were no DO_IT or MAYBE
  campaigns in this window. Both were trading competitions.

## Data-source quirks (not OpenMinion)

- The Binance article **detail** endpoint
  (`/bapi/apex/v1/public/apex/cms/article/detail/query?articleCode=...`) returns
  `{"success": true, "data": null}` unless you send the header `clienttype: web`.
- Announcement bodies are a JSON rich-text tree (`node`/`tag`/`child`), not
  HTML. We flatten it to text and render tables as `a | b`. Times appear as
  `YYYY-MM-DD HH:MM (UTC)`; WAT is UTC+1 all year.
