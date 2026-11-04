"""Official RSS/Atom feeds listed under cfg["rss"]."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Sequence

import feedparser
import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from ._common import clean_text, from_struct, result

log = logging.getLogger(__name__)
NAME = "rss"


def entry_text(entry: Any) -> str:
    """Prefer full content, fall back to summary."""
    content = entry.get("content") or []
    raw = content[0].get("value", "") if content else ""
    return clean_text(raw or entry.get("summary", ""))


def entry_published(entry: Any) -> datetime | None:
    return from_struct(entry.get("published_parsed") or entry.get("updated_parsed"))


def parse_feed(data: bytes, *, source: str, kind: str, since: datetime) -> list[Item]:
    """Parse feed bytes into Items newer than `since`. Raises ValueError on unusable feeds."""
    parsed = feedparser.parse(data)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.get('bozo_exception')}")
    items: list[Item] = []
    for entry in parsed.entries:
        published = entry_published(entry)
        link = entry.get("link", "")
        if published is None or not link:
            log.debug("skip entry without date/link in %s", source)
            continue
        if published < since:
            continue
        items.append(Item(
            url=link, title=clean_text(entry.get("title", ""), 300), text=entry_text(entry),
            source=source, kind=kind, published=published, author=entry.get("author", ""),
        ))
    return items


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    feeds = cfg.get("rss") or []
    items: list[Item] = []
    errors: list[str] = []
    for feed in feeds:
        name = feed.get("name") or feed.get("url", "?")
        try:
            resp = fetch(client, feed["url"])
            items.extend(parse_feed(resp.content, source=name, kind=feed.get("kind", "official"),
                                    since=since))
        except (FetchError, ValueError, KeyError) as exc:
            log.warning("rss feed %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
    return result(NAME, items, errors, attempts=len(feeds))
