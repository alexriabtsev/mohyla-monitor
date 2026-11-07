"""Monthly spend ledger for the paid Facebook scrapers (Apify, pay per post).

The Apify free plan gives $5 of usage per billing cycle. The ledger (data/facebook_spend.json)
records what each run cost, spreads what is left evenly over the days left in the cycle, and
remembers when Facebook was last scraped, so the next run only pays for newer posts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from mohyla import state
from mohyla.collectors._common import parse_iso

log = logging.getLogger(__name__)
LEDGER = "facebook_spend"
MIN_RUN_USD = 0.02  # below this a run would return a post or two: skip it


@dataclass(frozen=True)
class Ledger:
    cycle: str            # first day of the billing cycle, YYYY-MM-DD
    usd: float            # spent in this cycle
    last_run: datetime | None


def cycle_start(today: date, cycle_day: int) -> date:
    """Start of the billing cycle containing `today` (cycle_day clamped to 1..28)."""
    day = min(max(int(cycle_day), 1), 28)
    if today.day >= day:
        return today.replace(day=day)
    prev = today.replace(day=1) - timedelta(days=1)
    return prev.replace(day=day)


def days_left(today: date, cycle_day: int) -> int:
    start = cycle_start(today, cycle_day)
    nxt = (start.replace(day=28) + timedelta(days=5)).replace(day=start.day)
    return max((nxt - today).days, 1)


def load(now: datetime, cycle_day: int) -> Ledger:
    raw = state.load_record(LEDGER)
    cycle = cycle_start(now.date(), cycle_day).isoformat()
    last = parse_iso(raw.get("last_run"))
    usd = float(raw.get("usd") or 0.0) if raw.get("cycle") == cycle else 0.0
    return Ledger(cycle=cycle, usd=usd, last_run=last)


def save(ledger: Ledger) -> None:
    state.save_record(LEDGER, {
        "cycle": ledger.cycle, "usd": round(ledger.usd, 4),
        "last_run": ledger.last_run.isoformat() if ledger.last_run else None})


def allowance(ledger: Ledger, budget: float, today: date, cycle_day: int) -> float:
    """Today's share of what is left in the cycle."""
    return max(budget - ledger.usd, 0.0) / days_left(today, cycle_day)


def record(ledger: Ledger, spent: float, ran_at: datetime | None) -> Ledger:
    return replace(ledger, usd=ledger.usd + spent, last_run=ran_at or ledger.last_run)


def run_cost(run: dict[str, Any], rows: int, price_per_post: float) -> float:
    """What a run cost: pay-per-event charges when Apify reports them, never less than
    rows x price (the run object may lag behind the charges), plus platform usage."""
    events = 0.0
    counts = run.get("chargedEventCounts") or {}
    prices = (((run.get("pricingInfo") or {}).get("pricingPerEvent") or {})
              .get("actorChargeEvents") or {})
    if isinstance(counts, dict) and isinstance(prices, dict):
        for name, count in counts.items():
            spec = prices.get(name)
            price = spec.get("eventPriceUsd") if isinstance(spec, dict) else None
            if isinstance(count, (int, float)) and isinstance(price, (int, float)):
                events += count * price
    platform = run.get("usageTotalUsd")
    platform = float(platform) if isinstance(platform, (int, float)) else 0.0
    return max(events, rows * price_per_post) + platform
