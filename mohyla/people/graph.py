"""People graph: merging sources, employer / co-mention edges, snowball candidates.

All functions are pure: inputs are never mutated, new objects are returned.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import replace
from itertools import combinations
from urllib.parse import urlsplit
from typing import Iterable

from mohyla.models import ALUMNUS, Edge, Item, Person
from mohyla.people.names import extract_snowball_mentions, name_pattern, normalize

log = logging.getLogger(__name__)

MAX_EMPLOYER_GROUP = 40
MAX_EVIDENCE = 5
_ID_PRIORITY = {"wd": 0, "wp": 1, "cand": 2}


def _union(*seqs: Iterable) -> tuple:
    return tuple(dict.fromkeys(x for seq in seqs for x in seq))


def _rank(person: Person) -> int:
    return _ID_PRIORITY.get(person.id.split(":", 1)[0], 9)


def _combine(a: Person, b: Person) -> Person:
    """Merge two records of the same person; the higher-priority id wins."""
    main, other = (a, b) if _rank(a) <= _rank(b) else (b, a)
    extra_names = [other.name_uk] if normalize(other.name_uk) != normalize(main.name_uk) else []
    aliases = tuple(x for x in _union(main.aliases, other.aliases, extra_names)
                    if normalize(x) != normalize(main.name_uk))
    return replace(
        main,
        name_en=main.name_en or other.name_en,
        aliases=aliases,
        roles=_union(main.roles, other.roles),
        description=main.description or other.description,
        employers=_union(main.employers, other.employers),
        socials=_union(main.socials, other.socials),
        sources=_union(main.sources, other.sources),
        prominence=max(main.prominence, other.prominence),
    )


def _merge_by_id(people: Iterable[Person]) -> list[Person]:
    by_id: dict[str, Person] = {}
    for p in people:
        by_id[p.id] = _combine(by_id[p.id], p) if p.id in by_id else p
    return list(by_id.values())


def _merge_by_name(people: list[Person]) -> list[Person]:
    """Fold records with equal normalized names, unless both are distinct Wikidata items."""
    out: list[Person] = []
    by_name: dict[str, int] = {}
    for p in sorted(people, key=_rank):
        key = normalize(p.name_uk)
        idx = by_name.get(key)
        if idx is not None and not (out[idx].id.startswith("wd:") and p.id.startswith("wd:")):
            out[idx] = _combine(out[idx], p)
            continue
        if idx is None:
            by_name[key] = len(out)
        out.append(p)
    return out


def merge_people(*lists: list[Person]) -> list[Person]:
    """Merge people from several sources by id, then by normalized Ukrainian name."""
    merged = _merge_by_name(_merge_by_id(p for lst in lists for p in lst))
    return sorted(merged, key=lambda p: (-p.prominence, p.name_uk))


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def employer_edges(people: list[Person], exclude: set[str] = frozenset(),
                   max_group: int = MAX_EMPLOYER_GROUP) -> list[Edge]:
    """Edges between people sharing a (non-generic, non-excluded) employer."""
    members: dict[str, list[str]] = defaultdict(list)
    for p in people:
        for emp in dict.fromkeys(p.employers):
            if emp not in exclude:
                members[emp].append(p.id)
    shared: dict[tuple[str, str], list[str]] = defaultdict(list)
    for emp, ids in members.items():
        ids = sorted(set(ids))
        if len(ids) > max_group:
            log.debug("skip generic employer %s (%d people)", emp, len(ids))
            continue
        for a, b in combinations(ids, 2):
            shared[(a, b)].append(emp)
    return [Edge(a=a, b=b, kind="employer", weight=float(len(emps)),
                 evidence=tuple(f"https://www.wikidata.org/wiki/{e}" for e in emps))
            for (a, b), emps in sorted(shared.items())]


def comention_edges(items: list[Item]) -> list[Edge]:
    """Edges between people mentioned together; weight = number of shared items."""
    weight: Counter = Counter()
    evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in items:
        ids = sorted(set(item.person_ids))
        for a, b in combinations(ids, 2):
            weight[(a, b)] += 1
            if len(evidence[(a, b)]) < MAX_EVIDENCE and item.url not in evidence[(a, b)]:
                evidence[(a, b)].append(item.url)
    return [Edge(a=a, b=b, kind="comention", weight=float(w), evidence=tuple(evidence[(a, b)]))
            for (a, b), w in sorted(weight.items())]



def merge_edges(old: Iterable[Edge], new: Iterable[Edge]) -> list[Edge]:
    """Accumulate edges across runs: same (a, b, kind) sums weight and unions evidence."""
    merged: dict[tuple[str, str, str], Edge] = {}
    for edge in [*old, *new]:
        a, b = _pair(edge.a, edge.b)
        key = (a, b, edge.kind)
        prev = merged.get(key)
        if prev is None:
            merged[key] = replace(edge, a=a, b=b)
            continue
        evidence = tuple(dict.fromkeys(prev.evidence + edge.evidence))[:MAX_EVIDENCE]
        merged[key] = replace(prev, weight=prev.weight + edge.weight, evidence=evidence)
    return sorted(merged.values(), key=lambda e: (e.kind, e.a, e.b))

# --- snowball candidates ------------------------------------------------------------

class _KnownMatcher:
    """Answers 'is this name an already known person?'."""

    def __init__(self, known: list[Person]):
        self._names = {normalize(n) for p in known for n in (p.name_uk, p.name_en, *p.aliases) if n}
        self._patterns = [pat for p in known if (pat := name_pattern(p)) is not None]

    def __contains__(self, name: str) -> bool:
        if normalize(name) in self._names:
            return True
        return any(pat.fullmatch(name) for pat in self._patterns)


def _new_record(name: str, when: str) -> dict:
    return {"name": name, "count": 0, "evidence": [], "first_seen": when,
            "last_seen": when, "role_votes": {}, "role": ALUMNUS}


def _with_mention(rec: dict, url: str, when: str, role: str) -> dict:
    votes = {**rec.get("role_votes", {})}
    votes[role] = votes.get(role, 0) + 1
    return {
        **rec,
        # count distinct outlets, so one syndicated story cannot promote a person alone
        "count": len({urlsplit(u).netloc.lower() for u in [*rec.get("evidence", []), url]}),
        "evidence": [*rec.get("evidence", []), url],
        "first_seen": min(rec.get("first_seen", when), when),
        "last_seen": max(rec.get("last_seen", when), when),
        "role_votes": votes,
        "role": max(votes, key=lambda r: (votes[r], r != ALUMNUS)),
    }


def update_candidates(candidates: dict[str, dict], items: list[Item],
                      known: list[Person]) -> dict[str, dict]:
    """Return a NEW candidates dict updated with snowball mentions found in items."""
    is_known = _KnownMatcher(known)
    out = {k: {**v} for k, v in candidates.items()}
    for item in items:
        when = item.published.isoformat()
        for name, role in extract_snowball_mentions(f"{item.title}\n{item.text}"):
            if name in is_known:
                continue
            key = normalize(name)
            rec = out.get(key) or _new_record(name, when)
            if item.url in rec.get("evidence", []) or rec.get("promoted"):
                continue
            out[key] = _with_mention(rec, item.url, when, role)
    return out


def promote(candidates: dict[str, dict], threshold: int = 2) -> list[Person]:
    """Candidates seen in at least `threshold` distinct items become Person records."""
    return [
        Person(
            id="cand:" + key.replace(" ", "-"),
            name_uk=rec["name"],
            roles=(rec.get("role") or ALUMNUS,),
            sources=tuple(rec.get("evidence", [])),
        )
        for key, rec in sorted(candidates.items())
        if rec.get("count", 0) >= threshold and not rec.get("promoted")
    ]


def mark_promoted(candidates: dict[str, dict], people: list[Person]) -> dict[str, dict]:
    """New dict where candidates turned into `people` are flagged and never re-announced."""
    ids = {p.id for p in people}
    return {k: ({**v, "promoted": True} if "cand:" + k.replace(" ", "-") in ids else {**v})
            for k, v in candidates.items()}
