"""Render the daily digest (HTML page, archive, RSS) and write the static site."""
from __future__ import annotations

from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from mohyla import digest_assets as A
from mohyla.people.archive import cohort_label
from mohyla.models import Item, Person, SourceStatus

KYIV = ZoneInfo("Europe/Kyiv")
LEAD_COUNT = 5
SNIPPET_CHARS = 240
WIKIDATA_URL = "https://www.wikidata.org/wiki/"


def esc(text: Any) -> str:
    return escape(str(text), quote=True)


def safe_url(url: str) -> str | None:
    """Return the URL only if it is http(s) with a host; otherwise None."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme.lower() in ("http", "https") and parts.netloc:
        return url.strip()
    return None


def _link(url: str, text: str, cls: str = "") -> str:
    """<a> for safe URLs, plain escaped text otherwise."""
    href = safe_url(url)
    attr = f' class="{cls}"' if cls else ""
    if not href:
        return f"<span{attr}>{esc(text)}</span>"
    return f'<a{attr} href="{esc(href)}" target="_blank" rel="noopener">{esc(text)}</a>'


def fmt_time(dt: datetime) -> str:
    """'HH:MM, D <month genitive>' in Kyiv time."""
    local = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(KYIV)
    return f"{local:%H:%M}, {local.day} {A.MONTHS_GEN[local.month - 1]}"


def fmt_day(day: date) -> str:
    return f"{A.WEEKDAYS[day.weekday()]}, {day.day} {A.MONTHS_GEN[day.month - 1]} {day.year}"


def _snippet(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"


def _cat_label(key: str) -> str:
    return A.CATEGORY_LABELS.get(key, key or A.CATEGORY_LABELS["community"])


# --- item fragments ---------------------------------------------------------

def _person_chip(person: Person) -> str:
    roles = ", ".join(A.ROLE_LABELS.get(r, r) for r in person.roles)
    if person.id.startswith("alumni:"):  # graduate from the archived cohort lists
        roles = " ".join(filter(None, (roles, cohort_label(person))))
    inner = esc(person.name_uk) + (f" <small>· {esc(roles)}</small>" if roles else "")
    if person.id.startswith("wd:Q") and person.id[4:].isdigit():
        return f'<a class="person" href="{WIKIDATA_URL}{esc(person.id[3:])}" ' \
               f'target="_blank" rel="noopener">{inner}</a>'
    return f'<span class="person">{inner}</span>'


def _people(item: Item, people_by_id: Mapping[str, Person]) -> str:
    chips = [_person_chip(people_by_id[p]) for p in item.person_ids if p in people_by_id]
    return f'<div class="people">{"".join(chips)}</div>' if chips else ""


def _also(item: Item) -> str:
    also = item.extra.get("also") or []
    links = [_link(str(a.get("url", "")), str(a.get("source", "")))
             for a in also if isinstance(a, dict)]
    return f'<div class="also">Також: {", ".join(links)}</div>' if links else ""


def _kicker(item: Item) -> str:
    kind = item.kind if item.kind in A.KIND_LABELS else "media"
    return (f'<div class="kick"><span class="badge {kind}">{esc(A.KIND_LABELS[kind])}</span>'
            f'<span>{esc(item.source)}</span><span class="cat">{esc(_cat_label(item.category))}'
            f'</span><time datetime="{esc(item.published.isoformat())}">'
            f'{esc(fmt_time(item.published))}</time></div>')


def _item(item: Item, people_by_id: Mapping[str, Person], tag: str, cls: str) -> str:
    snip = _snippet(item.text)
    if snip.startswith(item.title[:60]):  # Google News "summary" just repeats the headline
        snip = ""
    body_note = ('<p class="also">Могилянку згадано в тексті статті, не в заголовку</p>'
                 if item.extra.get("body_match") else "")
    return (f'<{tag} class="{cls}" data-cat="{esc(item.category)}">{_kicker(item)}'
            f'<h3>{_link(item.url, item.title)}</h3>'
            + (f'<p class="snip">{esc(snip)}</p>' if snip else "") + body_note
            + _people(item, people_by_id) + _also(item) + f"</{tag}>")


# --- page sections ----------------------------------------------------------

def _filters(items: Sequence[Item]) -> str:
    cats = [c for c in A.CATEGORY_LABELS if any(i.category == c for i in items)]
    btns = ['<button type="button" class="chip-btn" data-filter="" aria-pressed="true">'
            'Усі</button>']
    btns += [f'<button type="button" class="chip-btn" data-filter="{esc(c)}" '
             f'aria-pressed="false">{esc(_cat_label(c))}</button>' for c in cats]
    return (f'<div class="filters" hidden>{"".join(btns)}<input class="search" '
            f'type="search" placeholder="Пошук: імʼя, тема, джерело…" '
            f'aria-label="Пошук"></div>')


def _grouped(items: Sequence[Item], people_by_id: Mapping[str, Person]) -> str:
    order = list(A.CATEGORY_LABELS) + sorted({i.category for i in items} - set(A.CATEGORY_LABELS))
    out = []
    for cat in order:
        group = [i for i in items if i.category == cat]
        if group:
            rows = "".join(_item(i, people_by_id, "li", "row") for i in group)
            out.append(f'<section data-group="{esc(cat)}"><h2 class="sec">'
                       f'{esc(_cat_label(cat))}</h2><ul class="list">{rows}</ul></section>')
    return "".join(out)


def _new_people(new_people: Sequence[Person]) -> str:
    if not new_people:
        return ""
    rows = []
    for p in new_people:
        evidence = next((u for u in p.sources if safe_url(u)), "")
        desc = f" — {esc(p.description)}" if p.description else ""
        link = f" · {_link(evidence, 'джерело')}" if evidence else ""
        rows.append(f"<li><strong>{esc(p.name_uk)}</strong>{desc}{link}</li>")
    return (f'<section><h2 class="sec">Нові могилянці в графі</h2>'
            f'<ul class="list newp">{"".join(rows)}</ul></section>')


def _status_row(s: SourceStatus) -> str:
    if not s.enabled:
        state, label = "disabled", "вимкнено"
    elif s.ok:
        state, label = "ok", "працює"
    else:
        state, label = "failed", "помилка"
    return (f'<tr><td>{esc(s.name)}</td><td class="st-{state}">{label}</td>'
            f'<td>{s.count}</td><td>{esc(s.message)}</td></tr>')


def _footer(statuses: Sequence[SourceStatus], stats: Mapping[str, Any]) -> str:
    rows = "".join(_status_row(s) for s in statuses) or \
        '<tr><td colspan="4">Немає даних про джерела</td></tr>'
    people, edges = stats.get("people", "—"), stats.get("edges", "—")
    if stats.get("archive"):
        people = f"{people} публічних + {stats['archive']} випускників з архіву"
    return (f'<footer><h2 class="sec">Джерела сьогодні</h2><div class="tbl-wrap"><table>'
            f'<thead><tr><th>Джерело</th><th>Стан</th><th>Матеріалів</th><th>Примітка</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p>У базі людей: {esc(people)} · звʼязків у графі: {esc(edges)}. '
            f'Лише публічні матеріали; зберігаємо посилання та короткий фрагмент.</p>'
            f'<p><a href="archive.html">Архів</a> · <a href="feed.xml">RSS</a></p></footer>')


def _page(title: str, body: str, with_js: bool = False) -> str:
    js = f"<script>{A.JS}</script>" if with_js else ""
    return (f'<!doctype html><html lang="uk"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="light dark"><title>{esc(title)}</title>'
            f'<link rel="preconnect" href="https://fonts.googleapis.com">'
            f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="{esc(A.FONTS_HREF)}">'
            f'<link rel="alternate" type="application/rss+xml" href="feed.xml" '
            f'title="{esc(A.SITE_TITLE)}"><style>{A.CSS}</style></head>'
            f'<body><div class="wrap">{body}</div>{js}</body></html>')


def _nav() -> str:
    return (f'<nav class="topnav"><a href="index.html">{esc(A.SITE_TITLE)}</a>'
            f'<span><a href="archive.html">Архів</a> · <a href="feed.xml">RSS</a></span></nav>')


def render_day(day: date, items: Sequence[Item], statuses: Sequence[SourceStatus],
               people_by_id: Mapping[str, Person], new_people: Sequence[Person],
               stats: Mapping[str, Any]) -> str:
    """Full standalone Ukrainian HTML page for one day's digest."""
    n_sources = len({i.source for i in items})
    head = (f'<header class="mast"><p class="brand">{esc(A.SITE_SUBTITLE)}</p>'
            f'<h1>{esc(fmt_day(day))}</h1><p class="meta">{len(items)} матеріалів · '
            f'{n_sources} джерел</p></header>')
    lead, rest = list(items[:LEAD_COUNT]), list(items[LEAD_COUNT:])
    if items:
        cards = "".join(_item(i, people_by_id, "article", "card") for i in lead)
        main = (_filters(items) + f'<section data-group="lead"><h2 class="sec">Головне</h2>'
                f'<div class="lead">{cards}</div></section>' + _grouped(rest, people_by_id))
    else:
        main = '<p class="empty">Сьогодні нових матеріалів про Могилянку не знайдено.</p>'
    body = _nav() + head + f"<main>{main}{_new_people(new_people)}</main>"
    body += _footer(statuses, stats)
    return _page(f"{A.SITE_TITLE} — {day.isoformat()}", body, with_js=bool(items))


def render_index(dates: Sequence[date]) -> str:
    """Archive page listing all digest days, newest first."""
    rows = "".join(f'<li><a href="{d.isoformat()}.html">{esc(fmt_day(d))}</a></li>'
                   for d in sorted(set(dates), reverse=True))
    body = (_nav() + f'<header class="mast"><p class="brand">{esc(A.SITE_TITLE)}</p>'
            f'<h1>Архів випусків</h1></header><ul class="list archive">'
            f'{rows or "<li>Поки що порожньо</li>"}</ul>')
    return _page(f"{A.SITE_TITLE} — архів", body)


def render_feed(day: date, items: Sequence[Item], site_url: str = "") -> str:
    """RSS 2.0 of the day's items (XML-escaped)."""
    base = site_url.rstrip("/")
    entries = []
    for i in items:
        link = safe_url(i.url) or ""
        entries.append(
            f"<item><title>{esc(i.title)}</title><link>{esc(link)}</link>"
            f"<guid isPermaLink=\"true\">{esc(link)}</guid>"
            f"<description>{esc(_snippet(i.text))}</description>"
            f"<category>{esc(_cat_label(i.category))}</category>"
            f"<source url=\"{esc(link)}\">{esc(i.source)}</source>"
            f"<pubDate>{format_datetime(i.published.astimezone(timezone.utc))}</pubDate></item>")
    channel_link = f"{base}/{day.isoformat()}.html" if base else f"{day.isoformat()}.html"
    return ('<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0"><channel>'
            f"<title>{esc(A.SITE_TITLE)}</title><link>{esc(channel_link)}</link>"
            f"<description>{esc(A.SITE_SUBTITLE)} — {esc(fmt_day(day))}</description>"
            f"<language>uk</language>{''.join(entries)}</channel></rss>\n")


def write_site(site_dir: Path, day: date, html_day: str, index_html: str,
               items: Sequence[Item] = (), site_url: str = "") -> list[Path]:
    """Write <day>.html, index.html (= latest day), archive.html, feed.xml, .nojekyll.

    `index_html` is the archive page from render_index(); `day` is assumed latest.
    """
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    files = {
        f"{day.isoformat()}.html": html_day,
        "index.html": html_day,
        "archive.html": index_html,
        "feed.xml": render_feed(day, items, site_url),
        ".nojekyll": "",
    }
    written = []
    for name, content in files.items():
        path = site_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
