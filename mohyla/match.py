"""Link items to people and decide which items belong in the digest.

An item is kept when any of these holds:
- it mentions Mohyla explicitly (keyword in title/text);
- it is a Google News hit for a configured Mohyla query (mention is in the article body,
  which RSS does not carry) -> marked extra["body_match"];
- it mentions a known Mohyla person other than the account owner;
- it is a person's own post with achievement wording (appointment, award, grant...),
  at most one such post per owner per run, to keep personal chatter out.
"""
from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Callable, Sequence

from mohyla.models import Item, Person
from mohyla.people.names import name_pattern

log = logging.getLogger(__name__)

# Names that are too ambiguous to match without Mohyla context in the same item
MIN_PROMINENCE_WITHOUT_CONTEXT = 0.35

Predicate = Callable[[Item], bool]


def build_matchers(people: Sequence[Person]) -> list[tuple[Person, re.Pattern]]:
    matchers = []
    for person in people:
        pattern = name_pattern(person)
        if pattern is not None:
            matchers.append((person, pattern))
    log.info("built %d name matchers for %d people", len(matchers), len(people))
    return matchers


def social_owners(people: Sequence[Person]) -> dict[str, str]:
    return {handle.lower().lstrip("@"): p.id for p in people for _, handle in p.socials}


def owner_id(item: Item, owners: dict[str, str]) -> str | None:
    """Person whose own social account published the item (source 'network:<handle>')."""
    if item.kind != "social" or ":" not in item.source:
        return None
    return owners.get(item.source.split(":", 1)[1].lower())


def link_item(
    item: Item,
    matchers: Sequence[tuple[Person, re.Pattern]],
    owner: str | None,
    relevant: bool,
) -> Item:
    haystack = f"{item.title}\n{item.text}"
    found = [
        person.id for person, pattern in matchers
        if pattern.search(haystack)
        and (relevant or person.prominence >= MIN_PROMINENCE_WITHOUT_CONTEXT)
    ]
    ids = tuple(dict.fromkeys(([owner] if owner else []) + found))
    return replace(item, person_ids=ids)


def is_query_hit(item: Item, trusted_queries: set[str]) -> bool:
    return item.source.startswith("gnews:") and item.extra.get("query") in trusted_queries


def _decide(item: Item, linked: Item, owner: str | None, relevant: bool,
            is_achievement: Predicate) -> str | None:
    """Return the reason to keep the item, or None to drop it."""
    if relevant:
        return "keyword"
    if any(pid != owner for pid in linked.person_ids):
        return "person"
    if owner and is_achievement(item):
        return "own_achievement"
    return None


def filter_and_link(
    items: Sequence[Item],
    people: Sequence[Person],
    is_relevant: Predicate,
    is_achievement: Predicate = lambda _: False,
    trusted_queries: Sequence[str] = (),
) -> list[Item]:
    matchers = build_matchers(people)
    owners = social_owners(people)
    trusted = set(trusted_queries)
    kept: list[Item] = []
    own_posts: set[str] = set()
    for item in items:
        keyword = is_relevant(item)
        body = not keyword and is_query_hit(item, trusted)
        owner = owner_id(item, owners)
        linked = link_item(item, matchers, owner, keyword or body)
        reason = "body" if body else _decide(item, linked, owner, keyword, is_achievement)
        if reason is None or (reason == "own_achievement" and owner in own_posts):
            continue
        if reason == "own_achievement":
            own_posts.add(owner)
        kept.append(replace(linked, extra={**linked.extra, "keep_reason": reason,
                                           "body_match": reason == "body"}))
    log.info("kept %d of %d items after relevance/person filter", len(kept), len(items))
    return kept
