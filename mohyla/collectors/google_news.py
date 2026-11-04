"""Google News RSS search, Ukrainian and US-English editions."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Sequence

import feedparser
import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from ._common import clean_text, from_struct, result

log = logging.getLogger(__name__)
NAME = "google_news"
SEARCH_URL = "https://news.google.com/rss/search"
EDITIONS = (
    {"hl": "uk", "gl": "UA", "ceid": "UA:uk"},
    {"hl": "en-US", "gl": "US", "ceid": "US:en"},
)
WINDOW = " when:2d"
_NON_WORD = re.compile(r"[\W_]+")


def strip_publisher(title: str, publisher: str) -> str:
    """Drop the trailing ' - Publisher' that Google News appends to titles."""
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -len(publisher) - 3].strip()
    if not publisher and " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title.strip()


def norm_title(title: str) -> str:
    return _NON_WORD.sub(" ", title.lower()).strip()


def entry_to_item(entry: Any, query: str = "") -> Item | None:
    published = from_struct(entry.get("published_parsed") or entry.get("updated_parsed"))
    link = entry.get("link", "")
    if published is None or not link:
        return None
    src = entry.get("source") or {}
    publisher = (src.get("title") or "").strip()
    title = strip_publisher(clean_text(entry.get("title", ""), 400), publisher)
    extra = {"query": query} if query else {}
    if src.get("href"):
        extra = {**extra, "publisher_url": src["href"]}
    return Item(
        url=link, title=title, text=clean_text(entry.get("summary", "")),
        source=f"gnews:{publisher or 'unknown'}", kind="media", published=published,
        author=publisher, extra=extra,
    )


def search(client: httpx.Client, query: str, edition: dict[str, str]) -> list[Any]:
    resp = fetch(client, SEARCH_URL, params={"q": query + WINDOW, **edition})
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.get('bozo_exception')}")
    return list(parsed.entries)


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    queries = cfg.get("google_news_queries") or []
    seen: set[str] = set()
    items: list[Item] = []
    errors: list[str] = []
    for query in queries:
        for edition in EDITIONS:
            try:
                entries = search(client, query, edition)
            except (FetchError, ValueError) as exc:
                log.warning("google news %r (%s) failed: %s", query, edition["ceid"], exc)
                errors.append(f"{query} [{edition['ceid']}]: {exc}")
                continue
            for entry in entries:
                item = entry_to_item(entry, query)
                if item is None or item.published < since:
                    continue
                key = norm_title(item.title)
                if key and key not in seen:
                    seen.add(key)
                    items.append(item)
    return result(NAME, items, errors, attempts=len(queries) * len(EDITIONS))
