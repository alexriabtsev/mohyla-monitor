"""LinkedIn / X / Threads / Instagram posts found through the Tavily Search API (TAVILY_API_KEY).

Each configured query is {query, domains}: Tavily restricts results to those domains
(include_domains) and to the last day (time_range), one basic search = 1 credit.
The key goes in the Authorization header, never in a URL.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from urllib.parse import urlparse

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from ._common import clean_text, disabled, json_object, make_title, parse_iso, result, utc

log = logging.getLogger(__name__)
NAME = "websearch"
ENV = ("TAVILY_API_KEY",)
SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS = 20
DATE_FORMATS = ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d")  # Tavily dates vary by source
# Only individual posts: profile, company and search pages (e.g. linkedin.com/in/<name>)
# describe people, not news, and would put private individuals' profiles in the digest.
POST_PATH = re.compile(
    r"^/(?:posts/|pulse/|feed/update/"                 # LinkedIn
    r"|[^/]+/status/\d+"                               # X
    r"|@[^/]+/post/"                                    # Threads
    r"|(?:[^/]+/)?(?:p|reel)/[\w-]+)")                 # Instagram


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


# Post IDs carry their creation time, which beats Tavily's date (often absent; its
# time_range filters by index date, so an old post can come back as "today").
_SHORTCODE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_IG_CODE = re.compile(r"/(?:p|reel|post)/([\w-]{11})(?:[/?]|$)")     # Instagram, Threads
_X_ID = re.compile(r"/status/(\d{15,})")
_LI_ID = re.compile(r"(?:activity|ugcPost|share)[-:](\d{15,})")
IG_EPOCH_MS = 1314220021721   # Instagram media ids: ms since this epoch << 23
X_EPOCH_MS = 1288834974657    # X snowflake: ms since this epoch << 22
EARLIEST_ID_TIME = datetime(2015, 1, 1, tzinfo=timezone.utc)


def _ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def id_published(url: str, now: datetime) -> datetime | None:
    """Creation time decoded from the post id in the URL; None if absent or implausible."""
    path = urlparse(url).path or ""
    dt = None
    if (m := _IG_CODE.search(path)) and hostname(url).startswith(("instagram.", "threads.")):
        num = 0
        for ch in m.group(1):
            num = num * 64 + _SHORTCODE.index(ch)
        dt = _ms((num >> 23) + IG_EPOCH_MS)
    elif (m := _X_ID.search(path)) and hostname(url) in ("x.com", "twitter.com"):
        dt = _ms((int(m.group(1)) >> 22) + X_EPOCH_MS)
    elif (m := _LI_ID.search(url)) and hostname(url).endswith("linkedin.com"):
        dt = _ms(int(m.group(1)) >> 22)
    if dt is None or not EARLIEST_ID_TIME <= dt <= now + timedelta(days=1):
        return None
    return dt


def is_post(url: str) -> bool:
    return bool(POST_PATH.match(urlparse(url).path or ""))


# X result titles: 'Name on X: "tweet text..." / X', 'Name on X / X', 'Name - X'
_X_TITLE = re.compile(r'^(?P<name>.+?)\s+(?:on X|on Twitter|-\s*X)(?::\s*"(?P<tweet>.*?)"?)?(?:\s*/\s*X)?$')
MIN_BLURB_URLS = 2  # same snippet on this many posts of one host = a profile bio, not a post


def x_parts(title: str) -> tuple[str, str]:
    """(author name, tweet text from the title); empty strings when not an X-style title."""
    m = _X_TITLE.match(title.strip())
    return (m.group("name").strip(), (m.group("tweet") or "").strip()) if m else ("", "")


def blurbs(results: Sequence[dict[str, Any]]) -> set[tuple[str, str]]:
    """(host, snippet) pairs shared by several posts: search engines often show the
    author's profile bio instead of the post, which would mislabel every post."""
    urls: dict[tuple[str, str], set[str]] = {}
    for res in results:
        text = clean_text(res.get("content", ""))
        if text and res.get("url"):
            urls.setdefault((hostname(res["url"]), text), set()).add(res["url"])
    return {key for key, found in urls.items() if len(found) >= MIN_BLURB_URLS}


def to_item(res: dict[str, Any], since: datetime, now: datetime,
            bios: set[tuple[str, str]] = frozenset()) -> Item | None:
    url = res.get("url") or ""
    if not url or not is_post(url):
        return None
    published = id_published(url, now) or result_published(res)
    extra: dict[str, Any] = {}
    if published is None:
        published, extra = now, {"date_estimated": True}  # no id, no date: assume new
    if published < since:
        return None
    host = hostname(url)
    title = clean_text(res.get("title", ""), 300)
    text = clean_text(res.get("content", ""))
    if (host, text) in bios:
        text = ""
    author = ""
    if host in ("x.com", "twitter.com"):
        author, tweet = x_parts(title)
        text = text or tweet
        title = make_title(text)
        extra = {**extra, "handle": urlparse(url).path.strip("/").split("/")[0]}
    if not text.strip():
        return None  # nothing of the post itself to judge or show
    return Item(url=url, title=title or make_title(text), text=text, source=f"web:{host}",
                kind="social", published=published, author=author, extra=extra)


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
    raw: dict[str, dict[str, Any]] = {}
    for query, domains in queries:
        try:
            results = search(client, key, query, domains)
        except (FetchError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, FetchError) else str(exc)
            log.warning("tavily search %r failed: %s", query, reason)
            errors.append(f"{query}: {reason}")
            continue
        for res in results:
            if res.get("url"):
                raw.setdefault(res["url"], res)
    bios = blurbs(list(raw.values()))
    for res in raw.values():
        item = to_item(res, since, now, bios)
        if item is not None:
            items[item.url] = item
    return result(NAME, items.values(), errors, attempts=len(queries))
