"""Collector registry. Each module exposes collect(client, cfg, since, people) -> CollectResult."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Sequence

import httpx

from mohyla.models import CollectResult, Item, Person, SourceStatus

from . import bluesky, facebook_apify, google_news, rss, telegram, websearch

log = logging.getLogger(__name__)

Collector = Callable[[httpx.Client, dict, datetime, Sequence[Person]], CollectResult]

ALL_COLLECTORS: tuple[tuple[str, Collector], ...] = (
    ("rss", rss.collect),
    ("google_news", google_news.collect),
    ("telegram", telegram.collect),
    ("bluesky", bluesky.collect),
    ("facebook_apify", facebook_apify.collect),
    ("websearch", websearch.collect),
)


def run_all(
    client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person],
) -> tuple[list[Item], list[SourceStatus]]:
    """Run every collector; an unexpected exception only fails that one source."""
    items: list[Item] = []
    statuses: list[SourceStatus] = []
    for name, collect in ALL_COLLECTORS:
        try:
            res = collect(client, cfg, since, people)
        except Exception as exc:  # noqa: BLE001 - isolation boundary
            log.exception("collector %s crashed", name)
            statuses.append(SourceStatus(name=name, ok=False, message=f"crashed: {type(exc).__name__}: {exc}"))
            continue
        log.info("collector %s: ok=%s enabled=%s count=%d %s", name, res.status.ok,
                 res.status.enabled, res.status.count, res.status.message)
        items.extend(res.items)
        statuses.append(res.status)
    return items, statuses


__all__ = ["ALL_COLLECTORS", "run_all", "bluesky", "facebook_apify", "google_news", "rss",
           "telegram", "websearch"]
