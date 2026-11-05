"""People from uk.wikipedia categories (NaUKMA alumni, kmbs alumni, scholars)."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import ALUMNUS, STAFF, Person, qualified_role
from mohyla.people.names import canonical_name

log = logging.getLogger(__name__)

API_URL = "https://uk.wikipedia.org/w/api.php"
PAGEPROPS_BATCH = 50
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_SKIP_PREFIXES = ("Список", "Перелік")


def role_for_category(category: str, unit: str = "") -> str:
    base = STAFF if "Науковці" in category or "Викладачі" in category else ALUMNUS
    return qualified_role(base, unit)


def category_entries(cfg: dict) -> list[tuple[str, str]]:
    """wikipedia_categories items: 'Категорія:…' or {name: 'Категорія:…', unit: kmbs}."""
    out = []
    for entry in cfg.get("wikipedia_categories", []):
        if isinstance(entry, dict) and entry.get("name"):
            out.append((str(entry["name"]), str(entry.get("unit") or "")))
        elif isinstance(entry, str) and entry.strip():
            out.append((entry.strip(), ""))
    return out


def display_name(title: str) -> str:
    """'Грицак Ярослав Йосипович (історик)' -> 'Ярослав Грицак'.

    Only the unambiguous 3-token 'Прізвище Ім'я По-батькові' form is reordered;
    2-token titles keep their order (Wikidata labels win on merge anyway).
    """
    return canonical_name(_PAREN_RE.sub("", title).strip())


def _category_members(client: httpx.Client, category: str) -> list[str]:
    params: dict[str, Any] = {
        "action": "query", "list": "categorymembers", "cmtitle": category,
        "cmnamespace": 0, "cmtype": "page", "cmlimit": 500, "format": "json",
    }
    titles: list[str] = []
    while True:
        try:
            data = fetch(client, API_URL, params=params).json()
        except (FetchError, ValueError) as exc:
            log.warning("category %s: stopping after %d titles: %s", category, len(titles), exc)
            return titles
        titles += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            return titles
        params = {**params, "cmcontinue": cont}


def _wikibase_items(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    """title -> QID for the given titles (batched)."""
    out: dict[str, str] = {}
    for i in range(0, len(titles), PAGEPROPS_BATCH):
        batch = titles[i:i + PAGEPROPS_BATCH]
        params = {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                  "titles": "|".join(batch), "format": "json", "redirects": 1}
        try:
            data = fetch(client, API_URL, params=params).json()
        except (FetchError, ValueError) as exc:
            log.warning("pageprops batch %d failed: %s", i // PAGEPROPS_BATCH, exc)
            continue
        out.update(_parse_pageprops(data))
    return out


def _parse_pageprops(data: dict) -> dict[str, str]:
    query = data.get("query", {})
    # Map normalized/redirected titles back to the titles we asked for.
    back = {r["to"]: r["from"] for key in ("normalized", "redirects") for r in query.get(key, [])}
    out: dict[str, str] = {}
    for page in query.get("pages", {}).values():
        qid = page.get("pageprops", {}).get("wikibase_item")
        if qid:
            title = page.get("title", "")
            out[back.get(title, title)] = qid
    return out


def _person(title: str, qid: str | None, role: str) -> Person:
    name = display_name(title)
    plain = _PAREN_RE.sub("", title).strip()
    return Person(
        id=f"wd:{qid}" if qid else f"wp:uk:{title}",
        name_uk=name,
        aliases=(plain,) if plain != name else (),
        roles=(role,),
        sources=(f"https://uk.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",),
    )


def fetch_category_people(client: httpx.Client, cfg: dict) -> list[Person]:
    """Members of cfg['wikipedia_categories'] as Person records (one per title+role)."""
    by_category: dict[tuple[str, str], list[str]] = {}
    for category, unit in category_entries(cfg):
        titles = [t for t in _category_members(client, category) if not t.startswith(_SKIP_PREFIXES)]
        log.info("wikipedia: %d pages in %s", len(titles), category)
        by_category[(category, unit)] = titles
    all_titles = list(dict.fromkeys(t for ts in by_category.values() for t in ts))
    qids = _wikibase_items(client, all_titles)
    return [_person(t, qids.get(t), role_for_category(c, unit))
            for (c, unit), titles in by_category.items() for t in titles]
