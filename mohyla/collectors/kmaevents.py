"""Upcoming NaUKMA events from kmaevents.com (its public JSON API).

Events are not news: they go to a separate page, never into the digest. The last good
snapshot is kept in data/kmaevents.json, so an API outage shows yesterday's list.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import httpx

from mohyla import state
from mohyla.http import FetchError, fetch
from mohyla.models import SourceStatus

log = logging.getLogger(__name__)

SNAPSHOT = "kmaevents"
DEFAULTS = {
    "api_url": "https://kmaeventsapi-production.up.railway.app/api/events",
    "site_url": "https://kmaevents.com/events",
    "days_ahead": 60,
    "max_pages": 10,
}


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    kind: str            # eventType: talk, workshop, registration_deadline, ...
    starts: datetime
    ends: datetime | None
    club: str
    location: str
    description: str
    url: str             # the organiser's post (Instagram), or the kmaevents list
    calendar_url: str


@dataclass(frozen=True)
class Events:
    items: tuple[Event, ...]
    status: SourceStatus
    fetched: datetime | None   # when the shown list was fetched (older on an outage)


def settings(cfg: Mapping[str, Any]) -> dict[str, Any]:
    return {**DEFAULTS, **(cfg.get("kmaevents") or {})}


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_event(raw: Mapping[str, Any], site_url: str) -> Event | None:
    """One API record -> Event; None when it lacks an id, a title or a start time."""
    starts = _time(raw.get("startsAt"))
    title = " ".join(str(raw.get("title") or "").split())
    if not (raw.get("id") and title and starts):
        return None
    club = raw.get("club") if isinstance(raw.get("club"), dict) else {}
    return Event(
        id=str(raw["id"]), title=title, kind=str(raw.get("eventType") or "other"),
        starts=starts, ends=_time(raw.get("endsAt")),
        club=" ".join(str(club.get("name") or "").split()),
        location=" ".join(str(raw.get("location") or "").split()),
        description=" ".join(str(raw.get("description") or "").split()),
        url=str(raw.get("sourceUrl") or site_url), calendar_url=str(raw.get("gcalUrl") or ""))


def _fetch_all(client: httpx.Client, opts: Mapping[str, Any], start: datetime) -> list[dict]:
    """Every page from `start` on, following nextCursor up to max_pages."""
    out: list[dict] = []
    cursor = None
    for _ in range(int(opts["max_pages"])):
        params = {"from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        if cursor:
            params["cursor"] = cursor
        data = fetch(client, opts["api_url"], params=params).json()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("unexpected response: no 'items' list")
        out.extend(r for r in data["items"] if isinstance(r, dict))
        cursor = data.get("nextCursor")
        if not cursor:
            break
    return out


def upcoming(events: tuple[Event, ...] | list[Event], start: datetime,
             days_ahead: int) -> tuple[Event, ...]:
    """Events starting in [start, start + days_ahead), by time, without duplicate ids."""
    end = start + timedelta(days=days_ahead)
    unique = {e.id: e for e in events if start <= e.starts < end}
    return tuple(sorted(unique.values(), key=lambda e: (e.starts, e.title)))


# --- snapshot ---------------------------------------------------------------

def _to_json(e: Event) -> dict[str, Any]:
    d = asdict(e)
    d["starts"] = e.starts.isoformat()
    d["ends"] = e.ends.isoformat() if e.ends else None
    return d


def _from_json(d: Mapping[str, Any]) -> Event | None:
    try:
        return Event(**{**d, "starts": _time(d["starts"]), "ends": _time(d.get("ends"))})
    except (KeyError, TypeError):
        return None


def save_snapshot(events: Events) -> None:
    state.save_record(SNAPSHOT, {
        "fetched": events.fetched.isoformat() if events.fetched else None,
        "items": [_to_json(e) for e in events.items]})


def load_snapshot() -> tuple[list[Event], datetime | None]:
    try:
        rec = state.load_record(SNAPSHOT)
    except state.StateError as exc:
        log.error("events snapshot unreadable: %s", exc)
        return [], None
    items = [e for e in (_from_json(d) for d in rec.get("items") or [] if isinstance(d, dict))
             if e and e.starts]
    return items, _time(rec.get("fetched"))


# --- entry point ------------------------------------------------------------

def collect(client: httpx.Client, cfg: Mapping[str, Any], start: datetime,
            now: datetime) -> Events:
    """Upcoming events from `start` (the start of the Kyiv day); never raises."""
    opts = settings(cfg)
    days = int(opts["days_ahead"])
    try:
        raw = _fetch_all(client, opts, start)
    except (FetchError, ValueError, httpx.HTTPError) as exc:
        cached, fetched = load_snapshot()
        items = upcoming(cached, start, days)
        when = fetched.date().isoformat() if fetched else "never"
        log.warning("kmaevents failed (%s); showing the snapshot from %s", exc, when)
        return Events(items, SourceStatus("kmaevents.com", ok=False, count=len(items),
                                          message=f"{exc}; snapshot from {when}"), fetched)
    parsed = [e for e in (parse_event(r, opts["site_url"]) for r in raw) if e]
    items = upcoming(parsed, start, days)
    log.info("kmaevents: raw=%d upcoming=%d", len(raw), len(items))
    return Events(items, SourceStatus("kmaevents.com", ok=True, count=len(items)), now)
