"""CLI: python -m airdrop_scout [--dry-run] [--days N] [--timeout S]"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines); never overrides real env vars."""
    import os
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="airdrop_scout", description=__doc__)
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--dry-run", action="store_true", help="run tools against live Binance, no model call")
    p.add_argument("--timeout", type=float, default=None, help="per-run turn deadline in seconds")
    p.add_argument("--max-details", type=int, default=8)
    p.add_argument("--session", default=None, help="explicit OpenMinion session id")
    p.add_argument("--no-force-list", action="store_true", help="let the model decide whether to call list_recent_campaigns")
    p.add_argument("--no-mark-seen", action="store_true", help="do not remember covered campaigns")
    p.add_argument("--out", default=str(PROJECT / "briefs"))
    p.add_argument("--env-file", default=str(PROJECT / ".env"))
    a = p.parse_args(argv)
    load_dotenv(Path(a.env_file))

    from .config import choose_provider, isolate_openminion_home
    data_root = isolate_openminion_home(PROJECT)  # must run before openminion builds a runtime

    from . import tools
    from .brief import render
    from .timeutil import WAT

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(WAT).strftime("%Y-%m-%d")

    if a.dry_run:
        from .dryrun import dry_run
        report, errors, info = dry_run(a.days, max_details=min(a.max_details, 5))
        md = render(report, provider="none (dry-run)", errors=errors)
        path = out / f"dry-run-{stamp}.md"
        path.write_text(md)
        print(md)
        print(f"[dry-run] listed={info['listed']} fetched={info['fetched']} wrote {path}", file=sys.stderr)
        return 0

    choice = choose_provider()
    if choice.preset == "echo":
        print("No provider key found. Set SCOUT_PROVIDER and its key (see .env.example) or use --dry-run.",
              file=sys.stderr)
        return 1
    if not choice.has_key:
        print(f"{choice.key_env} is not set for SCOUT_PROVIDER={choice.preset}.", file=sys.stderr)
        return 1
    timeout = a.timeout or (900 if choice.preset == "cortensor-portal" else 300)

    from .agent import run_scout
    print(f"[scout] provider={choice.preset} model={choice.model} timeout={timeout:g}s", file=sys.stderr)
    res = run_scout(choice, config_dir=data_root, days=a.days, timeout_seconds=timeout,
                    session_id=a.session, max_details=a.max_details,
                    force_list_tool=not a.no_force_list)
    if not res.ok:
        print(f"[scout] {res.error_kind} failure (session={res.session_id}): {res.error}", file=sys.stderr)
        if res.raw_text:
            raw = out / f"failed-{stamp}.txt"
            raw.write_text(res.raw_text)
            print(f"[scout] raw model reply saved to {raw}", file=sys.stderr)
        return {"provider": 2, "timeout": 3, "validation": 4}.get(res.error_kind, 5)

    md = render(res.report, provider=f"{choice.preset}:{choice.model}")
    (out / f"{stamp}.md").write_text(md)
    (out / "LATEST.md").write_text(md)
    (out / f"{stamp}.json").write_text(res.report.model_dump_json(indent=2))
    if not a.no_mark_seen:
        for c in res.report.campaigns:
            tools.mark_seen(c.code)
    print(md)
    print(f"[scout] session={res.session_id} stats={json.dumps(res.stats)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
