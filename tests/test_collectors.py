"""Collector tests: saved fixtures + httpx.MockTransport, no real network."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from mohyla import http as mhttp
from mohyla.collectors import (
    ALL_COLLECTORS, bluesky, facebook_apify, facebook_links, google_news, rss, run_all, telegram, websearch,
)
from mohyla.models import Item, Person

FIX = Path(__file__).parent / "fixtures"
SINCE = datetime(2026, 11, 2, tzinfo=timezone.utc)


def fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # fetch() backs off with time.sleep on transient errors; keep tests fast
    monkeypatch.setattr(mhttp.time, "sleep", lambda s: None)
    monkeypatch.setattr(telegram.time, "sleep", lambda s: None)


@pytest.fixture
def no_secrets(monkeypatch):
    for k in ("BSKY_HANDLE", "BSKY_APP_PASSWORD", "APIFY_TOKEN", "BRAVE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def assert_items_valid(items: tuple[Item, ...]) -> None:
    for it in items:
        assert it.published.tzinfo is not None
        assert it.published >= SINCE
        assert "<" not in it.text and "  " not in it.text
        assert len(it.text) <= 1500


# ---------- rss ----------

RSS_CFG = {"rss": [{"name": "ukma.edu.ua", "url": "https://ukma.test/rss", "kind": "official"}]}


def test_rss_since_filter_and_clean_text():
    c = client_for(lambda r: httpx.Response(200, content=fx("ukma_rss.xml")))
    res = rss.collect(c, RSS_CFG, SINCE, [])
    assert res.status.ok and res.status.name == "rss" and res.status.count == 2
    assert [i.title[:10] for i in res.items] == ["У Стамбулі", "Могилянка "]
    first = res.items[0]
    assert first.source == "ukma.edu.ua" and first.kind == "official"
    assert first.text.startswith("22–24 жовтня 2026 року в Стамбулі")
    assert first.published == datetime(2026, 11, 4, 5, 29, 43, tzinfo=timezone.utc)
    assert_items_valid(res.items)


def test_rss_failure_returns_partial_without_raising():
    cfg = {"rss": RSS_CFG["rss"] + [{"name": "bad", "url": "https://bad.test/rss", "kind": "media"}]}

    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.host == "bad.test":
            return httpx.Response(403)
        return httpx.Response(200, content=fx("ukma_rss.xml"))

    res = rss.collect(client_for(handler), cfg, SINCE, [])
    assert not res.status.ok and "bad" in res.status.message
    assert len(res.items) == 2


def test_rss_network_exception_does_not_raise():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=r)

    res = rss.collect(client_for(handler), RSS_CFG, SINCE, [])
    assert not res.status.ok and res.items == ()


# ---------- google news ----------

def gnews_handler(seen: list[dict]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(r: httpx.Request) -> httpx.Response:
        qs = parse_qs(urlparse(str(r.url)).query)
        seen.append(qs)
        return httpx.Response(200, content=fx("gnews_uk.xml" if qs["hl"] == ["uk"] else "gnews_en.xml"))
    return handler


def test_google_news_editions_title_cleanup_and_dedupe():
    seen: list[dict] = []
    res = google_news.collect(client_for(gnews_handler(seen)), {"google_news_queries": ['"НаУКМА"']}, SINCE, [])
    assert {q["ceid"][0] for q in seen} == {"UA:uk", "US:en"}
    assert all(q["q"][0] == '"НаУКМА" when:2d' for q in seen)
    titles = [i.title for i in res.items]
    # duplicate "Будь серед своїх" across editions collapses; old item dropped
    assert titles == ["Будь серед своїх. Де волонтерити в Києві",
                      "Випускниця Могилянки - Тетяна - отримала премію",
                      "Kyiv-Mohyla Academy hosts NATO workshop"]
    first = res.items[0]
    assert first.source == "gnews:Вікенд" and first.kind == "media"
    assert first.url.startswith("https://news.google.com/rss/articles/")
    assert first.extra["publisher_url"] == "https://weekend.today"
    assert res.status.ok and res.status.count == 3
    assert_items_valid(res.items)


def test_google_news_failure_is_status_not_exception():
    res = google_news.collect(client_for(lambda r: httpx.Response(503)),
                              {"google_news_queries": ["x"]}, SINCE, [])
    assert not res.status.ok and res.items == ()


def test_strip_publisher():
    assert google_news.strip_publisher("A - B - Pub", "Pub") == "A - B"
    assert google_news.strip_publisher("Title only", "Pub") == "Title only"
    assert google_news.strip_publisher("A - Other", "") == "A"


# ---------- telegram ----------

def tg_handler(calls: list[str]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r.url.path)
        if r.url.path == "/s/naukmanews":
            return httpx.Response(200, content=fx("tg_channel.html"))
        if r.url.path == "/s/gone_away":
            return httpx.Response(404)
        return httpx.Response(200, content=fx("tg_not_channel.html"))
    return handler


def test_telegram_parse_and_channel_union():
    calls: list[str] = []
    people = [Person(id="wd:Q1", name_uk="А Б", socials=(("telegram", "@PersonChan"), ("facebook", "x")))]
    cfg = {"telegram_channels": ["naukmanews"], "telegram_discovered": ["https://t.me/gone_away"],
           "telegram_delay": 0}
    res = telegram.collect(client_for(tg_handler(calls)), cfg, SINCE, people)
    assert sorted(calls) == ["/s/gone_away", "/s/naukmanews", "/s/personchan"]
    assert res.status.ok
    assert [i.url for i in res.items] == ["https://t.me/naukmanews/41", "https://t.me/naukmanews/43"]
    hack = res.items[0]
    assert hack.title == "Студенти НаУКМА перемогли на хакатоні"
    assert hack.author == "Могилянський Новинач"
    assert hack.source == "telegram:naukmanews" and hack.kind == "social"
    assert hack.published == datetime(2026, 11, 4, 8, 15, tzinfo=timezone.utc)
    assert len(res.items[1].title) <= 140
    assert_items_valid(res.items)


def test_telegram_caps_channels():
    calls: list[str] = []
    cfg = {"telegram_channels": [f"chan{i}" for i in range(10)], "telegram_max_channels": 3,
           "telegram_delay": 0}
    telegram.collect(client_for(tg_handler(calls)), cfg, SINCE, [])
    assert len(calls) == 3


def test_discover_channels():
    def mk(text: str, url: str = "https://example.com/a") -> Item:
        return Item(url=url, title="t", text=text, source="s", kind="media", published=SINCE)

    items = [
        mk("Підписуйтесь: https://t.me/kmafi_news та t.me/s/preview_only і https://t.me/joinchat/AAA"),
        mk("invite https://t.me/+AbCdEf, bot t.me/mohyla_helper_bot, also telegram.me/Other_Chan"),
        mk("", url="https://t.me/naukmanews/41"),
    ]
    assert telegram.discover_channels(items) == {"kmafi_news", "other_chan", "naukmanews"}


# ---------- optional collectors: disabled without secrets ----------

@pytest.mark.parametrize("mod,env", [
    (bluesky, "BSKY_HANDLE"), (facebook_apify, "APIFY_TOKEN"), (websearch, "BRAVE_API_KEY"),
])
def test_disabled_without_secret(no_secrets, mod, env):
    def handler(r: httpx.Request) -> httpx.Response:
        raise AssertionError("no network expected")

    res = mod.collect(client_for(handler), {}, SINCE, [])
    assert res.status.enabled is False and res.status.ok is True
    assert env in res.status.message and res.status.message.startswith("disabled: set")
    assert res.items == ()


# ---------- bluesky ----------

def test_bluesky_search(monkeypatch):
    monkeypatch.setenv("BSKY_HANDLE", "me.bsky.social")
    monkeypatch.setenv("BSKY_APP_PASSWORD", "app-pass")
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        if r.url.path.endswith("createSession"):
            return httpx.Response(200, json={"accessJwt": "JWT", "did": "did:plc:me"})
        assert r.headers["Authorization"] == "Bearer JWT"
        return httpx.Response(200, content=fx("bluesky_search.json"))

    res = bluesky.collect(client_for(handler), {"bluesky_queries": ["Могилянка"]}, SINCE, [])
    search = seen[1]
    assert search.url.params["q"] == "Могилянка" and search.url.params["sort"] == "latest"
    assert search.url.params["since"].startswith("2026-11-02T00:00:00")
    assert res.status.ok and len(res.items) == 1
    it = res.items[0]
    assert it.url == "https://bsky.app/profile/olena.bsky.social/post/3lxyzold1"
    assert it.title == "Сьогодні виступала в Могилянці про медіаграмотність."
    assert it.author == "Олена" and it.kind == "social" and it.source == "bluesky:olena.bsky.social"
    assert_items_valid(res.items)


def test_bluesky_auth_failure(monkeypatch):
    monkeypatch.setenv("BSKY_HANDLE", "me")
    monkeypatch.setenv("BSKY_APP_PASSWORD", "bad")
    res = bluesky.collect(client_for(lambda r: httpx.Response(401)), {"bluesky_queries": ["x"]}, SINCE, [])
    assert res.status.enabled and not res.status.ok and res.items == ()
    assert "bad" not in res.status.message


# ---------- facebook via apify ----------

class FakeApify:
    """Mock Apify API: runs start RUNNING, finish on the first poll, datasets from a fixture."""

    def __init__(self, final_status="SUCCEEDED", poll_ok=True):
        self.started: list[tuple[str, dict, dict]] = []
        self.calls: list[str] = []
        self.final_status, self.poll_ok = final_status, poll_ok

    def __call__(self, r: httpx.Request) -> httpx.Response:
        # token goes in the Authorization header so it never appears in logged URLs
        assert r.headers["Authorization"] == "Bearer SECRET-TOKEN"
        assert "token" not in r.url.params
        path = r.url.path
        self.calls.append(f"{r.method} {path}")
        if r.method == "POST" and path.endswith("/runs"):
            actor = path.split("/")[-2]
            self.started.append((actor, json.loads(r.content), dict(r.url.params)))
            return httpx.Response(201, json={"data": {"id": f"run-{actor}", "status": "RUNNING",
                                                      "defaultDatasetId": f"ds-{actor}"}})
        if path.endswith("/abort"):
            return httpx.Response(200, json={"data": {"id": "x", "status": "ABORTING",
                                                      "defaultDatasetId": "ds-partial"}})
        if path.startswith("/v2/actor-runs/"):
            if not self.poll_ok:
                return httpx.Response(500)
            rid = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"data": {
                "id": rid, "status": self.final_status, "usageTotalUsd": 0.12,
                "defaultDatasetId": "ds-" + rid.removeprefix("run-")}})
        if path.startswith("/v2/datasets/"):
            return httpx.Response(200, content=fx("apify_fb.json"))
        raise AssertionError(path)


def test_facebook_apify_one_run_for_pages_and_one_for_groups(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "SECRET-TOKEN")
    api = FakeApify()
    people = [Person(id="p", name_uk="X", socials=(("facebook", "some.person"),))]
    cfg = {"facebook_pages": ["https://www.facebook.com/naukma/", "naukma"],
           "facebook_groups": ["https://m.facebook.com/groups/mohyla.alumni/?ref=share"],
           "facebook_discovered": ["https://www.facebook.com/kmbs.ua/"],
           "facebook_max_charge_usd": 0.3}
    res = facebook_apify.collect(client_for(api), cfg, SINCE, people)
    assert [a for a, _, _ in api.started] == ["apify~facebook-posts-scraper",
                                              "apify~facebook-groups-scraper"]
    pages_input, params = api.started[0][1], api.started[0][2]
    assert [u["url"] for u in pages_input["startUrls"]] == [
        "https://www.facebook.com/naukma/", "https://www.facebook.com/some.person/",
        "https://www.facebook.com/kmbs.ua/"]
    assert pages_input["onlyPostsNewerThan"] == "2026-11-02"
    assert params == {"maxItems": "2000", "maxTotalChargeUsd": "0.3"}
    assert api.started[1][1]["startUrls"] == [
        {"url": "https://www.facebook.com/groups/mohyla.alumni/"}]
    assert res.status.ok
    # per dataset: 111 (time) + 113 (timestamp); 112 old, error row skipped; dedup across runs
    assert [i.url for i in res.items] == ["https://www.facebook.com/naukma/posts/pfbid111",
                                          "https://www.facebook.com/naukma/posts/pfbid113"]
    assert res.items[0].author == "НаУКМА" and res.items[1].author == "Fallback Name"
    assert res.items[0].source == "facebook:naukma"  # from facebookUrl, matches profile handles
    assert res.items[1].source == "facebook:Fallback Name"
    assert res.items[0].kind == "social"
    assert_items_valid(res.items)


def test_facebook_caps_sources(monkeypatch):
    cfg = {"facebook_pages": [f"page{i}" for i in range(10)], "facebook_max_pages": 3}
    pages, groups = facebook_apify.source_lists(cfg, [])
    assert pages == [f"https://www.facebook.com/page{i}/" for i in range(3)] and groups == []


def test_facebook_failed_run_keeps_partial_rows(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "SECRET-TOKEN")
    res = facebook_apify.collect(client_for(FakeApify(final_status="ABORTED")),
                                 {"facebook_pages": ["naukma"]}, SINCE, [])
    assert not res.status.ok and "ABORTED" in res.status.message
    assert len(res.items) == 2


def test_facebook_run_over_budget_is_aborted(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "SECRET-TOKEN")
    api = FakeApify()
    cfg = {"facebook_pages": ["naukma"], "facebook_timeout_minutes": 0}
    res = facebook_apify.collect(client_for(api), cfg, SINCE, [])
    assert any(c.endswith("/abort") for c in api.calls)
    assert "TIMED-OUT" in res.status.message and len(res.items) == 2


def test_facebook_failure_never_leaks_token(monkeypatch, caplog):
    monkeypatch.setenv("APIFY_TOKEN", "SECRET-TOKEN")
    res = facebook_apify.collect(client_for(lambda r: httpx.Response(400)),
                                 {"facebook_pages": ["https://www.facebook.com/naukma/"]}, SINCE, [])
    assert not res.status.ok
    assert "SECRET-TOKEN" not in res.status.message
    assert "SECRET-TOKEN" not in caplog.text


def test_facebook_poll_failure_reported(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "SECRET-TOKEN")
    res = facebook_apify.collect(client_for(FakeApify(poll_ok=False)),
                                 {"facebook_pages": ["naukma"]}, SINCE, [])
    assert not res.status.ok and res.items == ()


@pytest.mark.parametrize("raw,canon", [
    ("naukma", "https://www.facebook.com/naukma/"),
    ("@kmbs.ua", "https://www.facebook.com/kmbs.ua/"),
    ("https://m.facebook.com/naukma/posts/123", "https://www.facebook.com/naukma/"),
    ("fb.com/groups/12345/permalink/9", "https://www.facebook.com/groups/12345/"),
    ("https://www.facebook.com/sharer/sharer.php?u=x", None),
    ("https://www.facebook.com/profile.php?id=1", None),
    ("https://example.com/naukma", None),
    ("https://www.facebook.com/groups/", None),
])
def test_facebook_link_normalize(raw, canon):
    assert facebook_links.normalize(raw) == canon


def _post(text, kind="social", reason="keyword", source="telegram:x"):
    return Item(url="https://t.me/x/1", title="t", source=source, kind=kind, published=SINCE,
                text=text, extra={"keep_reason": reason})


def test_facebook_discover_links_only_from_mohyla_social_posts():
    text = "Деталі на facebook.com/naukma.fen і в групі https://www.facebook.com/groups/ukma.alumni"
    found = facebook_links.discover([_post(text), _post("facebook.com/news.outlet", kind="media"),
                                     _post("facebook.com/someone.else", reason="person")])
    assert found == {"https://www.facebook.com/naukma.fen/",
                     "https://www.facebook.com/groups/ukma.alumni/"}


def test_facebook_lookalike_hosts_ignored():
    assert facebook_links.discover([_post("знижки на shopfb.com/sale та notfacebook.com/x")]) == set()


def test_facebook_abort_failure_keeps_partial_rows(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "SECRET-TOKEN")
    api = FakeApify()

    def handler(r):
        return httpx.Response(500) if r.url.path.endswith("/abort") else api(r)

    res = facebook_apify.collect(client_for(handler),
                                 {"facebook_pages": ["naukma"], "facebook_timeout_minutes": 0},
                                 SINCE, [])
    assert "TIMED-OUT" in res.status.message and len(res.items) == 2


def test_facebook_group_post_labelled_with_group():
    row = {"url": "https://www.facebook.com/groups/12345/posts/2", "text": "Привіт", "time":
           "2026-11-04T07:00:00Z", "facebookUrl": "https://www.facebook.com/groups/12345/",
           "groupTitle": "Могилянці", "user": {"name": "Член Групи"}}
    item = facebook_apify.row_to_item(row, SINCE)
    assert item.source == "facebook:Могилянці" and item.author == "Член Групи"
    assert item.extra == {"fb_group": "Могилянці"}


def test_facebook_blank_setting_uses_default():
    assert facebook_apify.setting({"facebook_max_items": None}, "facebook_max_items") == 2000


def test_facebook_discovered_sources_capped():
    cfg = {"facebook_discovered": [f"d{i}" for i in range(50)], "facebook_max_discovered": 2}
    assert facebook_apify.source_lists(cfg, [])[0] == ["https://www.facebook.com/d0/",
                                                       "https://www.facebook.com/d1/"]


# ---------- websearch (brave) ----------

def test_websearch_brave(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "KEY")

    def handler(r: httpx.Request) -> httpx.Response:
        assert r.headers["X-Subscription-Token"] == "KEY"
        assert r.url.params["freshness"] == "pd" and r.url.params["count"] == "20"
        return httpx.Response(200, content=fx("brave_search.json"))

    res = websearch.collect(client_for(handler), {"websearch_queries": ["q1"]}, SINCE, [])
    assert res.status.ok and len(res.items) == 2
    li, xx = res.items
    assert li.source == "web:linkedin.com" and xx.source == "web:x.com"
    assert li.published == datetime(2026, 11, 4, 6, tzinfo=timezone.utc)
    assert "date_estimated" not in li.extra and xx.extra["date_estimated"] is True
    assert li.text == "Proud Kyiv-Mohyla alumna & new role"
    assert_items_valid(res.items)


def test_websearch_failure(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "KEY")
    res = websearch.collect(client_for(lambda r: httpx.Response(429)),
                            {"websearch_queries": ["q1"]}, SINCE, [])
    assert not res.status.ok and res.items == ()


# ---------- registry / run_all ----------

def test_registry_order():
    assert [n for n, _ in ALL_COLLECTORS] == [
        "rss", "google_news", "telegram", "bluesky", "facebook_apify", "websearch"]


def test_run_all_isolates_exceptions(no_secrets, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    import mohyla.collectors as pkg
    patched = tuple((n, boom if n == "rss" else f) for n, f in pkg.ALL_COLLECTORS)
    monkeypatch.setattr(pkg, "ALL_COLLECTORS", patched)
    cfg = {"google_news_queries": ["x"], "telegram_channels": ["naukmanews"], "telegram_delay": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.host == "t.me":
            return httpx.Response(200, content=fx("tg_channel.html"))
        return httpx.Response(200, content=fx("gnews_uk.xml"))

    items, statuses = run_all(client_for(handler), cfg, SINCE, [])
    by = {s.name: s for s in statuses}
    assert [s.name for s in statuses] == [n for n, _ in ALL_COLLECTORS]
    assert not by["rss"].ok and "kaboom" in by["rss"].message
    assert by["google_news"].ok and by["telegram"].ok
    assert not by["bluesky"].enabled
    assert len(items) == by["google_news"].count + by["telegram"].count > 0
