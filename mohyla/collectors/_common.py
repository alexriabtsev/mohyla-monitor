"""Helpers shared by collectors: text cleanup, date parsing, status building."""
from __future__ import annotations

import calendar
import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from bs4 import BeautifulSoup

from mohyla.models import CollectResult, Item, Person, SourceStatus

MAX_TEXT = 1500
MAX_TITLE = 140
_WS = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s")


def clean_text(raw: str | None, limit: int = MAX_TEXT) -> str:
    """HTML -> plain text, entities decoded, whitespace collapsed, trimmed to `limit`."""
    if not raw:
        return ""
    text = raw
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = _WS.sub(" ", html.unescape(text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def make_title(text: str, limit: int = MAX_TITLE) -> str:
    """First non-empty line, cut to its first sentence when the line is too long."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = _WS.sub(" ", line)
    if len(line) > limit:
        line = _SENTENCE_END.split(line, maxsplit=1)[0]
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


def utc(dt: datetime) -> datetime:
    """Naive datetimes are assumed UTC; aware ones are converted."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def from_struct(st: time.struct_time | None) -> datetime | None:
    # feedparser *_parsed values are already normalized to UTC
    if not st:
        return None
    return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)


def parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def parse_epoch(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    secs = value / 1000 if value > 1e12 else value  # tolerate milliseconds
    try:
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def json_object(resp: Any) -> dict:
    """Decoded JSON body that must be an object; ValueError otherwise."""
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def disabled(name: str, env_names: Sequence[str]) -> CollectResult:
    msg = f"disabled: set {' + '.join(env_names)}"
    return CollectResult(items=(), status=SourceStatus(name=name, ok=True, enabled=False, message=msg))


def result(name: str, items: Iterable[Item], errors: Sequence[str], attempts: int = 0) -> CollectResult:
    """Build a CollectResult; any error marks the source as failed but keeps partial items."""
    items_t = tuple(items)
    if not errors:
        return CollectResult(items=items_t, status=SourceStatus(name=name, ok=True, count=len(items_t)))
    head = f"{len(errors)}/{attempts} requests failed: " if attempts else ""
    msg = head + "; ".join(errors[:3]) + (" …" if len(errors) > 3 else "")
    return CollectResult(items=items_t, status=SourceStatus(name=name, ok=False, count=len(items_t), message=msg))


def social_handles(people: Sequence[Person], network: str) -> list[str]:
    return [h for p in people for net, h in p.socials if net == network and h]


def unique(values: Iterable[str]) -> list[str]:
    """Order-preserving dedupe."""
    return list(dict.fromkeys(values))
