"""Tests for mohyla.people.graph and mohyla.people.store."""
import copy
from datetime import datetime, timezone

import pytest

from mohyla.models import Edge, Item, Person
from mohyla.people import store
from mohyla.people.graph import (
    comention_edges,
    employer_edges,
    merge_people,
    promote,
    update_candidates,
)

T1 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


def _item(url, title="", text="", ids=(), when=T1):
    return Item(url=url, title=title, text=text, source="test", kind="media",
                published=when, person_ids=tuple(ids))


# --- merge_people --------------------------------------------------------------

def test_merge_by_id_unions_fields():
    a = Person(id="wd:Q1", name_uk="Олена Петренко", roles=("alumnus",),
               socials=(("telegram", "olena"),), sources=("https://wd/Q1",), prominence=0.3)
    b = Person(id="wd:Q1", name_uk="Олена Петренко", roles=("staff",), aliases=("Олена П.",),
               sources=("https://uk.wikipedia.org/wiki/X",), prominence=0.7, employers=("Q9",))
    (m,) = merge_people([a], [b])
    assert m.roles == ("alumnus", "staff")
    assert m.socials == (("telegram", "olena"),)
    assert m.aliases == ("Олена П.",)
    assert m.employers == ("Q9",)
    assert m.prominence == 0.7
    assert set(m.sources) == {"https://wd/Q1", "https://uk.wikipedia.org/wiki/X"}


def test_merge_by_normalized_name_prefers_wikidata_id():
    wp = Person(id="wp:uk:Петренко Олена", name_uk="Олена Петренко", roles=("alumnus",))
    wd = Person(id="wd:Q5", name_uk="олена  петренко", name_en="Olena Petrenko", roles=("staff",))
    (m,) = merge_people([wp], [wd])
    assert m.id == "wd:Q5"
    assert m.name_en == "Olena Petrenko"
    assert set(m.roles) == {"alumnus", "staff"}


def test_namesakes_with_two_wikidata_ids_stay_separate():
    a = Person(id="wd:Q1", name_uk="Іван Петренко")
    b = Person(id="wd:Q2", name_uk="Іван Петренко")
    assert len(merge_people([a, b])) == 2


def test_merge_does_not_mutate_inputs():
    a = [Person(id="wd:Q1", name_uk="Олена Петренко", roles=("alumnus",))]
    b = [Person(id="wd:Q1", name_uk="Олена Петренко", roles=("staff",))]
    a_copy, b_copy = copy.deepcopy(a), copy.deepcopy(b)
    merge_people(a, b)
    assert a == a_copy and b == b_copy


# --- edges ---------------------------------------------------------------------

def test_employer_edges_excludes_university_and_generic():
    people = [Person(id=f"wd:Q{i}", name_uk=f"Особа {i}", employers=("Q1133013", "Q77"))
              for i in range(3)]
    big = [Person(id=f"wd:Q{100 + i}", name_uk=f"X {i}", employers=("Q88",)) for i in range(41)]
    edges = employer_edges(people + big, exclude={"Q1133013"})
    assert len(edges) == 3
    assert all(e.kind == "employer" for e in edges)
    assert all(e.a < e.b for e in edges)
    assert "https://www.wikidata.org/wiki/Q77" in edges[0].evidence


def test_comention_edges_accumulate():
    items = [_item(f"https://n/{i}", ids=("wd:Q2", "wd:Q1")) for i in range(7)]
    items.append(_item("https://n/x", ids=("wd:Q1",)))
    (e,) = comention_edges(items)
    assert (e.a, e.b, e.kind, e.weight) == ("wd:Q1", "wd:Q2", "comention", 7.0)
    assert len(e.evidence) == 5


# --- candidates ----------------------------------------------------------------

def test_update_candidates_counts_and_skips_known():
    known = [Person(id="wd:Q1", name_uk="Ярослав Грицак")]
    items = [
        _item("https://a", "випускниця Могилянки Олена Петренко перемогла", when=T1),
        _item("https://b", "", "Олена Петренко, випускниця НаУКМА; "
              "випускник Могилянки Ярослав Грицак", when=T2),
    ]
    original = {}
    out = update_candidates(original, items, known)
    assert original == {}
    assert list(out) == ["олена петренко"]
    rec = out["олена петренко"]
    assert rec["name"] == "Олена Петренко"
    assert rec["count"] == 2
    assert rec["evidence"] == ["https://a", "https://b"]
    assert rec["first_seen"].startswith("2026-11-01")
    assert rec["last_seen"].startswith("2026-11-03")
    assert rec["role"] == "alumnus"


def test_update_candidates_is_idempotent_per_url():
    items = [_item("https://a", "випускниця Могилянки Олена Петренко")]
    once = update_candidates({}, items, [])
    twice = update_candidates(once, items, [])
    assert twice["олена петренко"]["count"] == 1
    assert once["олена петренко"]["count"] == 1


def test_update_candidates_infers_staff_role():
    items = [_item("https://a", "викладач НаУКМА Іван Сидоренко")]
    out = update_candidates({}, items, [])
    assert out["іван сидоренко"]["role"] == "staff"


def test_promote_threshold():
    cands = {
        "олена петренко": {"name": "Олена Петренко", "count": 2, "role": "student",
                           "evidence": ["https://a", "https://b"]},
        "іван сидоренко": {"name": "Іван Сидоренко", "count": 1, "role": "alumnus",
                           "evidence": ["https://c"]},
    }
    (p,) = promote(cands, threshold=2)
    assert p.id == "cand:олена-петренко"
    assert p.roles == ("student",)
    assert p.sources == ("https://a", "https://b")


# --- store -----------------------------------------------------------------------

def test_store_round_trip(tmp_path):
    people = [Person(id="wd:Q1", name_uk="Олена Петренко", aliases=("О. П.",),
                     roles=("alumnus",), socials=(("telegram", "olena"),), prominence=0.5)]
    edges = [Edge(a="wd:Q1", b="wd:Q2", kind="employer", weight=2.0, evidence=("u",))]
    store.save_people(people, tmp_path)
    store.save_graph(people, edges, tmp_path)
    store.save_candidates({"x": {"name": "X Y", "count": 1}}, tmp_path)
    assert store.load_people(tmp_path) == people
    assert store.load_edges(tmp_path) == edges
    assert store.load_candidates(tmp_path) == {"x": {"name": "X Y", "count": 1}}
    assert "Олена" in (tmp_path / "people.json").read_text(encoding="utf-8")


def test_store_missing_files_are_empty(tmp_path):
    assert store.load_people(tmp_path) == []
    assert store.load_edges(tmp_path) == []
    assert store.load_candidates(tmp_path) == {}


def test_store_corrupt_file_raises(tmp_path):
    (tmp_path / "people.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(store.StoreError, match="people.json"):
        store.load_people(tmp_path)


def test_merge_edges_accumulates_without_mutation():
    from mohyla.models import Edge
    from mohyla.people.graph import merge_edges
    old = [Edge(a="wd:Q2", b="wd:Q1", kind="comention", weight=1.0, evidence=("u1",))]
    new = [Edge(a="wd:Q1", b="wd:Q2", kind="comention", weight=2.0, evidence=("u2", "u1")),
           Edge(a="wd:Q1", b="wd:Q2", kind="employer")]
    out = merge_edges(old, new)
    co = [e for e in out if e.kind == "comention"]
    assert len(out) == 2 and co[0].weight == 3.0 and co[0].evidence == ("u1", "u2")
    assert old[0].a == "wd:Q2"  # input untouched
