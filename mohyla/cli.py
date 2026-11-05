"""Entry points: `python -m mohyla.cli people` and `python -m mohyla.cli daily`."""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from zoneinfo import ZoneInfo

from mohyla import digest, rank, state
from mohyla.collectors import run_all
from mohyla.collectors.telegram import discover_channels
from mohyla.config import DATA_DIR, SITE_DIR, load_config
from mohyla.http import make_client
from mohyla.match import filter_and_link
from mohyla.people import archive, graph, store, wikidata, wikipedia
from mohyla.people.names import normalize

log = logging.getLogger("mohyla")
KYIV = ZoneInfo("Europe/Kyiv")


# Refuse to overwrite the base when a source outage shrinks it below this share
MIN_PEOPLE_RATIO = 0.7


def cmd_people(cfg: dict) -> int:
    """Rebuild the people base from Wikidata + Wikipedia, keep promoted candidates."""
    with make_client(cfg["user_agent"]) as client:
        wd_people = wikidata.fetch_people(client, cfg)
        wd_ids = {p.id for p in wd_people}
        wp_raw = wikipedia.fetch_category_people(client, cfg)
        wp_extra = wikidata.enrich_people(
            client, cfg, [p for p in wp_raw if p.id not in wd_ids])
    previous = store.load_people()
    promoted = [p for p in previous if p.id.startswith("cand:")]
    people = graph.merge_people(wd_people, wp_extra, promoted)
    if len(people) < MIN_PEOPLE_RATIO * len(previous) or not (wd_people or wp_extra):
        log.error("people base would shrink %d -> %d (source outage?); keeping the old one",
                  len(previous), len(people))
        return 1
    comention = [e for e in store.load_edges() if e.kind == "comention"]
    employer = graph.employer_edges(people, exclude=set(cfg["wikidata"]["orgs"]))
    edges = graph.merge_edges(comention, employer)
    store.save_people(people)
    store.save_graph(people, edges)
    log.info("people: wikidata=%d wikipedia_extra=%d merged=%d edges=%d",
             len(wd_people), len(wp_extra), len(people), len(edges))
    return 0


PRIVATE_DIR_NAME = "private"


def cmd_archive(cfg: dict) -> int:
    """Rebuild the private graduate base from archived cohort pages."""
    pages = cfg.get("alumni_archive_pages") or []
    with make_client(cfg["user_agent"]) as client:
        grads = archive.fetch_archive(client, pages)
    people = archive.to_people(grads, "web.archive.org: alumni.ukma.edu.ua / ukma.kiev.ua")
    private = store.load_people(data_dir=DATA_DIR / PRIVATE_DIR_NAME)
    if len(people) < MIN_PEOPLE_RATIO * len(private) or not people:
        log.error("archive base would shrink %d -> %d; keeping the old one", len(private), len(people))
        return 1
    store.save_people(people, data_dir=DATA_DIR / PRIVATE_DIR_NAME)
    log.info("archive: %d records, %d people", len(grads), len(people))
    return 0


def _collect(cfg: dict, people: list, since: datetime):
    discovered = sorted(state.load_extra("telegram_discovered"))
    run_cfg = {**cfg, "telegram_discovered": discovered}
    with make_client(cfg["user_agent"]) as client:
        items, statuses = run_all(client, run_cfg, since, people)
    return items, statuses, discovered


def _load_archive(public: list) -> list:
    """Private graduate base (absent on forks / without the deploy key: empty)."""
    try:
        archived = store.load_people(data_dir=DATA_DIR / PRIVATE_DIR_NAME)
    except store.StoreError as exc:
        log.error("private graduate base unreadable: %s", exc)
        return []
    if not archived:
        log.warning("private graduate base not found; matching public people only")
    return archive.without_public(archived, public)


def _alumni_edges(edges: list, stories: list, people_by_id: dict) -> tuple[list, set]:
    """Recompute classmate edges among every archived graduate ever seen in the news."""
    mentioned = state.load_extra("alumni_mentioned") | {
        pid for it in stories for pid in it.person_ids if pid.startswith("alumni:")}
    kept = [e for e in edges if e.kind != "cohort"]
    return kept + archive.cohort_edges(mentioned, people_by_id), mentioned


def _grow_graph(people: list, stories: list, archived: list) -> tuple[list, list, dict, list]:
    """Snowball candidates + co-mention edges, in memory. `stories` must be deduped."""
    candidates = graph.update_candidates(store.load_candidates(), stories, people + archived)
    known_ids = {p.id for p in people}
    known_names = {normalize(p.name_uk) for p in people}
    new_people = [p for p in graph.promote(candidates)
                  if p.id not in known_ids and normalize(p.name_uk) not in known_names]
    candidates = graph.mark_promoted(candidates, new_people)
    edges = graph.merge_edges(store.load_edges(), graph.comention_edges(stories))
    return graph.merge_people(people, new_people), new_people, candidates, edges


def _link(cfg: dict, raw: list, people: list) -> list:
    return filter_and_link(
        raw, people,
        is_relevant=partial(rank.is_relevant, patterns=cfg["relevance_patterns"]),
        is_achievement=partial(rank.is_relevant,
                               patterns=cfg.get("own_achievement_patterns", [])),
        trusted_queries=cfg.get("google_news_queries", []),
    )


def _processed_urls(items: list) -> list[str]:
    """Item URLs plus duplicates folded into extra["also"], all to be marked seen."""
    also = [a.get("url", "") for it in items for a in it.extra.get("also", [])
            if isinstance(a, dict)]
    return [it.url for it in items] + [u for u in also if u]


def cmd_daily(cfg: dict) -> int:
    now = datetime.now(timezone.utc)
    day = now.astimezone(KYIV).date()
    people = store.load_people()
    if not people:
        log.warning("people base is empty; run `people` first for person matching")
    raw, statuses, discovered = _collect(
        cfg, people, now - timedelta(hours=cfg["lookback_hours"]))
    seen = state.load_seen()
    archived = _load_archive(people)
    fresh = state.filter_unseen(_link(cfg, raw, people + archived), seen)
    stories = rank.rank(fresh, {p.id: p for p in people + archived}, cfg, now)  # deduped
    people, new_people, candidates, edges = _grow_graph(people, stories, archived)
    people_by_id = {p.id: p for p in people + archived}
    edges, mentioned = _alumni_edges(edges, stories, people_by_id)
    # a re-run on the same Kyiv day extends that day's issue instead of replacing it
    earlier = (state.load_digest(day) or {}).get("items", [])
    ranked = rank.rank([*earlier, *stories], people_by_id, cfg, now)
    chosen = rank.select_digest(ranked, cfg["digest_size"])
    stats = {"people": len(people), "archive": len(archived), "edges": len(edges)}
    _publish(cfg, day, chosen, statuses, people_by_id, new_people, stats)
    # publish succeeded: now persist state, seen first so nothing is counted twice
    state.save_seen(state.mark_seen_urls(seen, _processed_urls(stories), now))
    store.save_candidates(candidates)
    store.save_people(people)
    store.save_graph(people, edges)  # public people only; graduates appear as opaque ids
    state.save_extra("alumni_mentioned", mentioned)
    state.save_extra("telegram_discovered", set(discovered) | discover_channels(fresh))
    log.info("daily: raw=%d fresh=%d stories=%d chosen=%d new_people=%d",
             len(raw), len(fresh), len(stories), len(chosen), len(new_people))
    return 0 if any(s.ok and s.count for s in statuses) else 2


def _publish(cfg, day, chosen, statuses, people_by_id, new_people, stats) -> None:
    state.save_digest(day, chosen, statuses,
                      {"new_people": [p.id for p in new_people], **stats})
    html_day = digest.render_day(day, chosen, statuses, people_by_id, new_people, stats)
    dates = sorted(set(state.list_digest_dates()) | {day})
    digest.write_site(SITE_DIR, day, html_day, digest.render_index(dates),
                      items=chosen, site_url=cfg.get("site_url", ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mohyla")
    parser.add_argument("command", choices=("people", "daily", "archive"))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    commands = {"people": cmd_people, "daily": cmd_daily, "archive": cmd_archive}
    return commands[args.command](cfg)


if __name__ == "__main__":
    sys.exit(main())
