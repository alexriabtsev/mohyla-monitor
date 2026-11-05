"""Facebook URL handling: canonical page/group URLs, handles, and links found in items."""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from mohyla.models import Item

from ._common import unique

# facebook.com/<slug> or facebook.com/groups/<slug>; m./www./uk-ua. hosts, fb.com short host
# The lookbehind keeps look-alike hosts out ('notfacebook.com', 'shopfb.com').
_LINK = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:[a-z-]+\.)?(?:facebook|fb)\.com/(groups/)?([A-Za-z0-9.\-_]+)",
    re.I)
# Paths that are not pages or groups (posts, media, share widgets, login, etc.)
_RESERVED = {
    "sharer", "sharer.php", "share", "share.php", "dialog", "login", "login.php", "photo",
    "photo.php", "photos", "watch", "reel", "reels", "story.php", "permalink.php", "events",
    "profile.php", "pages", "hashtag", "help", "policies", "privacy", "plugins", "tr", "l.php",
    "home.php", "marketplace", "gaming", "media", "notes", "video.php", "videos", "search",
    "public", "people", "business", "ads", "settings", "messages", "friends", "about",
    "groups", "posts", "story", "permalink", "p", "page", "profile", "home",
}
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_]{1,79}$")


def normalize(raw: str) -> str | None:
    """'naukma', '@naukma', 'https://m.facebook.com/naukma/posts/1' -> canonical page/group URL."""
    value = str(raw).strip()
    m = _LINK.search(value)
    if m:
        group, slug = bool(m.group(1)), m.group(2)
    elif "://" in value or "/" in value.strip("/") or " " in value:
        return None  # some other site, or not a bare handle
    else:
        group, slug = False, value.lstrip("@").strip("/")
    if not _SLUG.match(slug) or slug.lower() in _RESERVED:
        return None
    return f"https://www.facebook.com/{'groups/' if group else ''}{slug}/"


def is_group(url: str) -> bool:
    return "/groups/" in url


def handle(url: str) -> str:
    """Lowercase page slug or 'groups/<slug>' used as the item source suffix."""
    canon = normalize(url) or ""
    return canon.removeprefix("https://www.facebook.com/").strip("/").lower()


def discover(items: Sequence[Item]) -> set[str]:
    """Canonical page/group URLs linked from the text of social posts that mention Mohyla.

    News snippets are skipped: outlets link their own pages, and every discovered source
    is scraped (and paid for) daily."""
    found: set[str] = set()
    for item in items:
        if item.kind != "social" or item.extra.get("keep_reason") != "keyword":
            continue
        for m in _LINK.finditer(item.text):
            canon = normalize(m.group(0))
            if canon:
                found.add(canon)
    return found


def unique_canonical(raw: Iterable[str]) -> list[str]:
    return unique(c for c in (normalize(r) for r in raw if str(r).strip()) if c)
