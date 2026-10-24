"""Render a ScoutReport into the daily markdown brief (deadlines in WAT)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .models import CampaignVerdict, ScoutReport
from .timeutil import WAT, utc_to_wat

ORDER = {"DO_IT": 0, "MAYBE": 1, "SKIP": 2}
BADGE = {"DO_IT": "🟢 DO IT", "MAYBE": "🟡 MAYBE", "SKIP": "🔴 SKIP"}


def _cost(c: CampaignVerdict) -> str:
    if c.est_cost_usd is None:
        return "unknown"
    return "free" if c.est_cost_usd == 0 else f"~${c.est_cost_usd:g}"


def render(report: ScoutReport, *, provider: str = "", now: datetime | None = None,
           errors: Iterable[str] = ()) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        "# Airdrop Scout — daily brief",
        "",
        f"_Generated {now.astimezone(WAT).strftime('%Y-%m-%d %H:%M WAT')}"
        + (f" · model: {provider}" if provider else "") + "_",
        "",
        report.summary.strip(),
        "",
    ]
    picks = sorted(report.campaigns, key=lambda c: (ORDER[c.verdict], c.deadline_utc or "9999"))
    for c in picks:
        if c.verdict == "SKIP":
            continue
        wat = utc_to_wat(c.deadline_utc) or "not stated"
        lines += [
            f"## {BADGE[c.verdict]} — [{c.title}]({c.url})",
            f"- **Deadline:** {wat}",
            f"- **Cost:** {_cost(c)} · **Trading volume:** {'yes' if c.needs_trading_volume else 'no'} · **Nigeria:** {c.nigeria}",
            f"- **Reward:** {c.reward or 'not stated'}",
        ]
        if c.steps:
            lines.append("- **Do this:**")
            lines += [f"  {i}. {s}" for i, s in enumerate(c.steps, 1)]
        if c.red_flags:
            lines.append("- **Red flags:** " + "; ".join(c.red_flags))
        lines += [f"- _Why:_ {c.reason}", ""]
    skipped = [c for c in picks if c.verdict == "SKIP"]
    if skipped:
        lines += ["## Skipped", ""]
        lines += [f"- [{c.title}]({c.url}) — {c.reason}" for c in skipped]
        lines.append("")
    if not report.campaigns:
        lines += ["Nothing new today.", ""]
    for e in errors:
        lines.append(f"> ⚠️ {e}")
    lines += ["", "_Read-only scout. Not financial advice; always check the official announcement._", ""]
    return "\n".join(lines)
