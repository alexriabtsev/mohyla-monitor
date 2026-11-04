import json
from datetime import date, datetime, timedelta, timezone

import pytest

from mohyla import state
from mohyla.models import Item, SourceStatus

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)


def mk(url, **kw):
    return Item(url=url, title="Т", text="", source="s", kind="media", published=NOW, **kw)


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    return tmp_path


def test_seen_roundtrip_and_filter(tmp_data):
    assert state.load_seen() == {}
    seen = state.mark_seen({}, [mk("https://a.ua/1?utm_source=x")], NOW)
    state.save_seen(seen)
    loaded = state.load_seen()
    assert loaded == seen
    out = state.filter_unseen([mk("https://a.ua/1/"), mk("https://a.ua/2")], loaded)
    assert [i.url for i in out] == ["https://a.ua/2"]


def test_mark_seen_new_dict_keeps_first_seen_and_prunes():
    old = (NOW - timedelta(days=40)).isoformat()
    first = (NOW - timedelta(days=2)).isoformat()
    seen = {"https://old.ua/x": old, "https://a.ua/1": first}
    out = state.mark_seen(seen, [mk("https://a.ua/1"), mk("https://b.ua/1")], NOW)
    assert "https://old.ua/x" in seen  # input untouched
    assert "https://old.ua/x" not in out
    assert out["https://a.ua/1"] == first
    assert "https://b.ua/1" in out


def test_corrupt_seen_raises(tmp_data):
    (tmp_data / "seen.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(state.StateError):
        state.load_seen()


def test_digest_roundtrip(tmp_data):
    d = date(2026, 11, 4)
    items = [mk("https://a.ua/1", person_ids=("wd:Q1",), category="science", score=1.5,
                extra={"also": [{"source": "x", "url": "https://x"}]})]
    st = [SourceStatus(name="rss", ok=True, count=1)]
    path = state.save_digest(d, items, st, {"note": "Могилянка"})
    assert path.name == "2026-11-04.json"
    assert "Могилянка" in path.read_text(encoding="utf-8")  # ensure_ascii=False
    data = state.load_digest(d)
    assert data["items"][0] == items[0]
    assert data["items"][0].extra == items[0].extra
    assert data["statuses"] == st
    assert data["extra"] == {"note": "Могилянка"}
    assert state.list_digest_dates() == [d]


def test_missing_digest_and_dates(tmp_data):
    assert state.load_digest(date(2020, 1, 1)) is None
    assert state.list_digest_dates() == []


def test_extra_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DATA_DIR", tmp_path)
    assert state.load_extra("telegram_discovered") == set()
    state.save_extra("telegram_discovered", {"b", "a"})
    assert state.load_extra("telegram_discovered") == {"a", "b"}
