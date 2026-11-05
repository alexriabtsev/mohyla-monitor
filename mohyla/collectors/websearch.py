"""LinkedIn / X / Threads / Instagram posts found through the Tavily Search API (TAVILY_API_KEY).

Each configured query is {query, domains}: Tavily restricts results to those domains
(include_domains) and to the last day (time_range), one basic search = 1 credit.
The key goes in the Authorization header, never in a URL.
"""
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
ENV = ("TAVILY_API_KEY",)
SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS = 20
DATE_FORMATS = ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d")  # Tavily dates vary by source


def hostname(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def result_published(res: dict[str, Any]) -> datetime | None:
    raw = res.get("published_date")
    dt = parse_iso(raw)
    if dt or not isinstance(raw, str):
        return dt
    for fmt in DATE_FORMATS:
        try:
            return utc(datetime.strptime(raw.strip(), fmt))
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
        published, extra = now, {"date_estimated": True}  # time_range=day keeps it recent
    if published < since:
        return None
    return Item(url=url, title=clean_text(res.get("title", ""), 300),
                text=clean_text(res.get("content", "")), source=f"web:{hostname(url)}",
                kind="social", published=published, extra=extra)


def parse_query(raw: Any) -> tuple[str, list[str]] | None:
    """'text' or {query: text, domains: [..]} -> (text, domains); None if malformed."""
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), []
    if isinstance(raw, dict) and str(raw.get("query") or "").strip():
        domains = [str(d).strip() for d in raw.get("domains") or [] if str(d).strip()]
        return str(raw["query"]).strip(), domains
    return None


def search(client: httpx.Client, key: str, query: str, domains: list[str]) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"query": query, "search_depth": "basic", "topic": "general",
                            "time_range": "day", "max_results": MAX_RESULTS}
    if domains:
        body["include_domains"] = domains
    resp = fetch(client, SEARCH_URL, method="POST", json=body,
                 headers={"Authorization": f"Bearer {key}"})
    results = json_object(resp).get("results") or []
    if not isinstance(results, list):
        raise ValueError("unexpected Tavily response shape")
    return [r for r in results if isinstance(r, dict)]


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    key = os.environ.get(ENV[0])
    if not key:
        return disabled(NAME, ENV)
    raw_queries = cfg.get("websearch_queries") or []
    queries = [q for q in (parse_query(r) for r in raw_queries) if q]
    if len(queries) < len(raw_queries):
        log.warning("websearch: skipped %d malformed queries", len(raw_queries) - len(queries))
    now = datetime.now(timezone.utc)
    items: dict[str, Item] = {}
    errors: list[str] = []
    for query, domains in queries:
        try:
            results = search(client, key, query, domains)
        except (FetchError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, FetchError) else str(exc)
            log.warning("tavily search %r failed: %s", query, reason)
            errors.append(f"{query}: {reason}")
            continue
        for res in results:
            item = to_item(res, since, now)
            if item is not None:
                items.setdefault(item.url, item)
    return result(NAME, items.values(), errors, attempts=len(queries))
