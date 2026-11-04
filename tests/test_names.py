"""Tests for mohyla.people.names: normalization, declension-aware patterns, snowball."""
import pytest

from mohyla.models import Person
from mohyla.people.names import (
    canonical_name,
    extract_snowball_mentions,
    extract_snowball_names,
    name_pattern,
    normalize,
)


def _p(name_uk: str, name_en: str = "", aliases: tuple[str, ...] = ()) -> Person:
    return Person(id="wd:Q1", name_uk=name_uk, name_en=name_en, aliases=aliases)


# --- normalize ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("  Мар’яна   Петренко ", "мар'яна петренко"),
    ("Марʼяна", "мар'яна"),
    ("Мар`яна", "мар'яна"),
    ("Алёна", "алена"),
    ("«Олена Петренко»,", "олена петренко"),
    ("John\tSmith.", "john smith"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("label,en,expected", [
    ("Буданов Кирило Олексійович", "Kyrylo Budanov", "Кирило Буданов"),
    ("Олексій Валерійович Гончарук", "Olexii Honcharuk", "Олексій Гончарук"),
    ("Бураковський Ігор", "Ihor Burakovsʹkyĭ", "Ігор Бураковський"),
    ("Ігор Бураковський", "Ihor Burakovskyi", "Ігор Бураковський"),
    ("Іванців Анастасія (журналістка)", "", "Іванців Анастасія"),
    ("Мадонна", "", "Мадонна"),
])
def test_canonical_name(label, en, expected):
    assert canonical_name(label, en) == expected


# --- name_pattern: positives ---------------------------------------------------

@pytest.mark.parametrize("text", [
    "Олександра Матвійчук отримала премію",
    "премію вручили Олександрі Матвійчук",
    "інтерв'ю з Олександрою Матвійчук",
    "Матвійчук Олександра заявила",
    "OLEKSANDRA MATVIICHUK spoke",
    "Oleksandra Matviichuk's speech",
])
def test_feminine_declensions(text):
    pat = name_pattern(_p("Олександра Матвійчук", "Oleksandra Matviichuk"))
    assert pat is not None and pat.search(text), text


@pytest.mark.parametrize("text", [
    "Ярослав Грицак виступив",
    "лекція Ярослава Грицака",
    "розмова з Ярославом Грицаком",
    "Ярославові Грицакові вручили",
    "Грицак Ярослав Йосипович",
    "Ярослав Йосипович Грицак",
])
def test_masculine_declensions(text):
    pat = name_pattern(_p("Ярослав Грицак"))
    assert pat.search(text), text


@pytest.mark.parametrize("text", [
    "Михайло Грушевський",
    "праці Михайла Грушевського",
    "з Михайлом Грушевським",
])
def test_adjectival_surname_masculine(text):
    assert name_pattern(_p("Михайло Грушевський")).search(text), text


@pytest.mark.parametrize("text", [
    "Олена Зеленська",
    "Олени Зеленської",
    "Олені Зеленській",
    "з Оленою Зеленською",
])
def test_adjectival_surname_feminine(text):
    assert name_pattern(_p("Олена Зеленська")).search(text), text


def test_apostrophe_variants_in_name():
    pat = name_pattern(_p("Мар'яна Кияновська"))
    assert pat.search("Мар’яна Кияновська")
    assert pat.search("Марʼяною Кияновською")


def test_alias_matches():
    pat = name_pattern(_p("Святослав Вакарчук", aliases=("Славко Вакарчук",)))
    assert pat.search("концерт Славка Вакарчука")


def test_english_name_matches():
    pat = name_pattern(_p("Тимофій Милованов", "Tymofiy Mylovanov"))
    assert pat.search("Tymofiy Mylovanov said")


# --- name_pattern: negatives --------------------------------------------------

def test_first_name_alone_does_not_match():
    pat = name_pattern(_p("Олена Петренко"))
    assert not pat.search("Олена сказала, що прийде")


def test_surname_alone_does_not_match():
    pat = name_pattern(_p("Олена Петренко"))
    assert not pat.search("пан Петренко сказав")


def test_different_surname_does_not_match():
    pat = name_pattern(_p("Олена Петренко"))
    assert not pat.search("Олена Петрук виступила")
    assert not pat.search("Олена Коваленко виступила")


def test_word_inside_longer_word_does_not_match():
    pat = name_pattern(_p("Іван Сидоренко"))
    assert not pat.search("Степаніван Сидоренко")


def test_single_token_returns_none():
    assert name_pattern(_p("Мадонна")) is None


def test_short_stem_keeps_full_word():
    pat = name_pattern(_p("Ян Ко"))
    assert pat.search("Ян Ко")
    assert not pat.search("Яна Коваль")


# --- snowball extraction -------------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ("Сьогодні випускниця Могилянки Олена Петренко отримала нагороду.", "Олена Петренко"),
    ("Олена Петренко, випускник НаУКМА, розповіла про проєкт.", "Олена Петренко"),
    ("викладач Києво-Могилянської академії Іван Сидоренко", "Іван Сидоренко"),
    ("студентка НаУКМА Марія Коваль перемогла", "Марія Коваль"),
    ("Kyiv-Mohyla Academy graduate John Smith won", "John Smith"),
    ("John Smith, a NaUKMA alumnus, said", "John Smith"),
    ("випускник Могилянки Мар’ян Гнатюк-Ковальчук", "Мар'ян Гнатюк-Ковальчук"),
    ("випускниця Могилянки Олена Іванівна Петренко", "Олена Петренко"),
    ("Олена Петренко, викладачка кафедри історії НаУКМА, заявила", "Олена Петренко"),
])
def test_snowball_positive(text, name):
    assert name in extract_snowball_names(text)


@pytest.mark.parametrize("text", [
    "У Могилянки Києва новий корпус.",
    "Випускники Могилянки зібралися у Києві.",
    "Могилянка Олена Петренко",          # no role word
    "випускниця Могилянки олена петренко",  # not capitalized
    "Олена Петренко сказала, що НаУКМА важлива",
    "випускниця Могилянки Київ Україна",
])
def test_snowball_negative(text):
    assert extract_snowball_names(text) == []


def test_snowball_role_inference():
    mentions = dict(extract_snowball_mentions(
        "викладач НаУКМА Іван Сидоренко і студентка НаУКМА Марія Коваль"))
    assert mentions["Іван Сидоренко"] == "staff"
    assert mentions["Марія Коваль"] == "student"


def test_snowball_dedupes():
    text = "випускниця Могилянки Олена Петренко. Олена Петренко, випускниця НаУКМА"
    assert extract_snowball_names(text) == ["Олена Петренко"]
