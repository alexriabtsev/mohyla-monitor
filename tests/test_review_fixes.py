"""Regressions for issues found in code review (state across runs, matching precision)."""
from datetime import datetime, timedelta, timezone

import pytest

from mohyla import cli, rank, state
from mohyla.collectors import kmaevents
from mohyla.config import load_config
from mohyla.models import Item, Person, SourceStatus
from mohyla.people import graph, store
from mohyla.people.names import name_pattern

NOW = datetime.now(timezone.utc)


def test_surname_does_not_match_longer_surname():
    pat = name_pattern(Person(id="x", name_uk="Олег Мороз"))
    assert pat.search("Олега Мороза") and pat.search("з Олегом Морозом")
    assert not pat.search("Олег Морозов") and not pat.search("Олега Морозова")


def test_malformed_url_does_not_raise():
    assert rank.canonical_url("http://[x") == "http://[x"


def _story(url, text, title=""):
    return Item(url=url, title=title or text, text=text, source="s", kind="media",
                published=NOW)


def test_candidate_needs_two_outlets_and_is_announced_once():
    text = "випускниця Могилянки Олена Петренко отримала премію"
    same_outlet = [_story("https://a.ua/1", text), _story("https://a.ua/2", text)]
    cands = graph.update_candidates({}, same_outlet, [])
    assert graph.promote(cands) == []
    cands = graph.update_candidates(cands, [_story("https://b.ua/1", text)], [])
    promoted = graph.promote(cands)
    assert [p.name_uk for p in promoted] == ["Олена Петренко"]
    assert graph.promote(graph.mark_promoted(cands, promoted)) == []


def test_mark_seen_urls_includes_folded_duplicates():
    seen = state.mark_seen_urls({}, ["https://www.a.ua/x/?utm_source=t"], NOW)
    assert list(seen) == ["https://a.ua/x"]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for mod in (state, store):
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cli, "SITE_DIR", tmp_path / "docs")
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cli, "_events", lambda cfg, day, now: kmaevents.Events(
        (), SourceStatus(name="kmaevents.com", ok=True), now))
    return tmp_path


def _fake_collect(batches):
    def collect(cfg, people, since):
        items = batches.pop(0)
        return items, [SourceStatus(name="fake", ok=True, count=len(items))], {}
    return collect


def test_same_day_rerun_extends_issue_and_never_repeats(sandbox, monkeypatch):
    first = [_story("https://a.ua/1", "Могилянка відкрила лабораторію"),
             _story("https://b.ua/1", "Могилянка відкрила лабораторію")]  # duplicate
    second = [*first, _story("https://c.ua/2", "У НаУКМА новий курс про ШІ")]
    monkeypatch.setattr(cli, "_collect", _fake_collect([first, second]))
    cfg = load_config()
    assert cli.cmd_daily(cfg) == 0
    assert cli.cmd_daily(cfg) == 0
    day = NOW.astimezone(cli.KYIV).date()
    urls = sorted(i.url for i in state.load_digest(day)["items"])
    assert urls == ["https://a.ua/1", "https://c.ua/2"]
    assert "https://b.ua/1" in state.load_seen()
    assert (sandbox / "docs" / "index.html").exists()
    assert "<h1>Події</h1>" in (sandbox / "docs" / "events.html").read_text(encoding="utf-8")


def test_people_refresh_refuses_to_shrink_base(sandbox, monkeypatch):
    big = [Person(id=f"wd:Q{i}", name_uk=f"Ім'я{i} Прізвище{i}") for i in range(10)]
    store.save_people(big)
    monkeypatch.setattr(cli.wikidata, "fetch_people", lambda c, cfg: big[:3])
    monkeypatch.setattr(cli.wikipedia, "fetch_category_people", lambda c, cfg: [])
    monkeypatch.setattr(cli.wikidata, "enrich_people", lambda c, cfg, p: [])
    assert cli.cmd_people(load_config()) == 1
    assert len(store.load_people()) == 10


def test_daily_saves_discovered_facebook_and_telegram_links(sandbox, monkeypatch):
    story = Item(url="https://t.me/fen_news/1", title="Могилянка", source="telegram:fen_news",
                 kind="social", published=NOW,
                 text="Могилянка: деталі на facebook.com/naukma.fen та t.me/fen_news")
    monkeypatch.setattr(cli, "_collect", _fake_collect([[story]]))
    assert cli.cmd_daily(load_config()) == 0
    assert state.load_extra("facebook_discovered") == {"https://www.facebook.com/naukma.fen/"}
    assert state.load_extra("telegram_discovered") == {"fen_news"}


def test_story_from_an_earlier_issue_is_not_repeated(sandbox, monkeypatch):
    title = "Могилянка оголосила переможців конкурсу «Зірка ФЕН» цього року"
    yesterday = NOW.astimezone(cli.KYIV).date() - timedelta(days=1)
    state.save_digest(yesterday, [_story("https://facebook.com/fen/posts/pfbid1", title, title)], [], {})
    repost = _story("https://facebook.com/fen/posts/pfbid2", title + "!", title)  # new URL, same post
    other = _story("https://c.ua/3", "У НаУКМА новий курс про ШІ")
    monkeypatch.setattr(cli, "_collect", _fake_collect([[repost, other]]))
    assert cli.cmd_daily(load_config()) == 0
    today = state.load_digest(NOW.astimezone(cli.KYIV).date())["items"]
    assert [i.url for i in today] == ["https://c.ua/3"]
    assert "https://facebook.com/fen/posts/pfbid2" in state.load_seen()  # not re-checked daily
