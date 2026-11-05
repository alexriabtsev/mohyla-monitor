"""Relevance, categorization, dedupe, scoring and digest selection."""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from functools import lru_cache
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mohyla.models import Item, Person

KIND_PRIORITY = {"official": 0, "media": 1, "social": 2}
FALLBACK_CATEGORY = "community"
TITLE_JACCARD = 0.7
TITLE_PREFIX = 60
MIN_TITLE_TOKENS = 3
PERSON_CAP = 3
SOURCE_SHARE = 0.4
MIN_ACHIEVEMENTS = 5

_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


@lru_cache(maxsize=64)
def _compile(patterns: tuple[str, ...]) -> re.Pattern[str] | None:
    if not patterns:
        return None
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE | re.UNICODE)


def _haystack(item: Item) -> str:
    return f"{item.title}\n{item.text}"


def is_relevant(item: Item, patterns: Sequence[str]) -> bool:
    rx = _compile(tuple(patterns))
    return bool(rx and rx.search(_haystack(item)))


def categorize(item: Item, categories_cfg: Mapping[str, Any]) -> str:
    """First category whose patterns hit; otherwise the last key (or 'community')."""
    for key, spec in categories_cfg.items():
        rx = _compile(tuple((spec or {}).get("patterns") or ()))
        if rx and rx.search(_haystack(item)):
            return key
    keys = list(categories_cfg)
    return keys[-1] if keys else FALLBACK_CATEGORY


def canonical_url(url: str) -> str:
    """Lowercase host, drop utm_* params, fragment and trailing slash."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    path = parts.path.rstrip("/")
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def _norm_title(title: str) -> str:
    return " ".join(_NON_WORD.sub(" ", title.lower()).split())


def _titles_similar(a: str, b: str) -> bool:
    ta, tb = set(a.split()), set(b.split())
    if min(len(ta), len(tb)) < MIN_TITLE_TOKENS:
        return a == b and bool(a)
    if a[:TITLE_PREFIX] == b[:TITLE_PREFIX]:
        return True
    return len(ta & tb) / len(ta | tb) >= TITLE_JACCARD


def _preference(item: Item) -> tuple[float, int]:
    return (-item.score, KIND_PRIORITY.get(item.kind, len(KIND_PRIORITY)))


def dedupe(items: Sequence[Item]) -> list[Item]:
    """Collapse URL/title duplicates; the best item keeps others in extra['also']."""
    clusters: list[tuple[Item, str, str, list[Item]]] = []
    for item in sorted(items, key=_preference):
        url, title = canonical_url(item.url), _norm_title(item.title)
        for rep, rurl, rtitle, dups in clusters:
            if url == rurl or _titles_similar(title, rtitle):
                dups.append(item)
                break
        else:
            clusters.append((item, url, title, []))
    return [_merge(rep, dups) for rep, _, _, dups in clusters]


def _merge(rep: Item, dups: list[Item]) -> Item:
    if not dups:
        return rep
    also = list(rep.extra.get("also", []))
    for d in dups:
        also.append({"source": d.source, "url": d.url})
        also.extend(d.extra.get("also", []))
    return replace(rep, extra={**rep.extra, "also": also})


def score(item: Item, people_by_id: Mapping[str, Person], weights: Mapping[str, Any],
          now: datetime) -> float:
    base = float(weights.get("kind", {}).get(item.kind, 0.0))
    base += float(weights.get("person_mention", 0.0)) * min(len(item.person_ids), PERSON_CAP)
    prominences = [people_by_id[p].prominence for p in item.person_ids if p in people_by_id]
    base += float(weights.get("prominence", 0.0)) * max(prominences, default=0.0)
    base += float(weights.get("category", {}).get(item.category, 0.0))
    base += float(weights.get("keep_reason", {}).get(item.extra.get("keep_reason"), 0.0))
    age_h = max(0.0, (now - item.published).total_seconds() / 3600)
    half_life = float(weights.get("recency_half_life_hours", 24)) or 24.0
    return base * 0.5 ** (age_h / half_life)


def rank(items: Sequence[Item], people_by_id: Mapping[str, Person],
         cfg: Mapping[str, Any], now: datetime) -> list[Item]:
    """Categorize + score (new Items), dedupe, sort by score desc."""
    scored = []
    for item in items:
        cat = categorize(item, cfg.get("categories", {}))
        with_cat = replace(item, category=cat)
        scored.append(replace(with_cat, score=score(with_cat, people_by_id,
                                                    cfg.get("weights", {}), now)))
    return sorted(dedupe(scored), key=_preference)


def _family(item: Item) -> str:
    """Source family: 'web:x.com' -> 'web', 'telegram:naukma' -> 'telegram'."""
    return item.source.split(":", 1)[0]


def _greedy(pool: list[int], items: Sequence[Item], limit: int, cap: int | None,
            chosen: list[int], family_caps: dict[str, int]) -> list[int]:
    """Add items in pool order; `cap` limits one source (None = no limit), family caps
    are always enforced."""
    out = list(chosen)
    for idx in pool:
        if len(out) >= limit:
            break
        if idx in out:
            continue
        item = items[idx]
        same = sum(1 for j in out if items[j].source == item.source)
        fam_cap = family_caps.get(_family(item))
        fam = sum(1 for j in out if _family(items[j]) == _family(item))
        if (cap is None or same < cap) and (fam_cap is None or fam < fam_cap):
            out.append(idx)
    return out


def select_digest(items: Sequence[Item], size: int,
                  family_shares: dict[str, float] | None = None) -> list[Item]:
    """Top `size` with <=40% per source, per-family shares (e.g. {'web': 0.25}) as a hard
    limit, and >=min(5, available) achievements."""
    if size <= 0:
        return []
    order = sorted(range(len(items)), key=lambda i: _preference(items[i]))
    cap = max(1, int(size * SOURCE_SHARE))
    fams = {f: max(1, int(size * share)) for f, share in (family_shares or {}).items()}
    ach = [i for i in order if items[i].category == "achievement"]
    need = min(MIN_ACHIEVEMENTS, len(ach), size)
    chosen = _greedy(ach, items, need, cap, [], fams)
    chosen = _greedy(ach, items, need, None, chosen, fams)       # relax source cap if needed
    chosen = _greedy(order, items, size, cap, chosen, fams)
    chosen = _greedy(order, items, size, None, chosen, fams)     # fill if sources too few
    return [items[i] for i in sorted(chosen, key=lambda i: _preference(items[i]))]
