"""Public Facebook pages and groups via Apify actors (APIFY_TOKEN).

One asynchronous actor run covers all pages and one covers all groups: start the run,
long-poll it until it finishes (or the time budget runs out, then abort it), and read the
dataset, keeping partial results. Every run is capped by item count and by spend
(maxItems / maxTotalChargeUsd), so a long source list cannot produce a surprise bill.

The token is sent as an Authorization header, so it never appears in URLs that
http.fetch logs or puts into FetchError messages.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from . import facebook_links as links
from ._common import clean_text, disabled, make_title, parse_epoch, parse_iso, result, social_handles

log = logging.getLogger(__name__)
NAME = "facebook_apify"
ENV = ("APIFY_TOKEN",)
API = "https://api.apify.com/v2"
POSTS_ACTOR = "apify~facebook-posts-scraper"
GROUPS_ACTOR = "apify~facebook-groups-scraper"
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
POLL_SECONDS = 60  # server-side long poll per request

DEFAULTS = {
    "facebook_max_pages": 200,
    "facebook_max_groups": 60,
    "facebook_max_discovered": 40,     # of the pages/groups found via links
    "facebook_posts_per_source": 8,
    "facebook_max_items": 2000,        # per actor run; keep >= sources x posts_per_source
    "facebook_max_charge_usd": 0.5,    # per actor run
    "facebook_timeout_minutes": 15,    # for both runs together
}


@dataclass(frozen=True)
class RunPlan:
    actor: str
    urls: tuple[str, ...]
    input: dict


def setting(cfg: dict, key: str) -> float:
    value = cfg.get(key)
    return float(DEFAULTS[key] if value is None else value)


def source_lists(cfg: dict, people: Sequence[Person]) -> tuple[list[str], list[str]]:
    """Pages and groups in priority order: config, people's profiles, discovered; capped."""
    found = (cfg.get("facebook_discovered") or [])[: int(setting(cfg, "facebook_max_discovered"))]
    raw = [*(cfg.get("facebook_pages") or []), *(cfg.get("facebook_groups") or []),
           *social_handles(people, "facebook"), *found]
    urls = links.unique_canonical(raw)
    pages = [u for u in urls if not links.is_group(u)]
    groups = [u for u in urls if links.is_group(u)]
    return (pages[: int(setting(cfg, "facebook_max_pages"))],
            groups[: int(setting(cfg, "facebook_max_groups"))])


def plans(cfg: dict, people: Sequence[Person], since: datetime) -> list[RunPlan]:
    pages, groups = source_lists(cfg, people)
    newer = since.astimezone(timezone.utc).strftime("%Y-%m-%d")
    per = int(setting(cfg, "facebook_posts_per_source"))
    cap = int(setting(cfg, "facebook_max_items"))
    for kind, urls in (("pages", pages), ("groups", groups)):
        if len(urls) * per > cap:
            log.warning("facebook: %d %s x %d posts exceeds facebook_max_items=%d; "
                        "the last sources may get nothing", len(urls), kind, per, cap)
    out = []
    if pages:
        out.append(RunPlan(POSTS_ACTOR, tuple(pages), {
            "startUrls": [{"url": u} for u in pages], "resultsLimit": per,
            "onlyPostsNewerThan": newer}))
    if groups:
        out.append(RunPlan(GROUPS_ACTOR, tuple(groups), {
            "startUrls": [{"url": u} for u in groups], "resultsLimit": per,
            "viewOption": "CHRONOLOGICAL", "onlyPostsNewerThan": newer}))
    return out


# ---------- rows -> items ----------

def row_published(row: dict[str, Any]) -> datetime | None:
    for key in ("time", "timestamp", "date"):
        value = row.get(key)
        dt = parse_iso(value) or parse_epoch(value)
        if dt:
            return dt
    return None


def row_author(row: dict[str, Any]) -> str:
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    return str(row.get("pageName") or user.get("name") or row.get("groupTitle") or "")


def row_source(row: dict[str, Any], author: str) -> str:
    """facebook:<page slug> when the input URL is known, so a person's own posts can be
    matched to their profile handle; otherwise the display name."""
    for key in ("facebookUrl", "inputUrl", "pageUrl"):
        value = row.get(key)
        slug = links.handle(value) if isinstance(value, str) else ""
        if slug.startswith("groups/"):  # a member's post: label it with the group, not a handle
            return f"facebook:{row.get('groupTitle') or slug}"
        if slug:
            return f"facebook:{slug}"
    return f"facebook:{author or 'unknown'}"


def row_to_item(row: dict[str, Any], since: datetime) -> Item | None:
    url = row.get("postUrl") or row.get("url") or ""
    raw = str(row.get("text") or row.get("postText") or "")
    published = row_published(row)
    if row.get("error") or not url or not raw.strip() or published is None or published < since:
        return None
    author = row_author(row)
    extra = {"fb_group": str(row["groupTitle"])} if row.get("groupTitle") else {}
    return Item(url=url, title=make_title(raw), text=clean_text(raw),
                source=row_source(row, author), kind="social", published=published,
                author=author, extra=extra)


# ---------- Apify API ----------

def _data(resp: httpx.Response) -> dict:
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError("unexpected Apify run response")
    return data


def start_run(client: httpx.Client, headers: dict, plan: RunPlan, cfg: dict) -> dict:
    params = {"maxItems": int(setting(cfg, "facebook_max_items")),
              "maxTotalChargeUsd": setting(cfg, "facebook_max_charge_usd")}
    resp = fetch(client, f"{API}/acts/{plan.actor}/runs", method="POST", retries=1,
                 params=params, json=plan.input, headers=headers, timeout=60.0)
    return _data(resp)


def wait_run(client: httpx.Client, headers: dict, run: dict, deadline: float) -> dict:
    """Long-poll until the run is terminal; abort it once the deadline passes."""
    while run.get("status") not in TERMINAL:
        if time.monotonic() >= deadline:
            log.warning("apify run %s over time budget; aborting", run["id"])
            try:
                resp = fetch(client, f"{API}/actor-runs/{run['id']}/abort", method="POST",
                             retries=1, headers=headers, timeout=60.0)
                run = _data(resp)
            except (FetchError, ValueError) as exc:  # still read what was scraped so far
                log.warning("apify abort %s failed: %s", run["id"], _reason(exc))
            return {**run, "status": "TIMED-OUT"}
        resp = fetch(client, f"{API}/actor-runs/{run['id']}", headers=headers,
                     params={"waitForFinish": POLL_SECONDS}, timeout=POLL_SECONDS + 30.0)
        run = _data(resp)
    return run


def dataset_rows(client: httpx.Client, headers: dict, run: dict, limit: int) -> list[Any]:
    dataset = run.get("defaultDatasetId")
    if not dataset:
        return []
    resp = fetch(client, f"{API}/datasets/{dataset}/items", headers=headers, timeout=120.0,
                 params={"clean": "true", "format": "json", "limit": limit})
    rows = resp.json()
    if not isinstance(rows, list):
        raise ValueError("unexpected Apify dataset response")
    return rows


def finish_run(client: httpx.Client, headers: dict, plan: RunPlan, run: dict, cfg: dict,
               deadline: float) -> tuple[list[Any], str | None]:
    """Rows of one started run, plus an error message if it did not fully succeed."""
    run = wait_run(client, headers, run, deadline)
    rows = dataset_rows(client, headers, run, int(setting(cfg, "facebook_max_items")))
    cost = run.get("usageTotalUsd")
    log.info("apify %s: status=%s sources=%d rows=%d cost=%s", plan.actor, run.get("status"),
             len(plan.urls), len(rows), cost if cost is not None else "?")
    error = None if run.get("status") == "SUCCEEDED" else f"{plan.actor}: {run.get('status')}"
    return rows, error


def _reason(exc: Exception) -> str:
    return exc.reason if isinstance(exc, FetchError) else str(exc)


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    token = os.environ.get(ENV[0])
    if not token:
        return disabled(NAME, ENV)
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + 60 * setting(cfg, "facebook_timeout_minutes")
    runs = plans(cfg, people, since)
    errors: list[str] = []
    started: list[tuple[RunPlan, dict]] = []
    for plan in runs:  # start all runs first so pages and groups scrape in parallel
        try:
            started.append((plan, start_run(client, headers, plan, cfg)))
        except (FetchError, ValueError) as exc:
            log.warning("apify %s failed to start: %s", plan.actor, _reason(exc))
            errors.append(f"{plan.actor}: {_reason(exc)}")
    items: dict[str, Item] = {}
    for plan, run in started:
        try:
            rows, error = finish_run(client, headers, plan, run, cfg, deadline)
        except (FetchError, ValueError) as exc:
            log.warning("apify %s failed: %s", plan.actor, _reason(exc))
            errors.append(f"{plan.actor}: {_reason(exc)}")
            continue
        if error:
            errors.append(error)  # partial rows are still used
        for row in rows:
            item = row_to_item(row, since) if isinstance(row, dict) else None
            if item is not None:
                items.setdefault(item.url, item)
    return result(NAME, items.values(), errors, attempts=len(runs))
