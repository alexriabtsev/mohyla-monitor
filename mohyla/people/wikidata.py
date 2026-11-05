"""NaUKMA people from Wikidata (P69 educated at / P108 employer).

Two-phase to stay well under the 60 s SPARQL limit: a bare core query lists
(person, relation) pairs, then details come in VALUES batches as long-format
(person, key, value) rows. One wide query with label OPTIONALs times out.
"""
from __future__ import annotations

import logging
import math
import re
import time
from collections import defaultdict
from dataclasses import replace

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import ALUMNUS, STAFF, Person, qualified_role
from mohyla.people.names import canonical_name

log = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"
ENTITY = "http://www.wikidata.org/entity/"
BATCH = 200
RATE_LIMIT_WAIT = 65.0          # WDQS may throttle to 1 req/min during incidents
REQUEST_TIMEOUT = 70.0
PROMINENCE_SATURATION = 60
SOCIAL_PROPS = {
    "telegram": "P3789", "facebook": "P2013", "x": "P2002", "bluesky": "P12361",
    "linkedin": "P6634", "mastodon": "P4033", "instagram": "P2003",
}
_YEAR_RE = re.compile(r"^(-?\d{1,4})-")


def prominence(sitelinks: int) -> float:
    return min(1.0, math.log1p(max(sitelinks, 0)) / math.log1p(PROMINENCE_SATURATION))


def core_query(orgs: list[str], units: dict[str, str] | None = None) -> str:
    """Alumni (P69) and staff (P108) of each org; roles carry the org's unit label
    (e.g. 'alumnus@kmbs') when it is a school inside NaUKMA rather than the university."""
    branches = []
    for org in orgs:
        unit = (units or {}).get(org, "")
        branches.append(f'{{ ?p wdt:P69 wd:{org} . BIND("{qualified_role(ALUMNUS, unit)}" AS ?rel) }}')
        branches.append(f'{{ ?p wdt:P108 wd:{org} . BIND("{qualified_role(STAFF, unit)}" AS ?rel) }}')
    return "SELECT DISTINCT ?p ?rel WHERE {\n  " + "\n  UNION ".join(branches) + "\n}"


def detail_query(qids: list[str]) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    socials = " ".join(f'("{k}" wdt:{p})' for k, p in SOCIAL_PROPS.items())
    return f"""SELECT ?p ?k ?v WHERE {{
  VALUES ?p {{ {values} }}
  {{ ?p wdt:P31 ?v . FILTER(?v = wd:Q5) BIND("P31" AS ?k) }}
  UNION {{ ?p wdt:P570 ?v . BIND("P570" AS ?k) }}
  UNION {{ ?p wdt:P569 ?v . BIND("P569" AS ?k) }}
  UNION {{ ?p wikibase:sitelinks ?v . BIND("sitelinks" AS ?k) }}
  UNION {{ ?p rdfs:label ?v . FILTER(LANG(?v) = "uk" || LANG(?v) = "en") BIND("label" AS ?k) }}
  UNION {{ ?p schema:description ?v . FILTER(LANG(?v) = "uk") BIND("desc" AS ?k) }}
  UNION {{ ?p skos:altLabel ?v . FILTER(LANG(?v) = "uk") BIND("alias" AS ?k) }}
  UNION {{ ?p wdt:P108 ?v . BIND("P108" AS ?k) }}
  UNION {{ VALUES (?k ?prop) {{ {socials} }} ?p ?prop ?v . }}
}}"""


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _bindings(data: dict) -> list[dict]:
    return data.get("results", {}).get("bindings", [])


def parse_core(data: dict) -> dict[str, tuple[str, ...]]:
    """QID -> roles, preserving first-seen order."""
    roles: dict[str, dict[str, None]] = defaultdict(dict)
    for b in _bindings(data):
        roles[_qid(b["p"]["value"])][b["rel"]["value"]] = None
    return {q: tuple(r) for q, r in roles.items()}


def _empty_detail() -> dict:
    return {"human": False, "dead": False, "birth_years": [], "sitelinks": 0, "label_uk": "",
            "label_en": "", "desc": "", "aliases": [], "employers": [], "socials": []}


def _apply_row(d: dict, key: str, val: dict) -> None:
    value = val.get("value", "")
    if key == "P31":
        d["human"] = True
    elif key == "P570":
        d["dead"] = True
    elif key == "P569" and (m := _YEAR_RE.match(value)):
        d["birth_years"].append(int(m.group(1)))
    elif key == "sitelinks":
        d["sitelinks"] = int(value) if value.isdigit() else 0
    elif key == "label":
        d["label_uk" if val.get("xml:lang") == "uk" else "label_en"] = value
    elif key == "desc":
        d["desc"] = value
    elif key == "alias":
        d["aliases"].append(value)
    elif key == "P108" and value.startswith(ENTITY):
        d["employers"].append(_qid(value))
    elif key in SOCIAL_PROPS and value:
        d["socials"].append((key, value.lstrip("@")))


def parse_details(data: dict) -> dict[str, dict]:
    """QID -> detail dict built from long-format (p, k, v) rows."""
    out: dict[str, dict] = defaultdict(_empty_detail)
    for b in _bindings(data):
        _apply_row(out[_qid(b["p"]["value"])], b["k"]["value"], b["v"])
    return dict(out)


def _keep(d: dict, wcfg: dict) -> bool:
    if not d["human"]:
        return False
    if wcfg.get("exclude_dead", True) and d["dead"]:
        return False
    min_year = wcfg.get("min_birth_year")
    return not (min_year and d["birth_years"] and min(d["birth_years"]) < min_year)


def _person(qid: str, roles: tuple[str, ...], d: dict) -> Person | None:
    label = d["label_uk"] or d["label_en"]
    if not label:
        log.debug("wikidata %s has no uk/en label; skipped", qid)
        return None
    name = canonical_name(label, d["label_en"])
    return Person(
        id=f"wd:{qid}", name_uk=name, name_en=d["label_en"],
        aliases=tuple(dict.fromkeys(a for a in (label, *d["aliases"]) if a != name)),
        roles=roles, description=d["desc"],
        employers=tuple(dict.fromkeys(d["employers"])),
        socials=tuple(dict.fromkeys(d["socials"])),
        sources=(f"https://www.wikidata.org/wiki/{qid}",),
        prominence=prominence(d["sitelinks"]),
    )


def build_people(core: dict[str, tuple[str, ...]], details: dict[str, dict],
                 cfg: dict) -> list[Person]:
    wcfg = cfg.get("wikidata", {})
    out = []
    for qid, roles in core.items():
        d = details.get(qid)
        if d is None or not _keep(d, wcfg):
            continue
        if (p := _person(qid, roles, d)) is not None:
            out.append(p)
    return out


def _post(client: httpx.Client, query: str) -> httpx.Response:
    return fetch(client, SPARQL_URL, method="POST", data={"query": query},
                 headers={"Accept": "application/sparql-results+json"},
                 timeout=REQUEST_TIMEOUT, retries=1, backoff=10.0)


def _sparql(client: httpx.Client, query: str) -> dict:
    """POST a query; on HTTP 429 wait out WDQS's per-minute throttle once and retry."""
    try:
        resp = _post(client, query)
    except FetchError as exc:
        if exc.reason != "HTTP 429":
            raise
        log.warning("wikidata rate-limited; waiting %.0f s before one retry", RATE_LIMIT_WAIT)
        time.sleep(RATE_LIMIT_WAIT)
        resp = _post(client, query)
    try:
        return resp.json()
    except ValueError as exc:
        raise FetchError(SPARQL_URL, f"invalid JSON: {exc}") from exc


def fetch_details(client: httpx.Client, qids: list[str]) -> dict[str, dict]:
    """Details for many QIDs in VALUES batches; failed batches are logged and skipped."""
    out: dict[str, dict] = {}
    for i in range(0, len(qids), BATCH):
        batch = qids[i:i + BATCH]
        try:
            out.update(parse_details(_sparql(client, detail_query(batch))))
        except FetchError as exc:
            log.warning("wikidata details batch %d (%d qids) failed: %s", i // BATCH, len(batch), exc)
    return out


def fetch_people(client: httpx.Client, cfg: dict) -> list[Person]:
    """Living NaUKMA alumni/staff from Wikidata. Returns [] if the core query fails."""
    orgs = cfg.get("wikidata", {}).get("orgs", [])
    try:
        core = parse_core(_sparql(client, core_query(orgs, cfg.get("wikidata", {}).get("units"))))
    except FetchError as exc:
        log.error("wikidata core query failed: %s", exc)
        return []
    details = fetch_details(client, sorted(core))
    people = build_people(core, details, cfg)
    log.info("wikidata: %d candidates, %d kept", len(core), len(people))
    return people


def enrich_people(client: httpx.Client, cfg: dict, people: list[Person]) -> list[Person]:
    """Fill in Wikidata details for wd:-id people from other sources (e.g. Wikipedia),
    applying the same living/birth-year filters. Non-wd people pass through unchanged.
    People whose details could not be fetched are kept as they are."""
    qids = sorted({p.id[3:] for p in people if p.id.startswith("wd:")})
    details = fetch_details(client, qids)
    wcfg = cfg.get("wikidata", {})
    out = []
    for p in people:
        d = details.get(p.id[3:]) if p.id.startswith("wd:") else None
        if d is None:
            out.append(p)
        elif _keep(d, wcfg) and (wdp := _person(p.id[3:], p.roles, d)) is not None:
            out.append(_overlay(wdp, p))
    return out


def _overlay(wdp: Person, src: Person) -> Person:
    """Wikidata record with the source's provenance and its name kept as an alias."""
    extra = (src.name_uk,) if src.name_uk != wdp.name_uk else ()
    return replace(wdp, aliases=tuple(dict.fromkeys((*wdp.aliases, *src.aliases, *extra))),
                   sources=tuple(dict.fromkeys((*src.sources, *wdp.sources))))
