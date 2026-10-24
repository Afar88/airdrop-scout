# Building blocks

How Airdrop Scout is put together, and which OpenMinion features each piece uses.

```
             ┌──────────────── python -m airdrop_scout ────────────────┐
             │  .env → config.choose_provider() → config.write_config() │
             │  (project-local .openminion/agents.json, OPENMINION_HOME)│
             └───────────────┬──────────────────────────────────────────┘
                             │ Agent(config_path, agent_id="scout",
                             │       instructions, output_type=ScoutReport,
                             │       tools=[...], forced_tools=[list],
                             │       session_id=...)  with-block → close()
                             ▼
   ┌──────────────── OpenMinion runtime (0.1.10) ───────────────┐
   │ brain loop: decide → tool calls → finalize → judge          │
   │ provider: cortensor-portal | openrouter | openai | ollama   │
   └───────┬───────────────────────────────┬─────────────────────┘
           │ @tool                         │ final JSON text
           ▼                               ▼
  tools.list_recent_campaigns      Agent._coerce_output → ScoutReport
  tools.fetch_campaign_details     (AgentOutputValidationError on failure)
  tools.check_seen                         │
           │                               ▼
  binance_feed (reused radar.py)   brief.render (deadline UTC → WAT)
  timeutil.find_utc_times          briefs/YYYY-MM-DD.md, LATEST.md, .json
  memory.SeenStore ◄────────────── tools.mark_seen (app, after success)
```

| Block | File | OpenMinion feature | Notes |
| --- | --- | --- | --- |
| Binance feed | `airdrop_scout/binance_feed.py` | none | Reused from Airdrop Radar (MIT), plus detail fetch and body flattening |
| Tools | `airdrop_scout/tools.py` | `@tool` (name, docstring, `Annotated` arg descriptions, `idempotent=True`) | Dict outputs sized to OpenMinion's 1200-char / 16-item tool-message limits |
| Typed output | `airdrop_scout/models.py` | `output_type=` + `AgentOutputValidationError.raw_text` | Schema goes in the run message (not sent automatically) |
| Agent run | `airdrop_scout/agent.py` | `Agent`, `session_id`, `timeout_seconds`, `forced_tools`, context-manager close, `ProviderError` / `TurnTimeoutError` | Returns a `RunOutcome` instead of raising |
| Provider config | `airdrop_scout/config.py` | `config_path`, `agent_id`, provider blocks with `api_key_env`, `runtime.memory_enabled`, `runtime.log_level`, `OPENMINION_HOME` / `OPENMINION_DATA_ROOT` | Mirrors `openminion setup` presets; never writes secrets |
| Memory | `airdrop_scout/memory.py` | none (OpenMinion memory off on purpose) | JSON seen-store, capped at 1000 codes |
| Brief | `airdrop_scout/brief.py` | none | WAT conversion in Python, not by the model |
| Dry run | `airdrop_scout/dryrun.py` | calls the decorated tools directly | Keyword heuristics; no model |
| Offline provider | `tests/mock_openai.py` | real `Agent` against a scripted `/v1/chat/completions` | Proves wiring, tool loop and error types without a key |
| Repros | `repro/*.py` | none | Upstream bug reports (see WHAT_WE_LEARNED.md) |

## Next blocks (not built yet)

- [ ] First real-model run on Cortensor Portal (`oss-20b`); record latency, request count and JSON compliance.
- [ ] A/B the same day on OpenRouter `openai/gpt-4.1-mini` vs Cortensor `oss-20b` (`SCOUT_PROVIDER` switch only).
- [ ] `run_stream(on_delta=...)` progress output for long Cortensor runs.
- [ ] A `subagent` reviewer that double-checks DO_IT verdicts against the announcement text.
- [ ] Daily schedule (cron / GitHub Actions) that commits `briefs/LATEST.md`.
- [ ] Upstream: open issues for items 1–3 and 6–8 in WHAT_WE_LEARNED.md, and a fix PR for item 1.
