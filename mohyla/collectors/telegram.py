"""Public Telegram channels via the official web preview https://t.me/s/<channel>."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Iterable, Sequence

import httpx
from bs4 import BeautifulSoup

from mohyla.http import FetchError, fetch
from mohyla.models import CollectResult, Item, Person

from ._common import clean_text, make_title, parse_iso, result, social_handles, unique

log = logging.getLogger(__name__)
NAME = "telegram"
PREVIEW_URL = "https://t.me/s/{}"
DEFAULT_DELAY = 1.0
DEFAULT_MAX_CHANNELS = 300

# t.me/<name> or telegram.me/<name>; "+" and "joinchat" are invites, "s" is the preview prefix
_LINK = re.compile(r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(\+?[A-Za-z0-9_]+)", re.I)
_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")  # 4..32 chars (short collectible names exist)
_RESERVED = {"s", "c", "joinchat", "addstickers", "addemoji", "share", "proxy", "socks",
             "login", "iv", "setlanguage", "addtheme", "boost", "contact", "invoice"}


def normalize_channel(raw: str) -> str | None:
    """'@Name', 'https://t.me/Name/12', 'name' -> 'name'; None if not a channel username."""
    value = raw.strip()
    m = _LINK.search(value)
    name = m.group(1) if m else value.lstrip("@").split("/")[0]
    if not _USERNAME.match(name) or name.lower() in _RESERVED:
        return None
    return name.lower()


def discover_channels(items: Sequence[Item]) -> set[str]:
    """Channel usernames linked from item text/url (no invites, previews or bots)."""
    found: set[str] = set()
    for item in items:
        for m in _LINK.finditer(f"{item.url} {item.text}"):
            name = m.group(1)
            if name.startswith("+") or name.lower().endswith("bot"):
                continue
            norm = normalize_channel(name)
            if norm:
                found.add(norm)
    return found


def channel_list(cfg: dict, people: Sequence[Person]) -> list[str]:
    raw = [*(cfg.get("telegram_channels") or []), *social_handles(people, "telegram"),
           *(cfg.get("telegram_discovered") or [])]
    names = unique(n for n in (normalize_channel(str(r)) for r in raw) if n)
    cap = int(cfg.get("telegram_max_channels", DEFAULT_MAX_CHANNELS))
    if len(names) > cap:
        log.info("telegram: capping %d channels to %d", len(names), cap)
    return names[:cap]


def message_text(node: Any) -> str:
    """Message text with <br> preserved as newlines (used for the title)."""
    for br in node.find_all("br"):
        br.replace_with("\n")
    return node.get_text()


def parse_message(msg: Any, channel: str, title: str, since: datetime) -> Item | None:
    post = msg.get("data-post") or ""
    text_node = msg.select_one(".tgme_widget_message_text")
    time_node = msg.select_one("time[datetime]")
    if not post or text_node is None or time_node is None:
        return None
    published = parse_iso(time_node.get("datetime"))
    if published is None or published < since:
        return None
    raw = message_text(text_node)
    text = clean_text(raw)
    if not text:
        return None
    return Item(url=f"https://t.me/{post}", title=make_title(raw), text=text,
                source=f"telegram:{channel}", kind="social", published=published, author=title)


def parse_page(html: str, channel: str, since: datetime) -> list[Item] | None:
    """Items from a t.me/s page; None when the page is not a public channel preview."""
    soup = BeautifulSoup(html, "html.parser")
    messages = soup.select(".tgme_widget_message")
    header = soup.select_one(".tgme_channel_info_header_title")
    if header is None and not messages:
        return None
    owner = soup.select_one(".tgme_widget_message_owner_name")
    title = clean_text((header or owner).get_text()) if (header or owner) else channel
    parsed = (parse_message(m, channel, title, since) for m in messages)
    return [it for it in parsed if it is not None]


def fetch_channel(client: httpx.Client, channel: str, since: datetime) -> list[Item]:
    """Raises FetchError for real failures; returns [] for missing/non-channel pages."""
    try:
        resp = fetch(client, PREVIEW_URL.format(channel))
    except FetchError as exc:
        if exc.reason == "HTTP 404":
            log.debug("telegram: %s not found", channel)
            return []
        raise
    items = parse_page(resp.text, channel, since)
    if items is None:
        log.debug("telegram: %s is not a public channel", channel)
        return []
    return items


def collect(client: httpx.Client, cfg: dict, since: datetime, people: Sequence[Person]) -> CollectResult:
    channels = channel_list(cfg, people)
    delay = float(cfg.get("telegram_delay", DEFAULT_DELAY))
    items: list[Item] = []
    errors: list[str] = []
    for i, channel in enumerate(channels):
        if i and delay > 0:
            time.sleep(delay)  # be polite: ~1 request per second
        try:
            items.extend(fetch_channel(client, channel, since))
        except FetchError as exc:
            log.warning("telegram %s failed: %s", channel, exc.reason)
            errors.append(f"{channel}: {exc.reason}")
    return result(NAME, unique_by_url(items), errors, attempts=len(channels))


def unique_by_url(items: Iterable[Item]) -> list[Item]:
    return list({it.url: it for it in items}.values())
