"""Parse saved SPARQL JSON fixtures (no network)."""
import json
import math
from pathlib import Path

import pytest

from mohyla.models import Person
from mohyla.people import wikidata as wd
from mohyla.people.wikipedia import display_name, role_for_category

FIX = Path(__file__).parent / "fixtures" / "wikidata"
CFG = {"wikidata": {"orgs": ["Q1133013"], "exclude_dead": True, "min_birth_year": 1940}}


@pytest.fixture
def people() -> dict[str, Person]:
    core = wd.parse_core(json.loads((FIX / "core.json").read_text(encoding="utf-8")))
    details = wd.parse_details(json.loads((FIX / "details.json").read_text(encoding="utf-8")))
    return {p.id: p for p in wd.build_people(core, details, CFG)}


def test_parse_core_roles():
    core = wd.parse_core(json.loads((FIX / "core.json").read_text(encoding="utf-8")))
    assert core["Q100"] == ("alumnus", "staff")
    assert core["Q200"] == ("alumnus",)


def test_filters(people):
    assert set(people) == {"wd:Q100", "wd:Q200"}  # dead, pre-1940, non-human dropped


def test_full_record(people):
    p = people["wd:Q100"]
    assert p.name_uk == "Олександра Матвійчук"
    assert p.name_en == "Oleksandra Matviichuk"
    assert p.description == "українська правозахисниця"
    assert p.aliases == ("Матвійчук Олександра Вячеславівна",)
    assert p.roles == ("alumnus", "staff")
    assert p.employers == ("Q1133013", "Q4211")
    assert set(p.socials) == {("telegram", "matviichuk"), ("x", "avalaina"),
                              ("facebook", "oleksandra.matviichuk")}
    assert p.sources == ("https://www.wikidata.org/wiki/Q100",)
    assert p.prominence == pytest.approx(math.log1p(12) / math.log1p(60))


def test_english_fallback_and_zero_prominence(people):
    p = people["wd:Q200"]
    assert p.name_uk == "John Smith"
    assert p.prominence == 0.0
    assert p.socials == (("linkedin", "john-smith-123"),)


def test_keep_dead_when_not_excluded():
    cfg = {"wikidata": {"orgs": ["Q1"], "exclude_dead": False, "min_birth_year": 0}}
    core = {"Q300": ("staff",), "Q400": ("alumnus",)}
    details = wd.parse_details(json.loads((FIX / "details.json").read_text(encoding="utf-8")))
    assert {p.id for p in wd.build_people(core, details, cfg)} == {"wd:Q300", "wd:Q400"}


def test_queries_mention_orgs_and_batch():
    assert "wd:Q1133013" in wd.core_query(["Q1133013"])
    q = wd.detail_query(["Q1", "Q2"])
    assert "wd:Q1 wd:Q2" in q and "P3789" in q


def test_prominence_capped():
    assert wd.prominence(500) == 1.0
    assert wd.prominence(0) == 0.0


@pytest.mark.parametrize("title,name", [
    ("Грицак Ярослав Йосипович", "Ярослав Грицак"),
    ("Іванців Анастасія (журналістка)", "Іванців Анастасія"),
    ("Анастасія Іванців", "Анастасія Іванців"),
])
def test_wikipedia_display_name(title, name):
    assert display_name(title) == name


def test_wikipedia_role_for_category():
    assert role_for_category("Категорія:Науковці Києво-Могилянської академії") == "staff"
    assert role_for_category("Категорія:Випускники Києво-Могилянської бізнес-школи") == "alumnus"
