"""Typed output the agent must return (validated by OpenMinion's output_type)."""
from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CampaignVerdict(BaseModel):
    code: str = Field(description="32-character Binance article code")
    title: str
    url: str
    verdict: Literal["DO_IT", "MAYBE", "SKIP"] = Field(
        description="DO_IT only if free or under $1, no trading volume, and Nigeria is not excluded")
    est_cost_usd: Optional[float] = Field(None, description="Minimum money the user must put in; 0 if free; null if unknown")
    needs_trading_volume: bool
    nigeria: Literal["available", "excluded", "unclear"]
    steps: list[str] = Field(default_factory=list, description="Short imperative steps to participate")
    reward: str = Field("", description="Reward pool / per-user reward as stated")
    deadline_utc: str = Field("", description="Campaign end as 'YYYY-MM-DD HH:MM' UTC, or '' if not stated")
    red_flags: list[str] = Field(default_factory=list)
    reason: str = Field(description="One sentence explaining the verdict")


class ScoutReport(BaseModel):
    summary: str = Field(description="Two sentences max: what is worth doing today")
    campaigns: list[CampaignVerdict]


def schema_hint() -> str:
    """Compact JSON schema to paste into the instructions.

    OpenMinion 0.1.10 validates `output_type` *after* the reply; it does not
    send the schema to the model, so the prompt has to carry it."""
    return json.dumps(ScoutReport.model_json_schema(), separators=(",", ":"))
