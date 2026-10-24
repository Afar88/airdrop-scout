"""--dry-run: exercise every tool against live Binance with NO model call.

Produces a rule-based ScoutReport (keyword + eligibility-line heuristics) so
the brief pipeline can be checked end to end. This is a baseline, not the
agent's judgement."""
from __future__ import annotations

import re

from . import tools
from .models import CampaignVerdict, ScoutReport

_VOLUME = re.compile(r"trading volume|trade at least|futures|net deposit|deposit at least|cumulative .*volume", re.I)
_NIGERIA_OUT = re.compile(r"nigeria", re.I)


def heuristic_verdict(item: dict, detail: dict | None) -> CampaignVerdict:
    hint = item["keyword_hint"]
    text = "\n".join((detail or {}).get("text_chunks", []))
    elig = " ".join((detail or {}).get("eligibility_lines", []))
    needs_volume = hint == "PAID" or bool(_VOLUME.search(text))
    if detail and detail.get("mentions_nigeria") and _NIGERIA_OUT.search(elig):
        nigeria = "excluded"
    else:
        nigeria = "unclear"
    times = (detail or {}).get("times") or []
    deadline = max((t["utc"] for t in times), default="")
    if needs_volume or nigeria == "excluded":
        verdict, reason = "SKIP", "Needs trading/deposits or excludes Nigeria (heuristic)."
    elif hint in ("FREE", "CHEAP"):
        verdict, reason = "MAYBE", f"Title looks {hint.lower()}; needs the agent to confirm (heuristic)."
    else:
        verdict, reason = "SKIP", "No free/cheap signal in title (heuristic)."
    return CampaignVerdict(
        code=item["code"], title=item["title"], url=item["url"], verdict=verdict,
        est_cost_usd=0.0 if hint == "FREE" else None, needs_trading_volume=needs_volume,
        nigeria=nigeria, steps=[], reward="", deadline_utc=deadline,
        red_flags=["dry-run: not reviewed by a model"], reason=reason,
    )


def dry_run(days: int = 2, max_details: int = 5, include_seen: bool = False) -> tuple[ScoutReport, list[str], dict]:
    campaigns, offset, errors = [], 0, []
    while offset is not None:
        page = tools.list_recent_campaigns(days=days, offset=offset)
        campaigns += page["campaigns"]
        errors = page["errors"]
        offset = page["next_offset"]
    items = [c for c in campaigns if include_seen or not c["seen"]]
    verdicts, fetched = [], 0
    for it in items:
        detail = None
        if it["keyword_hint"] != "PAID" and fetched < max_details:
            detail = tools.fetch_campaign_details(it["code"])
            fetched += 1
            if "error" in detail:
                detail = None
        verdicts.append(heuristic_verdict(it, detail))
    report = ScoutReport(
        summary=f"DRY RUN (no model): {len(items)} campaign(s) in the last {days} day(s); "
                f"{fetched} announcement(s) fetched. Verdicts below are keyword heuristics only.",
        campaigns=verdicts,
    )
    return report, errors, {"listed": len(campaigns), "fetched": fetched}
