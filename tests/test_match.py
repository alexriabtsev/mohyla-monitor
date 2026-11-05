from datetime import datetime, timezone

from mohyla.match import filter_and_link
from mohyla.models import Item, Person

NOW = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
HRYTSAK = Person(id="wd:Q1", name_uk="Ярослав Грицак", prominence=0.2)
BUDANOV = Person(id="wd:Q2", name_uk="Кирило Буданов", prominence=0.9,
                 socials=(("telegram", "Kyrylo_Budanov_Official"),))


def item(title, source="gnews:X", kind="media", text="", **extra):
    return Item(url=f"https://e.com/{abs(hash(title))}", title=title, text=text,
                source=source, kind=kind, published=NOW, extra=extra)


def keyword(it):
    return "могилян" in (it.title + it.text).lower()


def achievement(it):
    return "призначен" in (it.title + it.text).lower()


def run(items, **kw):
    return filter_and_link(items, [HRYTSAK, BUDANOV], keyword, achievement, **kw)


def test_keyword_item_kept_and_linked_with_declined_name():
    out = run([item("Лекція у Могилянці", text="Виступив Ярослав Грицак")])
    assert out[0].person_ids == ("wd:Q1",) and out[0].extra["keep_reason"] == "keyword"


def test_low_prominence_name_without_context_dropped():
    assert run([item("Ярослав Грицак про історію")]) == []


def test_trusted_query_hit_kept_as_body_match():
    out = run([item("Любов Галан стала заступницею міністра", query="Q")], trusted_queries=["Q"])
    assert out[0].extra["body_match"] is True


def test_untrusted_query_hit_dropped():
    assert run([item("Курс валют", query="other")], trusted_queries=["Q"]) == []


def test_own_post_needs_achievement_and_is_capped():
    src = "telegram:kyrylo_budanov_official"
    posts = [item("Новини фронту", source=src, kind="social"),
             item("Мене призначено радником", source=src, kind="social"),
             item("Указ про призначення", source=src, kind="social")]
    out = run(posts)
    assert [o.title for o in out] == ["Мене призначено радником"]
    assert out[0].person_ids == ("wd:Q2",)


def test_inputs_not_mutated():
    src = item("Могилянка", text="Ярослав Грицак")
    run([src])
    assert src.person_ids == () and "keep_reason" not in src.extra


def test_index_matches_declined_and_reversed_names():
    from mohyla.match import MatcherIndex, build_matchers, link_item
    p = Person(id="a", name_uk="Олена Петренко", aliases=("Петренко Олена Іванівна",))
    ix = MatcherIndex(build_matchers([p, HRYTSAK]))
    for text in ("з Оленою Петренко", "Петренко Олена розповіла", "Ярославом Грицаком"):
        assert link_item(item("Могилянка", text=text), ix, None, True).person_ids
