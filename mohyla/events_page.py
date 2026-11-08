"""The «Події» tab: upcoming events from kmaevents.com, grouped by Kyiv day."""
from __future__ import annotations

from datetime import date, datetime
from itertools import groupby
from typing import Sequence

from mohyla import digest_assets as A
from mohyla.collectors.kmaevents import Event, Events
from mohyla.digest import KYIV, _link, _nav, _page, esc, fmt_day, fmt_time, safe_url

EVENTS_FILE = "events.html"
SOURCE_URL = "https://kmaevents.com/events"
DESC_CHARS = 200
DEADLINE = "registration_deadline"


def _local(dt: datetime) -> datetime:
    return dt.astimezone(KYIV)


def _kind(key: str) -> str:
    return A.EVENT_KIND_LABELS.get(key, A.EVENT_KIND_LABELS["other"])


def _when(e: Event) -> str:
    start = f"{_local(e.starts):%H:%M}"
    if e.kind == DEADLINE:
        return f"до {start}"
    if e.ends and _local(e.ends).date() == _local(e.starts).date():
        return f"{start}–{_local(e.ends):%H:%M}"
    return start


def _desc(text: str) -> str:
    if len(text) <= DESC_CHARS:
        return text
    return text[:DESC_CHARS].rsplit(" ", 1)[0] + "…"


def _row(e: Event) -> str:
    meta = [f'<span class="badge ev">{esc(_kind(e.kind))}</span>',
            f'<time datetime="{esc(e.starts.isoformat())}">{esc(_when(e))}</time>']
    if e.club:
        meta.append(f"<span>{esc(e.club)}</span>")
    place = f'<p class="place">{esc(e.location)}</p>' if e.location else ""
    desc = _desc(e.description)
    desc_html = f'<p class="snip">{esc(desc)}</p>' if desc and desc != e.title else ""
    cal = (f'<p class="also">{_link(e.calendar_url, "Додати в календар")}</p>'
           if safe_url(e.calendar_url) else "")
    return (f'<li class="row" data-cat="{esc(e.kind)}"><div class="kick">{"".join(meta)}'
            f'</div><h3>{_link(e.url, e.title)}</h3>{place}{desc_html}{cal}</li>')


def _filters(events: Sequence[Event]) -> str:
    kinds = [k for k in A.EVENT_KIND_LABELS if any(e.kind == k for e in events)]
    kinds += sorted({e.kind for e in events} - set(kinds))
    btns = ['<button type="button" class="chip-btn" data-filter="" aria-pressed="true">'
            'Усі</button>']
    btns += [f'<button type="button" class="chip-btn" data-filter="{esc(k)}" '
             f'aria-pressed="false">{esc(_kind(k))}</button>' for k in kinds]
    return (f'<div class="filters" hidden>{"".join(btns)}<input class="search" '
            f'type="search" placeholder="Пошук: назва, клуб, місце…" '
            f'aria-label="Пошук"></div>')


def _days(events: Sequence[Event]) -> str:
    out = []
    for day, group in groupby(events, key=lambda e: _local(e.starts).date()):
        rows = "".join(_row(e) for e in group)
        out.append(f'<section data-group="{day.isoformat()}"><h2 class="sec">'
                   f'{esc(fmt_day(day))}</h2><ul class="list">{rows}</ul></section>')
    return "".join(out)


def _note(events: Events, today: date) -> str:
    src = _link(SOURCE_URL, "kmaevents.com")
    if events.status.ok:
        return f"Джерело: {src}, студентський календар подій НаУКМА."
    if events.fetched:
        return (f"Не вдалося оновити {src}; показано список від "
                f"{esc(fmt_time(events.fetched))}.")
    return f"Не вдалося отримати події з {src}."


def render_events(today: date, events: Events, days_ahead: int) -> str:
    """Standalone page with the upcoming events, newest data first."""
    items = list(events.items)
    head = (f'<header class="mast"><p class="brand">{esc(A.SITE_TITLE)}</p>'
            f'<h1>Події</h1><p class="meta">{len(items)} подій у найближчі {days_ahead} днів'
            f' · від {esc(fmt_day(today))}</p></header>')
    main = (_filters(items) + _days(items) if items else
            '<p class="empty">Найближчих подій поки немає.</p>')
    body = (_nav("events") + head + f"<main>{main}</main>"
            f'<footer><p>{_note(events, today)}</p></footer>')
    return _page(f"{A.SITE_TITLE} — події", body, with_js=bool(items))
