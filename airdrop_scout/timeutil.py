"""UTC -> WAT helpers. Binance writes times as `YYYY-MM-DD HH:MM (UTC)`."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

WAT = ZoneInfo("Africa/Lagos")  # UTC+1 all year, no DST

_UTC_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})(?::\d{2})?\s*\(?UTC\)?")


def utc_to_wat(value: str) -> str:
    """'2026-11-20 00:00' or '2026-11-20 00:00 (UTC)' -> '2026-11-20 01:00 WAT'.

    Returns '' for empty/unknown input instead of guessing.
    """
    value = (value or "").strip()
    if not value or value.lower() in {"unknown", "none", "n/a", "-"}:
        return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?", value)
    if not m:
        return ""
    day, hm = m.group(1), m.group(2) or "00:00"
    dt = datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return dt.astimezone(WAT).strftime("%Y-%m-%d %H:%M WAT")


def find_utc_times(text: str) -> list[dict]:
    """Every explicit `(UTC)` timestamp in an announcement, with its WAT value."""
    seen, out = set(), []
    for m in _UTC_RE.finditer(text or ""):
        utc = f"{m.group(1)} {int(m.group(2).split(':')[0]):02d}:{m.group(2).split(':')[1]}"
        if utc in seen:
            continue
        seen.add(utc)
        out.append({"utc": utc, "wat": utc_to_wat(utc)})
    return out
