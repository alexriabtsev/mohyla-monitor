"""Persistence of people.json, graph.json and candidates.json under config.DATA_DIR.

Missing file -> empty value. Corrupt file -> StoreError (never silently reset).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from mohyla.config import DATA_DIR
from mohyla.models import Edge, Person

log = logging.getLogger(__name__)

PEOPLE_FILE = "people.json"
GRAPH_FILE = "graph.json"
CANDIDATES_FILE = "candidates.json"


class StoreError(RuntimeError):
    pass


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)  # atomic: readers never see a half-written file


def _to_tuple(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_to_tuple(v) for v in value)
    return value


def _from_dict(cls: type, raw: Any, path: Path) -> Any:
    if not isinstance(raw, dict):
        raise StoreError(f"{path}: expected an object, got {type(raw).__name__}")
    names = {f.name for f in fields(cls)}
    try:
        return cls(**{k: _to_tuple(v) for k, v in raw.items() if k in names})
    except TypeError as exc:
        raise StoreError(f"{path}: bad {cls.__name__} record {raw!r:.200}: {exc}") from exc


def _dir(data_dir: Path | None) -> Path:
    return Path(data_dir) if data_dir is not None else DATA_DIR


def load_people(data_dir: Path | None = None) -> list[Person]:
    path = _dir(data_dir) / PEOPLE_FILE
    raw = _read(path, [])
    if not isinstance(raw, list):
        raise StoreError(f"{path}: expected a list of people")
    return [_from_dict(Person, r, path) for r in raw]


def save_people(people: list[Person], data_dir: Path | None = None) -> Path:
    path = _dir(data_dir) / PEOPLE_FILE
    _write(path, [asdict(p) for p in people])
    log.info("saved %d people to %s", len(people), path)
    return path


def _node(p: Person) -> dict:
    return {"id": p.id, "name_uk": p.name_uk, "roles": list(p.roles),
            "prominence": p.prominence}


def save_graph(people: list[Person], edges: list[Edge], data_dir: Path | None = None) -> Path:
    path = _dir(data_dir) / GRAPH_FILE
    _write(path, {"nodes": [_node(p) for p in people], "edges": [asdict(e) for e in edges]})
    log.info("saved graph (%d nodes, %d edges) to %s", len(people), len(edges), path)
    return path


def _load_graph_raw(data_dir: Path | None) -> tuple[dict, Path]:
    path = _dir(data_dir) / GRAPH_FILE
    raw = _read(path, {"nodes": [], "edges": []})
    if not isinstance(raw, dict) or not isinstance(raw.get("edges", []), list):
        raise StoreError(f"{path}: expected {{nodes: [...], edges: [...]}}")
    return raw, path


def load_edges(data_dir: Path | None = None) -> list[Edge]:
    raw, path = _load_graph_raw(data_dir)
    return [_from_dict(Edge, e, path) for e in raw.get("edges", [])]


def load_graph_nodes(data_dir: Path | None = None) -> list[dict]:
    raw, _ = _load_graph_raw(data_dir)
    return list(raw.get("nodes", []))


def load_candidates(data_dir: Path | None = None) -> dict[str, dict]:
    path = _dir(data_dir) / CANDIDATES_FILE
    raw = _read(path, {})
    if not isinstance(raw, dict):
        raise StoreError(f"{path}: expected an object keyed by normalized name")
    return raw


def save_candidates(candidates: dict[str, dict], data_dir: Path | None = None) -> Path:
    path = _dir(data_dir) / CANDIDATES_FILE
    _write(path, candidates)
    log.info("saved %d candidates to %s", len(candidates), path)
    return path
