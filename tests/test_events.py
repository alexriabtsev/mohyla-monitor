"""kmaevents.com collector and the «Події» tab."""
from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest

from mohyla import digest, events_page, state
from mohyla.collectors import kmaevents

NOW = datetime(2026, 11, 8, 5, 0, tzinfo=timezone.utc)
START = datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc)   # 00:00 Kyiv, 8 Nov
CFG = {"kmaevents": {"api_url": "https://api.test/api/events",
                     "site_url": "https://kmaevents.com/events", "days_ahead": 30}}


def raw(id_, starts, title="Подія", kind="talk", **extra):
    return {"id": id_, "title": title, "eventType": kind, "startsAt": starts,
            "endsAt": None, "location": "КМЦ", "description": "Опис",
            "club": {"name": "KMA Talks"}, "sourceUrl": f"https://instagram.com/p/{id_}/",
            "gcalUrl": "https://calendar.google.com/calendar/render?x=1", **extra}


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DATA_DIR", tmp_path / "data")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("mohyla.http.time.sleep", lambda *_: None)


def client(pages: dict[str | None, dict], calls: list) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(dict(req.url.params))
        return httpx.Response(200, json=pages[req.url.params.get("cursor")])
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_event_and_reject_incomplete():
    e = kmaevents.parse_event(raw("a", "2026-11-10T17:00:00.000Z", "  Економіка   2027 "),
                              "https://kmaevents.com/events")
    assert e.title == "Економіка 2027" and e.club == "KMA Talks"
    assert e.starts == datetime(2026, 11, 10, 17, tzinfo=timezone.utc)
    assert kmaevents.parse_event({"id": "x", "title": "t"}, "") is None
    no_src = kmaevents.parse_event({**raw("b", "2026-11-10T17:00:00Z"), "sourceUrl": None},
                                   "https://kmaevents.com/events")
    assert no_src.url == "https://kmaevents.com/events"


def test_collect_follows_cursor_and_keeps_window():
    pages = {None: {"items": [raw("a", "2026-11-09T10:00:00Z"),
                              raw("old", "2026-11-07T10:00:00Z")], "nextCursor": "c2"},
             "c2": {"items": [raw("a", "2026-11-09T10:00:00Z"),        # duplicate id
                              raw("b", "2026-11-08T08:00:00Z"),
                              raw("far", "2027-01-20T10:00:00Z")], "nextCursor": None}}
    calls: list = []
    ev = kmaevents.collect(client(pages, calls), CFG, START, NOW)
    assert [e.id for e in ev.items] == ["b", "a"]
    assert ev.status.ok and ev.status.count == 2 and ev.fetched == NOW
    assert calls[0]["from"] == "2026-11-07T22:00:00.000Z" and calls[1]["cursor"] == "c2"


def test_outage_falls_back_to_snapshot():
    pages = {None: {"items": [raw("a", "2026-11-09T10:00:00Z")], "nextCursor": None}}
    kmaevents.save_snapshot(kmaevents.collect(client(pages, []), CFG, START, NOW))

    def down(req):
        return httpx.Response(503)
    later = datetime(2026, 11, 9, 5, tzinfo=timezone.utc)
    ev = kmaevents.collect(httpx.Client(transport=httpx.MockTransport(down)), CFG,
                           START, later)
    assert not ev.status.ok and [e.id for e in ev.items] == ["a"] and ev.fetched == NOW
    assert "snapshot from 2026-11-08" in ev.status.message


def test_outage_without_snapshot_is_empty_not_an_error():
    def bad(req):
        return httpx.Response(200, json={"oops": 1})
    ev = kmaevents.collect(httpx.Client(transport=httpx.MockTransport(bad)), CFG, START, NOW)
    assert ev.items == () and not ev.status.ok and ev.fetched is None


def _events():
    pages = {None: {"items": [
        raw("a", "2026-11-08T12:00:00Z", "Симуляція <ASEAN>", "workshop",
            endsAt="2026-11-08T14:00:00Z"),
        raw("d", "2026-11-09T21:59:00Z", "Школа переговорів", "registration_deadline"),
        raw("c", "2026-11-14T16:00:00Z", "Концерт", "fundraiser")], "nextCursor": None}}
    return kmaevents.collect(client(pages, []), CFG, START, NOW)


def test_events_page_groups_by_kyiv_day():
    html = events_page.render_events(date(2026, 11, 8), _events(), 30)
    assert "<h1>Події</h1>" in html and "3 подій" in html
    assert "Симуляція &lt;ASEAN&gt;" in html and "<ASEAN>" not in html
    assert "14:00–16:00" in html                     # Kyiv time, same-day end
    assert "до 23:59" in html and "Дедлайн реєстрації" in html
    assert html.index("неділя, 8 листопада") < html.index("понеділок, 9 листопада") \
        < html.index("субота, 14 листопада")
    assert 'href="https://instagram.com/p/a/"' in html and "Додати в календар" in html
    assert 'href="events.html" aria-current="page"' in html
    assert 'data-filter="fundraiser"' in html


def test_events_page_says_when_data_is_stale():
    ev = _events()
    stale = kmaevents.Events(ev.items, ev.status.__class__("kmaevents.com", ok=False),
                             NOW)
    assert "Не вдалося оновити" in events_page.render_events(date(2026, 11, 9), stale, 30)
    empty = kmaevents.Events((), ev.status, NOW)
    assert "Найближчих подій поки немає" in events_page.render_events(date(2026, 11, 9),
                                                                       empty, 30)


def test_site_has_events_tab_and_page(tmp_path):
    day = date(2026, 11, 8)
    html_day = digest.render_day(day, [], [], {}, [], {})
    assert 'href="events.html">Події</a>' in html_day
    assert 'href="index.html" aria-current="page"' in html_day
    digest.write_site(tmp_path, day, html_day, digest.render_index([day]),
                      pages={events_page.EVENTS_FILE: "<p>events</p>"})
    assert (tmp_path / "events.html").read_text(encoding="utf-8") == "<p>events</p>"
    assert "events" not in (tmp_path / "feed.xml").read_text(encoding="utf-8")
