"""The OpenMinion agent: tools in, typed ScoutReport out."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from openminion import (
    Agent,
    AgentOutputValidationError,
    ProviderError,
    TurnTimeoutError,
)

from . import tools
from .config import ProviderChoice, write_config
from .models import ScoutReport, schema_hint
from .timeutil import WAT

# Kept short on purpose: in openminion 0.1.10 `Agent(instructions=...)` lands in
# the [IDENTITY] block, which is truncated to roughly 640-890 characters
# depending on the brain phase (WHAT_WE_LEARNED.md, finding 3). The full method
# and the JSON schema therefore travel in the run message instead.
INSTRUCTIONS = (
    "You are Airdrop Scout, a careful, read-only triage agent for Binance campaign "
    "announcements. Your user lives in Nigeria (WAT, UTC+1) and only does campaigns that "
    "are free or cost under $1, with no trading volume. Use the tools to read the real "
    "announcements, never invent facts, and when asked for JSON reply with JSON only."
)

TASK = """Now is {now}.
Task: scout Binance campaigns from the last {days} day(s) for my user and return a JSON report.

User profile:
- lives in Nigeria; total spend must be FREE or under $1;
- will NOT trade for volume, use futures, deposit more than $1, stake, or buy tokens;
- happy to post on Binance Square, do quizzes, check-ins, learn-and-earn, votes, red packets,
  or hold a tiny balance (< $1).

Method:
1. Call list_recent_campaigns(days={days}); if next_offset is not null call it again with that
   offset. Ignore items with "seen": true.
2. For each remaining campaign that could plausibly fit, call fetch_campaign_details(url_or_code=<code>)
   and read text_chunks, eligibility_lines and times. Titles that obviously require trading/deposits
   can be marked SKIP without fetching. Fetch at most {max_details} announcements.
3. Verdict per campaign:
   DO_IT = free or < $1, no trading volume, Nigeria not excluded.
   MAYBE = probably fits but something important is unclear (region list not shown, cost unclear).
   SKIP  = needs trading volume / deposits / > $1, or Nigeria is excluded.
   nigeria = "excluded" only if Nigeria (or a group that clearly contains it) is listed as restricted;
   "unclear" if restricted regions are mentioned but not named; "available" if explicitly open.
4. deadline_utc = campaign END exactly as written in UTC, format 'YYYY-MM-DD HH:MM'; '' if none.
   Do not convert to WAT; the app does that.
5. red_flags: e.g. KYC required, tiny reward per user, lottery-only, referral spam, off-platform links,
   first-come-first-served, locked/vested rewards, vague terms.
6. Include every unseen campaign (SKIPs too).

FINAL ANSWER: only a JSON object (no prose, no code fences) matching this JSON schema:
{schema}"""

@dataclass
class RunOutcome:
    ok: bool
    report: ScoutReport | None = None
    error_kind: str = ""
    error: str = ""
    raw_text: str = ""
    session_id: str = ""
    stats: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def build_message(days: int, max_details: int = 8, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return TASK.format(now=now.astimezone(WAT).strftime("%Y-%m-%d %H:%M WAT"), days=days,
                       max_details=max_details, schema=schema_hint())


def run_scout(choice: ProviderChoice, *, config_dir: Path, days: int = 2,
              timeout_seconds: float = 600, session_id: str | None = None,
              max_details: int = 8, force_list_tool: bool = True) -> RunOutcome:
    """One bounded agent run with an explicit session, deadline and clean close."""
    config_path = write_config(choice, config_dir)
    session_id = session_id or f"airdrop-scout-{datetime.now(WAT).strftime('%Y%m%d-%H%M%S')}"
    try:
        # `with` closes the runtime the Agent created, even on errors.
        with Agent(
            name="airdrop_scout",
            config_path=str(config_path),
            agent_id="scout",
            instructions=INSTRUCTIONS,
            output_type=ScoutReport,
            tools=tools.AGENT_TOOLS,
            forced_tools=["list_recent_campaigns"] if force_list_tool else None,
            session_id=session_id,
        ) as agent:
            result = agent.run(build_message(days, max_details), timeout_seconds=timeout_seconds)
    except ProviderError as exc:
        return RunOutcome(False, error_kind="provider",
                          error=f"{exc.code}: {exc.message} details={json.dumps(exc.details, default=str)[:600]}",
                          session_id=session_id)
    except TurnTimeoutError as exc:
        return RunOutcome(False, error_kind="timeout", error=str(exc), session_id=session_id)
    except AgentOutputValidationError as exc:
        return RunOutcome(False, error_kind="validation", error=str(exc)[:1000],
                          raw_text=exc.raw_text or "", session_id=session_id)
    return RunOutcome(True, report=result.output, raw_text=result.text,
                      session_id=result.session_id or session_id,
                      stats=result.stats, metadata=result.metadata)
