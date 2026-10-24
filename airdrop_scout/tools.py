"""OpenMinion tools exposed to the Airdrop Scout agent.

Each function is a normal Python function decorated with the public
`openminion.tool` decorator, so it can be (a) handed to `Agent(tools=[...])`
and (b) called directly in tests and in --dry-run mode.

Tools return small dicts shaped for OpenMinion's tool-message compaction
(0.1.10, modules/brain/constants.py): every string is cut at 1200 chars and
every list/dict at 16 items/keys before the model sees it. So announcement text
is returned as <=1100-char chunks (max 14) and campaign lists are paged (15 per
call). Returning one big JSON string would be cut to its first 1200 chars
(WHAT_WE_LEARNED.md, finding 4).

NOTE: this module deliberately does NOT use `from __future__ import annotations`.
In openminion 0.1.10 `@tool` builds its argument model from raw (string)
annotations, so `Annotated[...]` under PEP 563 fails at run time with
"class-not-fully-defined" (see WHAT_WE_LEARNED.md, finding 1).
"""

import re
from typing import Annotated

from pydantic import Field

from openminion import tool

from . import binance_feed
from .memory import SeenStore
from .timeutil import find_utc_times

# Module-level seams so tests can swap the network opener and the seen-store.
OPENER = binance_feed._get_json
SEEN = SeenStore()

MAX_DAYS = 14
DEFAULT_MAX_CHARS = 8000
PAGE = 15            # < 16-item list limit
CHUNK = 1100         # < 1200-char string limit
MAX_CHUNKS = 14      # < 16-item list limit

_ELIGIBILITY_RE = re.compile(
    r"nigeria|restricted|not eligible|ineligible|exclud|jurisdiction|region|country|countries"
    r"|kyc|verified|verification|minimum|at least|trading volume|deposit|net purchase|hold",
    re.I,
)


def chunk_text(text: str, size: int = CHUNK, max_chunks: int = MAX_CHUNKS) -> list[str]:
    """Split on line boundaries into <=size pieces (hard-split very long lines)."""
    chunks, cur = [], ""
    for line in (text or "").splitlines():
        while len(line) > size:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) + 1 > size:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks[:max_chunks]


@tool(idempotent=True)
def list_recent_campaigns(
    days: Annotated[int, Field(description="Look-back window in days (1-14).")] = 2,
    offset: Annotated[int, Field(description="Paging offset; use next_offset from the previous call.")] = 0,
) -> dict:
    """List Binance campaign announcements (Latest Activities, Airdrop, New Listings)
    released in the last `days` days, newest first, 15 per page. Each item has code,
    title, url, catalog, released_utc, keyword_hint (FREE/CHEAP/PAID/OTHER, a
    title-keyword guess only) and seen (true if an earlier daily brief covered it).
    If next_offset is not null, call again with offset=next_offset."""
    days = max(1, min(int(days), MAX_DAYS))
    offset = max(0, int(offset))
    rows, errors = binance_feed.scan(days, opener=OPENER)
    seen = set(SEEN.load())
    page = rows[offset:offset + PAGE]
    for r in page:
        r["seen"] = r["code"] in seen
    nxt = offset + PAGE if offset + PAGE < len(rows) else None
    return {"days": days, "total": len(rows), "offset": offset, "next_offset": nxt,
            "campaigns": page, "errors": errors[:5]}


def eligibility_lines(text: str, limit: int = 16) -> list[str]:
    """Lines anywhere in the announcement that talk about regions, KYC,
    minimums, holding, deposits or trading volume (often buried in the T&Cs)."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and _ELIGIBILITY_RE.search(line) and line not in out:
            out.append(line[:400])
        if len(out) >= limit:
            break
    return out


@tool(idempotent=True)
def fetch_campaign_details(
    url_or_code: Annotated[str, Field(description="Binance announcement URL or its 32-character article code.")],
    max_chars: Annotated[int, Field(description="Max characters of announcement text to return (500-15000).")] = DEFAULT_MAX_CHARS,
) -> dict:
    """Fetch one Binance announcement. Returns title, url, text_chunks (the
    announcement as plain-text pieces, in order), every '(UTC)' timestamp found
    with its WAT (Africa/Lagos, UTC+1) equivalent, eligibility_lines (region/KYC/
    minimum/holding/volume lines from anywhere in the text) and mentions_nigeria."""
    try:
        d = binance_feed.fetch_detail(url_or_code, opener=OPENER)
    except (ValueError, LookupError) as e:
        return {"error": str(e)}
    text = d.pop("text")
    max_chars = max(500, min(int(max_chars), CHUNK * MAX_CHUNKS))
    d.update({
        "text_chunks": chunk_text(text[:max_chars]),
        "truncated": len(text) > max_chars,
        "full_length": len(text),
        "times": find_utc_times(text)[:16],
        "eligibility_lines": eligibility_lines(text, limit=16),
        "mentions_nigeria": "nigeria" in text.lower(),
    })
    return d


@tool(idempotent=True)
def check_seen(code: Annotated[str, Field(description="Binance article code.")]) -> dict:
    """Return whether this campaign was already covered by an earlier daily brief."""
    return {"code": code, "seen": SEEN.has(code)}


@tool
def mark_seen(code: Annotated[str, Field(description="Binance article code.")]) -> dict:
    """Remember that this campaign was covered, so later briefs skip it."""
    return {"code": code, "added": SEEN.add(code)}


AGENT_TOOLS = [list_recent_campaigns, fetch_campaign_details, check_seen]
