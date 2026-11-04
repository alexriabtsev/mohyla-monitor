from datetime import datetime, timedelta, timezone

import pytest

from mohyla.config import load_config
from mohyla.models import Item, Person
from mohyla.rank import (canonical_url, categorize, dedupe, is_relevant, rank, score,
                         select_digest)

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)
CFG = load_config()


def mk(url="https://a.ua/x", title="t", text="", source="s", kind="media",
       hours=1.0, **kw) -> Item:
    return Item(url=url, title=title, text=text, source=source, kind=kind,
                published=NOW - timedelta(hours=hours), **kw)


@pytest.mark.parametrize("title", [
    "Могилянка відкриває нову програму", "Науковці Києво-Могилянської академії",
    "Kyiv-Mohyla Academy hosts forum", "Новини НаУКМА", "kmbs запускає курс",
])
def test_relevant_positive(title):
    assert is_relevant(mk(title=title), CFG["relevance_patterns"])


@pytest.mark.parametrize("title", [
    "Братська могила на Лук'янівці", "Mohylev weather", "Укманія — новий бренд",
])
def test_relevant_negative(title):
    assert not is_relevant(mk(title=title), CFG["relevance_patterns"])


def test_relevant_uses_text():
    assert is_relevant(mk(title="Новина", text="випускниця Могилянки"),
                       CFG["relevance_patterns"])


def test_categorize():
    cats = CFG["categories"]
    assert categorize(mk(title="Випускниця отримала премію"), cats) == "achievement"
    assert categorize(mk(title="Нове дослідження клімату"), cats) == "science"
    assert categorize(mk(title="Студенти провели толоку"), cats) == "students"
    assert categorize(mk(title="Відкрили нову каву"), cats) == "community"


def test_canonical_url():
    a = canonical_url("https://Ukma.edu.ua/news/1/?utm_source=x&id=5#top")
    assert a == canonical_url("https://ukma.edu.ua/news/1?id=5")


def test_dedupe_by_url_keeps_one_with_also():
    a = mk(url="https://x.ua/n/1?utm_source=fb", title="A", source="s1", score=2.0)
    b = mk(url="https://x.ua/n/1/", title="Зовсім інше", source="s2", score=1.0)
    out = dedupe([a, b])
    assert len(out) == 1
    assert out[0].source == "s1"
    assert out[0].extra["also"] == [{"source": "s2", "url": "https://x.ua/n/1/"}]
    assert a.extra == {}  # input untouched


def test_dedupe_by_title_similarity_and_kind_tiebreak():
    t1 = "Випускниця Могилянки отримала Шевченківську премію 2026 року"
    t2 = "Випускниця Могилянки отримала Шевченківську премію 2026 року!"
    soc = mk(url="https://t.me/a/1", title=t1, source="tg", kind="social", score=3.0)
    off = mk(url="https://ukma.edu.ua/1", title=t2, source="ukma", kind="official", score=3.0)
    med = mk(url="https://other.ua/z", title="Інша тема зовсім", source="m", score=1.0)
    out = dedupe([soc, off, med])
    assert len(out) == 2
    keep = [i for i in out if i.title in (t1, t2)][0]
    assert keep.kind == "official"
    assert keep.extra["also"][0]["source"] == "tg"


def test_dedupe_higher_score_wins_over_kind():
    t = "Могилянка увійшла до рейтингу QS найкращих університетів"
    soc = mk(url="https://t.me/a/2", title=t, kind="social", source="tg", score=5.0)
    off = mk(url="https://ukma.edu.ua/2", title=t, kind="official", source="u", score=1.0)
    assert dedupe([off, soc])[0].kind == "social"


def test_score_ordering():
    people = {"wd:Q1": Person(id="wd:Q1", name_uk="Ім'я", prominence=0.9)}
    w = CFG["weights"]
    ach = mk(title="премія", category="achievement", person_ids=("wd:Q1",), hours=2)
    old = mk(title="x", category="community", hours=60)
    assert score(ach, people, w, NOW) > score(old, people, w, NOW)


def test_score_person_cap():
    w = CFG["weights"]
    ids = tuple(f"p{i}" for i in range(10))
    s3 = score(mk(person_ids=ids[:3], hours=0), {}, w, NOW)
    s10 = score(mk(person_ids=ids, hours=0), {}, w, NOW)
    assert s3 == pytest.approx(s10)


def test_rank_sets_category_score_and_sorts():
    items = [mk(url="https://a.ua/1", title="Студенти Могилянки", hours=30),
             mk(url="https://a.ua/2", title="Могилянка отримала грант", hours=1)]
    out = rank(items, {}, CFG, NOW)
    assert [i.category for i in out] == ["achievement", "students"]
    assert out[0].score >= out[1].score > 0
    assert items[0].score == 0.0


def test_select_digest_source_cap():
    items = [mk(url=f"https://a.ua/{i}", source="big", score=10 - i * 0.1) for i in range(10)]
    items += [mk(url=f"https://b.ua/{i}", source=f"o{i}", score=1.0) for i in range(10)]
    out = select_digest(items, 10)
    assert len(out) == 10
    assert sum(1 for i in out if i.source == "big") <= 4


def test_select_digest_min_achievements():
    items = [mk(url=f"https://a.ua/{i}", source=f"s{i}", score=10.0, category="community")
             for i in range(10)]
    items += [mk(url=f"https://b.ua/{i}", source=f"t{i}", score=0.1, category="achievement")
              for i in range(3)]
    out = select_digest(items, 6)
    assert len(out) == 6
    assert sum(1 for i in out if i.category == "achievement") == 3
    assert out == sorted(out, key=lambda i: -i.score)


def test_select_digest_small_input():
    items = [mk(url="https://a.ua/1", source="x", score=1.0)]
    assert len(select_digest(items, 30)) == 1


def test_keep_reason_weight_prefers_explicit_mention():
    from datetime import datetime, timezone
    from mohyla.models import Item
    from mohyla.rank import score
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    w = {"kind": {"media": 1.0}, "keep_reason": {"keyword": 2.0, "body": 0.5}}
    mk = lambda r: Item(url="https://e.com", title="t", text="", source="s", kind="media",
                        published=now, extra={"keep_reason": r})
    assert score(mk("keyword"), {}, w, now) > score(mk("body"), {}, w, now)
