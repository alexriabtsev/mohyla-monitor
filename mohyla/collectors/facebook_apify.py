"""Public Facebook page posts via the Apify facebook-posts-scraper actor (APIFY_TOKEN).

The token is sent as an Authorization header (Apify supports both header and ?token=),
so it never appears in URLs that http.fetch logs or puts into FetchError messages.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Sequence

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from ._common import clean_text, disabled, make_title, parse_epoch, parse_iso, result, social_handles, unique

log = logging.getLogger(__name__)
NAME = "facebook_apify"
ENV = ("APIFY_TOKEN",)
RUN_URL = "https://api.apify.com/v2/acts/apify~facebook-posts-scraper/run-sync-get-dataset-items"
RESULTS_LIMIT = 20
RUN_TIMEOUT = 300.0  # actor runs synchronously; can take minutes
DEFAULT_MAX_PAGES = 50


def page_url(handle: str) -> str:
    h = handle.strip()
    return h if h.startswith("http") else f"https://www.facebook.com/{h.lstrip('@/')}"


def page_list(cfg: dict, people: Sequence[Person]) -> list[str]:
    raw = [*(cfg.get("facebook_pages") or []), *social_handles(people, "facebook")]
    pages = unique(page_url(r) for r in raw if str(r).strip())
    return pages[: int(cfg.get("facebook_max_pages", DEFAULT_MAX_PAGES))]


def row_published(row: dict[str, Any]) -> datetime | None:
    for key in ("time", "timestamp", "date"):
        value = row.get(key)
        dt = parse_iso(value) or parse_epoch(value)
        if dt:
            return dt
    return None


def row_author(row: dict[str, Any]) -> str:
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    return str(row.get("pageName") or user.get("name") or "")


def row_to_item(row: dict[str, Any], since: datetime) -> Item | None:
    url = row.get("postUrl") or row.get("url") or ""
    raw = str(row.get("text") or row.get("postText") or "")
    published = row_published(row)
    if row.get("error") or not url or not raw.strip() or published is None or published < since:
        return None
    author = row_author(row)
    return Item(url=url, title=make_title(raw), text=clean_text(raw),
                source=f"facebook:{author or 'unknown'}", kind="social", published=published,
                author=author)


def run_actor(client: httpx.Client, token: str, url: str, since: datetime) -> list[Any]:
    body = {"startUrls": [{"url": url}], "resultsLimit": RESULTS_LIMIT,
            "onlyPostsNewerThan": since.astimezone(timezone.utc).strftime("%Y-%m-%d")}
    resp = fetch(client, RUN_URL, method="POST", retries=1, json=body, timeout=RUN_TIMEOUT,
                 headers={"Authorization": f"Bearer {token}"})
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("unexpected Apify response shape")
    return data


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    token = os.environ.get(ENV[0])
    if not token:
        return disabled(NAME, ENV)
    pages = page_list(cfg, people)
    items: dict[str, Item] = {}
    errors: list[str] = []
    for url in pages:
        try:
            rows = run_actor(client, token, url, since)
        except (FetchError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, FetchError) else str(exc)
            log.warning("apify facebook %s failed: %s", url, reason)
            errors.append(f"{url}: {reason}")
            continue
        for row in rows:
            item = row_to_item(row, since) if isinstance(row, dict) else None
            if item is not None:
                items.setdefault(item.url, item)
    return result(NAME, items.values(), errors, attempts=len(pages))
