"""Shared data contract. All models are immutable; use dataclasses.replace() to derive."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Roles of a person relative to the university
ALUMNUS = "alumnus"
STAFF = "staff"
STUDENT = "student"


@dataclass(frozen=True)
class Person:
    id: str                                   # "wd:Q123" | "wp:uk:Title" | "cand:<slug>"
    name_uk: str                              # canonical Ukrainian "Ім'я Прізвище"
    name_en: str = ""
    aliases: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()               # ALUMNUS / STAFF / STUDENT
    description: str = ""
    employers: tuple[str, ...] = ()           # Wikidata QIDs, used for graph edges
    socials: tuple[tuple[str, str], ...] = () # (network, handle), e.g. ("telegram", "durov")
    sources: tuple[str, ...] = ()             # provenance URLs
    prominence: float = 0.0                   # 0..1, e.g. from sitelink count


@dataclass(frozen=True)
class Edge:
    a: str                                    # Person.id
    b: str
    kind: str                                 # "employer" | "comention" | "snowball"
    weight: float = 1.0
    evidence: tuple[str, ...] = ()            # URLs


@dataclass(frozen=True)
class Item:
    url: str
    title: str
    text: str                                 # snippet / post body (plain text, trimmed)
    source: str                               # e.g. "ukma.edu.ua", "telegram:naukmanews"
    kind: str                                 # "official" | "media" | "social"
    published: datetime                       # timezone-aware
    author: str = ""
    person_ids: tuple[str, ...] = ()          # filled by match.py
    category: str = ""                        # filled by rank.py
    score: float = 0.0                        # filled by rank.py
    extra: dict = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class SourceStatus:
    name: str                                 # collector name, e.g. "telegram"
    ok: bool
    enabled: bool = True                      # False when a required key/secret is absent
    count: int = 0                            # items returned
    message: str = ""                         # human-readable reason on failure/disabled


@dataclass(frozen=True)
class CollectResult:
    items: tuple[Item, ...]
    status: SourceStatus
