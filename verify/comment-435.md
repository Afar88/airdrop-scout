Installed-package verification of #436 on the published **openminion==0.1.15** (PyPI wheel, uploaded 2026-10-29; tag `v0.1.15` contains merge `988ac4ec`, compare shows 0 behind). The fix also shipped in 0.1.14.

**Environment**
- Clean `uv venv` per run, outside any checkout; Linux aarch64, Python 3.11.17
- Run A: pydantic 2.14.1 (resolved by `pip install openminion==0.1.15`)
- Run B: pydantic 2.10.6 (pydantic-core 2.27.2)
- Provider: none, a local scripted OpenAI-compatible server (`om_mock.py`, stdlib only)

**Commands**
```
uv venv -p 3.11 /tmp/v15 && uv pip install -p /tmp/v15/bin/python "openminion==0.1.15"
uv venv -p 3.11 /tmp/v15p210 && uv pip install -p /tmp/v15p210/bin/python "openminion==0.1.15" "pydantic==2.10.6"
git clone https://github.com/Afar88/airdrop-scout && cd airdrop-scout && git checkout de65965c
/tmp/v15/bin/python verify/verify_435.py ; /tmp/v15p210/bin/python verify/verify_435.py
```
Script (self-contained, asserts every check, exit code = failures): https://github.com/Afar88/airdrop-scout/blob/de65965c948938efaea50400addf12f3ad9ded29/verify/verify_435.py

**Results: 8/8 pass on both Pydantic 2.14.1 and 2.10.6 (exit 0)**
- A, original repro, `handler(validated args model)`: `'solana >= 3 over 7d'`, received `Filter`, `Window`
- B, raw mapping and `model_dump()` mapping: both deliver `Filter`/`Window`; default `min_score=0` applied
- C, Pydantic dataclass: `PdSpan(start=4, end=10)` with default; `end=500` rejected (`less_than_equal`)
- D, nested: `Order` → `Inner` + `list[Item]` (std dataclass) all instances; defaults level=3, qty=1, priority=2, tag/note None
- E, rejected with `ValidationError`: wrong type `list_type`, nested constraint `less_than_equal`, top-level constraint `greater_than_equal`, missing `missing`, extra top-level input `extra_forbidden`, invalid enum `enum`, dataclass missing field `missing`
- F, #436 alias case: handler accepts validated model, `model_dump()`, `model_dump(by_alias=True)`, alias and field-name mappings (`['3','3','3','4','5']`); args model still alias-only; -1 / extra / empty rejected
- G, ordinary SDK `Agent.run` (original repro): tool received `Filter`/`Window`, tool status `success`, output `'solana >= 3 over 7d'`, `run_state=completed`
- H, SDK `Agent.run` with nested model and Pydantic dataclass: instances delivered, `success`, `completed`

The original `repro/repro_tool_model_args_arrive_as_dict.py` on 0.1.15 prints `handler(validated model) -> solana >= 3 over 7d`, `types the tool function received: {'f': 'Filter', 'window': 'Window'}`, `tool result the model saw: success`, `run_state='completed'`.

Negative control: the same harness on published 0.1.12 fails all 8 checks (`AttributeError: 'dict' object has no attribute 'chain'`, etc.), so it does catch the bug.

**Caveats**
- SDK nested alias through `Agent.run` still fails as expected (tool `failed`, `INVALID_ARGUMENT`, handler not called). That is #454, printed as INFO only and not counted here.
- Linux only, with the scripted server; no real provider, macOS or Windows.

Outputs: https://github.com/Afar88/airdrop-scout/tree/de65965c948938efaea50400addf12f3ad9ded29/verify/results
