"""Parser for archived cohort pages. Fixtures use invented names in the real page layouts."""
from mohyla.people.archive import cohort, cohort_label, faculty_abbr, parse_cohort_page, to_people

OLD_LAYOUT = """<html><head><meta charset="windows-1251"><script>var ie=1;</script></head><body>
Шлях: / випускники / 2003 <b>2003</b><h2>Бакалаврат</h2><h3>Факультет гуманітарних наук</h3>
<p>Тестенко В'ячеслав Валерійович</p><p>Пробна Юлія Віталіївна</p>
<h2>Магістратура</h2><h3>Факультет економічних наук</h3><p>Тестенко В'ячеслав Валерійович</p>
</body></html>""".encode("cp1251")

NEW_LAYOUT = """<html><meta charset="windows-1251"><body>
<a>Бакалаври: Факультет інформатики</a><a>Магістри: Факультет інформатики</a>
<td>Бакалаври</td><td>Факультет інформатики</td><td>Програмна інженерія</td>
<td>1.</td><td>Зразковий Максим Ігорович</td><td>2.</td><td>Макетна Інна Олександрівна</td>
</body></html>""".encode("cp1251")


def test_old_layout_degree_faculty_and_apostrophe():
    grads = parse_cohort_page(OLD_LAYOUT, 2003)
    assert [(g.first, g.degree, g.faculty) for g in grads] == [
        ("В'ячеслав", "бакалавр", "Факультет гуманітарних наук"),
        ("Юлія", "бакалавр", "Факультет гуманітарних наук"),
        ("В'ячеслав", "магістр", "Факультет економічних наук"),
    ]


def test_new_layout_skips_toc_and_numbering_and_reads_specialty():
    grads = parse_cohort_page(NEW_LAYOUT, 2018)
    assert [g.full_name for g in grads] == ["Зразковий Максим Ігорович", "Макетна Інна Олександрівна"]
    assert grads[0].specialty == "Програмна інженерія" and grads[0].degree == "бакалавр"


def test_to_people_merges_degrees_of_one_person():
    people = to_people(parse_cohort_page(OLD_LAYOUT, 2003), source="wayback")
    v = next(p for p in people if p.name_uk == "В'ячеслав Тестенко")
    assert v.prominence == 0.0 and v.aliases == ("Тестенко В'ячеслав Валерійович",)
    assert cohort(v) == ("2003|Факультет гуманітарних наук", "2003|Факультет економічних наук")
    assert len(people) == 2


def test_ids_are_opaque_and_labels_short():
    people = to_people(parse_cohort_page(OLD_LAYOUT, 2003), source="wayback")
    v = next(p for p in people if p.name_uk == "В'ячеслав Тестенко")
    assert v.id.startswith("alumni:") and "тестенко" not in v.id.lower()
    assert cohort_label(v) == "ФГН 2003, ФЕН 2003"
    assert faculty_abbr("Факультет соціальних наук і соціальних технологій") == "ФСНСТ"


def test_cohort_edges_and_chip():
    from mohyla.digest import _person_chip
    from mohyla.people.archive import cohort_edges, without_public
    from mohyla.models import Person
    people = to_people(parse_cohort_page(OLD_LAYOUT, 2003), source="wayback")
    by_id = {p.id: p for p in people}
    edges = cohort_edges(by_id, by_id)
    assert [(e.kind, e.evidence) for e in edges] == [("cohort", ("2003|Факультет гуманітарних наук",))]
    chip = _person_chip(people[0])
    assert "2003" in chip and "alumni:" not in chip
    public = [Person(id="wd:Q1", name_uk="Юлія Пробна")]
    assert [p.name_uk for p in without_public(people, public)] == ["В'ячеслав Тестенко"]


def test_without_public_matches_legal_name_alias():
    from mohyla.models import Person
    from mohyla.people.archive import without_public
    people = to_people(parse_cohort_page(OLD_LAYOUT, 2003), source="wayback")
    pen_name = Person(id="wd:Q2", name_uk="Псевдо Автор", aliases=("Тестенко В'ячеслав Валерійович",))
    assert [p.name_uk for p in without_public(people, [pen_name])] == ["Юлія Пробна"]
