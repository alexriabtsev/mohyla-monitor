"""LinkedIn / X / Threads posts found through the Brave Search API (BRAVE_API_KEY)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Sequence
from urllib.parse import urlparse

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from ._common import clean_text, disabled, json_object, parse_iso, result, utc

log = logging.getLogger(__name__)
NAME = "websearch"
ENV = ("BRAVE_API_KEY",)
SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
AGE_FORMATS = ("%B %d, %Y", "%b %d, %Y")  # Brave's human "age", e.g. "November 4, 2026"


def hostname(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def result_published(res: dict[str, Any]) -> datetime | None:
    dt = parse_iso(res.get("page_age")) or parse_iso(res.get("age"))
    if dt:
        return dt
    for fmt in AGE_FORMATS:
        try:
            return utc(datetime.strptime(str(res.get("age", "")).strip(), fmt))
        except ValueError:
            continue
    return None


def to_item(res: dict[str, Any], since: datetime, now: datetime) -> Item | None:
    url = res.get("url") or ""
    if not url:
        return None
    published = result_published(res)
    extra: dict[str, Any] = {}
    if published is None:
        published, extra = now, {"date_estimated": True}  # freshness=pd keeps it recent
    if published < since:
        return None
    return Item(url=url, title=clean_text(res.get("title", ""), 300),
                text=clean_text(res.get("description", "")), source=f"web:{hostname(url)}",
                kind="social", published=published, extra=extra)


def search(client: httpx.Client, key: str, query: str) -> list[dict[str, Any]]:
    resp = fetch(client, SEARCH_URL, params={"q": query, "freshness": "pd", "count": 20},
                 headers={"X-Subscription-Token": key, "Accept": "application/json"})
    results = (json_object(resp).get("web") or {}).get("results") or []
    if not isinstance(results, list):
        raise ValueError("unexpected Brave response shape")
    return [r for r in results if isinstance(r, dict)]


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    key = os.environ.get(ENV[0])
    if not key:
        return disabled(NAME, ENV)
    queries = cfg.get("websearch_queries") or []
    now = datetime.now(timezone.utc)
    items: dict[str, Item] = {}
    errors: list[str] = []
    for query in queries:
        try:
            results = search(client, key, query)
        except (FetchError, ValueError) as exc:
            log.warning("brave search %r failed: %s", query, exc)
            errors.append(f"{query}: {exc}")
            continue
        for res in results:
            item = to_item(res, since, now)
            if item is not None:
                items.setdefault(item.url, item)
    return result(NAME, items.values(), errors, attempts=len(queries))
