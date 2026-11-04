"""Persistent state: cross-day seen URLs and daily digest JSON archives."""
from __future__ import annotations

import json
from dataclasses import asdict, fields
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

from mohyla.config import DATA_DIR
from mohyla.models import Item, SourceStatus
from mohyla.rank import canonical_url

SEEN_TTL_DAYS = 30


class StateError(ValueError):
    """Raised when a state file exists but cannot be parsed."""


def _seen_path() -> Path:
    return DATA_DIR / "seen.json"


def _digest_dir() -> Path:
    return DATA_DIR / "digests"


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"corrupt state file {path}: {exc}") from exc


def _write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic on POSIX
    return path


# --- seen -------------------------------------------------------------------

def load_seen() -> dict[str, str]:
    data = _read_json(_seen_path())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise StateError(f"{_seen_path()} must contain a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def filter_unseen(items: Iterable[Item], seen: dict[str, str]) -> list[Item]:
    return [i for i in items if canonical_url(i.url) not in seen]


def _prune(seen: dict[str, str], now: datetime) -> dict[str, str]:
    cutoff = now - timedelta(days=SEEN_TTL_DAYS)
    kept = {}
    for url, ts in seen.items():
        try:
            first = datetime.fromisoformat(ts)
        except ValueError:
            continue  # unparsable timestamp: drop
        if first.tzinfo is None:
            first = first.replace(tzinfo=now.tzinfo)
        if first >= cutoff:
            kept[url] = ts
    return kept


def mark_seen(seen: dict[str, str], items: Iterable[Item], now: datetime) -> dict[str, str]:
    """New dict with items added (first-seen kept) and entries >30 days pruned."""
    out = dict(seen)
    for item in items:
        out.setdefault(canonical_url(item.url), now.isoformat())
    return _prune(out, now)


def mark_seen_urls(seen: dict[str, str], urls: Iterable[str], now: datetime) -> dict[str, str]:
    """Like mark_seen, for raw URLs (e.g. duplicates folded into extra["also"])."""
    out = dict(seen)
    for url in urls:
        out.setdefault(canonical_url(url), now.isoformat())
    return _prune(out, now)


def save_seen(seen: dict[str, str]) -> Path:
    return _write_json(_seen_path(), dict(sorted(seen.items())))


# --- digests ----------------------------------------------------------------

def _item_to_json(item: Item) -> dict[str, Any]:
    d = asdict(item)
    d["published"] = item.published.isoformat()
    return d


def _item_from_json(d: dict[str, Any]) -> Item:
    known = {f.name for f in fields(Item)}
    kw = {k: v for k, v in d.items() if k in known}
    kw["published"] = datetime.fromisoformat(kw["published"])
    kw["person_ids"] = tuple(kw.get("person_ids", ()))
    kw["extra"] = dict(kw.get("extra") or {})
    return Item(**kw)


def _status_from_json(d: dict[str, Any]) -> SourceStatus:
    known = {f.name for f in fields(SourceStatus)}
    return SourceStatus(**{k: v for k, v in d.items() if k in known})


def save_digest(day: date, items: Sequence[Item], statuses: Sequence[SourceStatus],
                extra: dict[str, Any]) -> Path:
    payload = {
        "date": day.isoformat(),
        "items": [_item_to_json(i) for i in items],
        "statuses": [asdict(s) for s in statuses],
        "extra": extra,
    }
    return _write_json(_digest_dir() / f"{day.isoformat()}.json", payload)


def load_digest(day: date) -> dict[str, Any] | None:
    """{'date', 'items': [Item], 'statuses': [SourceStatus], 'extra': dict} or None."""
    path = _digest_dir() / f"{day.isoformat()}.json"
    data = _read_json(path)
    if data is None:
        return None
    try:
        return {
            "date": date.fromisoformat(data["date"]),
            "items": [_item_from_json(i) for i in data.get("items", [])],
            "statuses": [_status_from_json(s) for s in data.get("statuses", [])],
            "extra": dict(data.get("extra") or {}),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise StateError(f"malformed digest {path}: {exc}") from exc


def list_digest_dates() -> list[date]:
    folder = _digest_dir()
    if not folder.is_dir():
        return []
    out = []
    for p in folder.glob("*.json"):
        try:
            out.append(date.fromisoformat(p.stem))
        except ValueError:
            continue
    return sorted(out)


# --- small named sets that persist between runs (e.g. discovered Telegram channels)

def _extra_path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def load_extra(name: str) -> set[str]:
    data = _read_json(_extra_path(name))
    if data is None:
        return set()
    if not isinstance(data, list):
        raise StateError(f"{_extra_path(name)} must contain a JSON list")
    return {str(x) for x in data}


def save_extra(name: str, values: Iterable[str]) -> Path:
    return _write_json(_extra_path(name), sorted(set(values)))
