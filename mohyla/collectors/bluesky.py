"""Bluesky post search (requires an app password: BSKY_HANDLE + BSKY_APP_PASSWORD)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Sequence

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from ._common import clean_text, disabled, json_object, make_title, parse_iso, result

log = logging.getLogger(__name__)
NAME = "bluesky"
ENV = ("BSKY_HANDLE", "BSKY_APP_PASSWORD")
XRPC = "https://bsky.social/xrpc/"
SEARCH_LIMIT = 50


def create_session(client: httpx.Client, handle: str, password: str) -> str:
    resp = fetch(client, XRPC + "com.atproto.server.createSession", method="POST", retries=0,
                 json={"identifier": handle, "password": password})
    token = json_object(resp).get("accessJwt")
    if not token:
        raise ValueError("createSession returned no accessJwt")
    return token


def post_to_item(post: dict[str, Any], since: datetime) -> Item | None:
    record = post.get("record") or {}
    author = post.get("author") or {}
    uri, handle = post.get("uri", ""), author.get("handle", "")
    published = parse_iso(record.get("createdAt")) or parse_iso(post.get("indexedAt"))
    raw = record.get("text") or ""
    if not (uri and handle and raw and published) or published < since:
        return None
    rkey = uri.rsplit("/", 1)[-1]
    return Item(
        url=f"https://bsky.app/profile/{handle}/post/{rkey}", title=make_title(raw),
        text=clean_text(raw), source=f"bluesky:{handle}", kind="social", published=published,
        author=author.get("displayName") or handle, extra={"uri": uri},
    )


def search(client: httpx.Client, token: str, query: str, since: datetime) -> list[dict[str, Any]]:
    since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = fetch(client, XRPC + "app.bsky.feed.searchPosts",
                 params={"q": query, "sort": "latest", "since": since_iso, "limit": SEARCH_LIMIT},
                 headers={"Authorization": f"Bearer {token}"})
    posts = json_object(resp).get("posts")
    if not isinstance(posts, list):
        raise ValueError("searchPosts: unexpected response shape")
    return posts


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    if not all(os.environ.get(n) for n in ENV):
        return disabled(NAME, ENV)
    try:
        token = create_session(client, os.environ[ENV[0]], os.environ[ENV[1]])
    except (FetchError, ValueError) as exc:
        log.warning("bluesky login failed: %s", exc)
        return result(NAME, [], [f"login failed: {exc}"])
    queries = cfg.get("bluesky_queries") or []
    items: dict[str, Item] = {}
    errors: list[str] = []
    for query in queries:
        try:
            posts = search(client, token, query, since)
        except (FetchError, ValueError) as exc:
            log.warning("bluesky search %r failed: %s", query, exc)
            errors.append(f"{query}: {exc}")
            continue
        for post in posts:
            item = post_to_item(post, since) if isinstance(post, dict) else None
            if item is not None:
                items.setdefault(item.url, item)
    return result(NAME, items.values(), errors, attempts=len(queries))
