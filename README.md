# Airdrop Scout 🛰️

An **OpenMinion** agent that reads new Binance campaign announcements every day
and tells one user in Nigeria which ones are actually worth doing: **free or
under $1, no trading volume, open to Nigeria**. For each one it pulls out the
steps, the reward, the deadline (in **WAT**) and any red flags, and returns a
typed report that becomes a short daily markdown brief.

Built for **Cortensor Hackathon #5**. Runs on Cortensor Portal (`oss-20b`),
OpenRouter, OpenAI or a local Ollama model, chosen by environment variables.

**▶ Demo video (2 min):** https://www.youtube.com/watch?v=a2f2aSxvz9E

> Read-only. It never signs in, touches a wallet, or places a trade. Not financial advice.

---

## Quick start

```bash
cd airdrop-scout
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt          # openminion==0.1.10, pydantic, pytest

# 1) No key needed: run the tools against live Binance with no model call
python -m airdrop_scout --dry-run --days 3

# 2) With a model (pick one)
export SCOUT_PROVIDER=cortensor-portal CORTENSOR_API_KEY=...   # Cortensor Portal, oss-20b
# export SCOUT_PROVIDER=openrouter OPENROUTER_API_KEY=...       # openai/gpt-4.1-mini
# export SCOUT_PROVIDER=openai OPENAI_API_KEY=...               # gpt-4.1-mini
# export SCOUT_PROVIDER=ollama                                  # llama3.1 on 127.0.0.1:11434
python -m airdrop_scout --days 2
```

You can also put the variables in `.env` (copy `.env.example`); real environment variables win.

Output:

| File | What it is |
| --- | --- |
| `briefs/YYYY-MM-DD.md`, `briefs/LATEST.md` | The daily brief (DO IT / MAYBE first, then skipped) |
| `briefs/YYYY-MM-DD.json` | The validated `ScoutReport` |
| `briefs/failed-YYYY-MM-DD.txt` | Raw model reply when it failed schema validation |
| `seen.json` | Campaign codes already briefed, so tomorrow only shows new ones |

CLI flags: `--days N`, `--timeout S` (per-run deadline; default 900 s on Cortensor, 300 s otherwise),
`--max-details N` (announcements the agent may open), `--session ID`, `--no-force-list`,
`--no-mark-seen`, `--out DIR`, `--env-file PATH`, `--dry-run`.

Exit codes: `0` ok · `1` no key/config · `2` `ProviderError` · `3` `TurnTimeoutError` · `4` `AgentOutputValidationError`.

## How OpenMinion is used

OpenMinion is the core. Everything goes through its public API (`openminion`
package root only; no `openminion.modules.*` imports in app code):

| Need | OpenMinion API used | Where |
| --- | --- | --- |
| Model-callable Python tools | `@tool` on `list_recent_campaigns(days, offset)`, `fetch_campaign_details(url_or_code, max_chars)`, `check_seen(code)` (+ `mark_seen(code)`, which the app calls itself) | `airdrop_scout/tools.py` |
| Agent with tools | `Agent(tools=[...], forced_tools=["list_recent_campaigns"], instructions=...)` | `airdrop_scout/agent.py` |
| Typed output | `Agent(output_type=ScoutReport)` → `result.output` (Pydantic) | `airdrop_scout/models.py` |
| Explicit session | `Agent(session_id="airdrop-scout-<timestamp>")` or `--session` | `agent.py` |
| Per-run deadline | `agent.run(..., timeout_seconds=...)` | `agent.py` |
| Clean shutdown | `with Agent(...) as agent:` closes the runtime it created | `agent.py` |
| Failure handling | `except ProviderError` (`code`, `message`, `details`), `TurnTimeoutError`, `AgentOutputValidationError` (`raw_text`) | `agent.py` |
| Provider switching | project-local `agents.json` passed as `Agent(config_path=..., agent_id="scout")`; `OPENMINION_HOME` / `OPENMINION_DATA_ROOT` isolate state | `airdrop_scout/config.py` |

What the agent does on each run:

1. Calls `list_recent_campaigns` (forced on the first step) and skips anything already in `seen.json`.
2. Opens the announcements that could fit with `fetch_campaign_details`. The tool returns the
   text in chunks, every `(UTC)` timestamp already converted to WAT, the eligibility lines
   (regions, KYC, minimums, holding, volume) and whether Nigeria is mentioned.
3. Gives each campaign a verdict (`DO_IT` / `MAYBE` / `SKIP`), with cost, trading volume,
   Nigeria status, steps, reward, `deadline_utc` and red flags, and returns JSON that
   OpenMinion checks against `ScoutReport`.
4. The app converts `deadline_utc` to WAT in Python (so the model never does time arithmetic),
   writes the brief, and marks the campaigns as seen.

Provider presets (copied from what `openminion setup --provider <id> --no-chat` writes in 0.1.10):

| `SCOUT_PROVIDER` | OpenMinion provider block | Model | Endpoint | Key env |
| --- | --- | --- | --- | --- |
| `cortensor-portal` | `openai` (OpenAI-compatible) | `oss-20b` | `https://api.cortensor.app/v1` | `CORTENSOR_API_KEY` |
| `openrouter` | `openrouter` | `openai/gpt-4.1-mini` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| `openai` | `openai` | `gpt-4.1-mini` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `ollama` | `ollama` | `llama3.1` | `http://127.0.0.1:11434` | none |

`SCOUT_MODEL` and `SCOUT_BASE_URL` override the model and endpoint. Secrets are never written
to `agents.json`; only `api_key_env` names are.

## Tests

```bash
pytest              # 45 offline tests: tools, parsing, WAT conversion, config, brief, CLI,
                    # and a real OpenMinion Agent against a scripted local OpenAI-compatible server
pytest -m live      # 2 tests against the real Binance API
```

`tests/test_agent_mock.py` runs the real `openminion.Agent` (no mocks inside OpenMinion)
against `tests/mock_openai.py`, a scripted `/v1/chat/completions` server. It checks the
tool-call loop (list → fetch → final JSON), that our tool schemas reach the provider,
typed output, and that `ProviderError`, `TurnTimeoutError` and `AgentOutputValidationError`
each show up as the documented type. It is not a model, so it says nothing about how well
a model judges campaigns.

## Status

- ✅ Install, imports, tools against live Binance, dry-run, 45 offline + 2 live tests.
- ✅ **First real-model run (2026-10-24):** `google/gemma-4-31b-it:free` on OpenRouter.
  The forced tool call worked, the `ScoutReport` JSON validated on the first try, and the
  run took about 30 s using 2 free requests. That day both new campaigns were trading
  competitions, so it correctly returned SKIP for both. See
  [`briefs/2026-10-24.md`](briefs/2026-10-24.md) and
  [WHAT_WE_LEARNED.md §11](WHAT_WE_LEARNED.md).
- ✅ A real OpenMinion `ProviderError(AUTH_ERROR)` from **Cortensor Portal** with a placeholder
  key, which shows the config reaches the real endpoint.
- ⏳ Cortensor Portal (`oss-20b`) and Gemma4-on-Portal runs wait on Portal access.

## Upstream contributions (OpenMinion)

| What | Link | State |
| --- | --- | --- |
| Bug: `@tool` fails with `from __future__ import annotations` + `Annotated` args | [openminion#376](https://github.com/openminion/openminion/issues/376) | Confirmed by a maintainer, fixed |
| Fix PR for #376 (resolve hints with `get_type_hints(include_extras=True)`, regression tests, changelog) | [openminion#383](https://github.com/openminion/openminion/pull/383) | ✅ Approved and merged into `dev` (2026-10-24) |
| Bug: `Agent.run` returns `run_state="completed"` on an internal runtime error | [openminion#384](https://github.com/openminion/openminion/issues/384) | Confirmed by a maintainer; fixed and released in [v0.1.12](https://github.com/openminion/openminion/releases/tag/v0.1.12); installed-package verification posted on the issue 2026-10-27 at the maintainer's request |
| Fix PR for #384 (a fatal runtime error now returns `run_state="failed"` with its structured error; recoverable tool errors still complete; regression tests, changelog) | [openminion#405](https://github.com/openminion/openminion/pull/405) | ✅ Approved and merged into `dev` (2026-10-25, all 18 upstream checks passed); shipped in v0.1.12 on PyPI (2026-10-26) and re-verified on the published package |
| Bug: `@tool` arguments typed as a Pydantic model or dataclass reach the function as a plain `dict` (tool crashes, run still reports `completed`) | [openminion#435](https://github.com/openminion/openminion/issues/435) | Reported 2026-10-26 on 0.1.12 and `dev` |
| Fix PR for #435 (pass validated model and dataclass instances through the `@tool` handler and argument repair; regression tests, changelog) | [openminion#436](https://github.com/openminion/openminion/pull/436) | 🔍 Open, in review. 2026-10-27: merged latest `dev` (incl. #432), changelog kept under Unreleased, Pydantic floor unchanged; the pre-existing SDK `Agent.run` alias bug is filed separately as [openminion#454](https://github.com/openminion/openminion/issues/454) and the strict xfail in #436 now links to it (round 3 pushed as `4adb6dc3`, all 18 CI checks green; reply and PR description handed to the account to paste because the app cannot comment upstream) |
| Bug: aliased `@tool` arguments (top-level or nested) rejected through SDK `Agent.run` by the shared runtime (pre-existing on `dev`, split out of #436) | [openminion#454](https://github.com/openminion/openminion/issues/454) | Filed 2026-10-27; tracked by a strict xfail in #436 |

Repro scripts for each are in [`repro/`](repro/) and need no API key.
All findings, including rough edges and docs gaps, are in
[WHAT_WE_LEARNED.md](WHAT_WE_LEARNED.md) and [BUILDING_BLOCKS.md](BUILDING_BLOCKS.md).

## Provenance

`airdrop_scout/binance_feed.py` reuses the Binance catalog fetch logic (`CATALOGS`, the
`bapi/apex/.../article/list/query` endpoint, fetch-with-retry and the FREE/CHEAP/PAID keyword
classifier) from the author's earlier MIT-licensed project **Airdrop Radar** (`radar.py`,
github.com/Afar88/airdrop-radar). The article-detail fetch, body flattening, tools, agent and
everything else are new in this repo. OpenMinion is Apache-2.0 and is used as a dependency.

## License

MIT, see [LICENSE](LICENSE).
