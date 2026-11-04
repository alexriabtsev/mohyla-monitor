from datetime import date, datetime, timezone

from mohyla import digest
from mohyla.models import Item, Person, SourceStatus

NOW = datetime(2026, 11, 4, 6, 30, tzinfo=timezone.utc)
D = date(2026, 11, 4)
PEOPLE = {"wd:Q42": Person(id="wd:Q42", name_uk="Олена Тест", roles=("alumnus",),
                           prominence=0.5),
          "cand:x": Person(id="cand:x", name_uk="Кандидат Х", roles=("staff",))}


def mk(title="Новина", url="https://a.ua/1", **kw):
    base = dict(text="Фрагмент", source="ukma.edu.ua", kind="official", published=NOW,
                category="achievement", score=1.0)
    base.update(kw)
    return Item(url=url, title=title, **base)


def render(items, statuses=(), new_people=()):
    return digest.render_day(D, items, list(statuses), PEOPLE, list(new_people),
                             {"people": 10, "edges": 3})


def test_escapes_script_title():
    html = render([mk(title="<script>alert(1)</script>")])
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_javascript_url_dropped():
    html = render([mk(url="javascript:alert(1)")])
    assert "javascript:alert" not in html


def test_ukrainian_month_and_kyiv_time():
    html = render([mk()])
    assert "листопада" in html
    assert "08:30, 4 лист" in html  # UTC+2 in November


def test_people_chips_and_also_and_statuses():
    it = mk(person_ids=("wd:Q42", "cand:x"),
            extra={"also": [{"source": "tg", "url": "https://t.me/a/1"}]})
    st = [SourceStatus(name="bluesky", ok=False, enabled=False, message="немає ключа"),
          SourceStatus(name="rss", ok=True, count=4)]
    html = render([it], st, [Person(id="cand:y", name_uk="Нова Людина",
                                    sources=("https://news.ua/a",))])
    assert 'href="https://www.wikidata.org/wiki/Q42"' in html
    assert "Кандидат Х" in html and "wikidata.org/wiki/x" not in html
    assert "Також:" in html and "https://t.me/a/1" in html
    assert "немає ключа" in html and "вимкнено" in html
    assert "Нова Людина" in html and "https://news.ua/a" in html


def test_empty_day_renders():
    html = render([])
    assert "<!doctype html>" in html.lower()


def test_render_index_and_write_site(tmp_path):
    idx = digest.render_index([date(2026, 11, 3), D])
    assert "2026-11-04.html" in idx and "2026-11-03.html" in idx
    day = render([mk()])
    digest.write_site(tmp_path, D, day, idx, items=[mk(title="A & B")])
    for name in ("2026-11-04.html", "index.html", "archive.html", "feed.xml", ".nojekyll"):
        assert (tmp_path / name).exists()
    feed = (tmp_path / "feed.xml").read_text(encoding="utf-8")
    assert "<rss" in feed and "A &amp; B" in feed
    assert "archive.html" in (tmp_path / "index.html").read_text(encoding="utf-8")
