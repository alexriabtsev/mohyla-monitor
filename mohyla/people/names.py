"""Name normalization, declension-tolerant name patterns, snowball name extraction.

Ukrainian names decline (Олександра -> Олександрі/Олександру/Олександрою), so a
person's pattern is built from stems: word minus a common inflection ending,
followed by up to 3 word characters. Both first-name and surname stems are
required, so "Олена" alone never matches "Олена Петренко".
"""
from __future__ import annotations

import logging
import re

from mohyla.models import Person

log = logging.getLogger(__name__)

APOSTROPHES = "'’ʼ`‘"
_APOS_CLASS = "['’ʼ`‘]"
_APOS_RE = re.compile(f"[{APOSTROPHES}]")
_CYRILLIC_RE = re.compile(r"[а-яіїєґё]", re.IGNORECASE)
_EDGE_PUNCT_RE = re.compile(r"^[^\w']+|[^\w']+$")
_PAREN_RE = re.compile(r"\s*\([^)]*\)")

# Longest first; "ий" covers adjectival surnames (Грушевський -> Грушевськ-ого).
_ENDINGS = ("ий", "а", "я", "о", "е", "є", "і", "и", "ь", "й", "у", "ю")
_MIN_STEM = 3
# closed set of case endings: "Мороз" must not match "Морозов", "Коваль" not "Ковальов"
_SUFFIX = (r"(?:ого|ому|ові|еві|єві|ою|ею|єю|ої|ій|ім|им|ом|ем|єм|ую|юю|ий"
           r"|а|я|у|ю|і|ї|е|є|о|и|ь|й)?")
_PATRONYMIC_RE = re.compile(r"(?:ович|евич|євич|івн|ївн|овн)\w{0,3}$", re.IGNORECASE)
_PATRONYMIC_PART = rf"(?:\s+[\w{APOSTROPHES}]+(?:ович|евич|євич|івн|ївн|овн)\w{{0,3}})?"


def normalize(s: str) -> str:
    """Lowercase, unify apostrophes, ё->е, collapse whitespace, strip edge punctuation."""
    out = _APOS_RE.sub("'", s.lower()).replace("ё", "е")
    out = " ".join(out.split())
    return _EDGE_PUNCT_RE.sub("", out)


def is_patronymic(token: str) -> bool:
    return bool(_PATRONYMIC_RE.search(token))


# Possible first Latin letters of a transliterated Cyrillic initial.
_LATIN_INITIALS = {
    "а": "a", "б": "b", "в": "vw", "г": "hg", "ґ": "g", "д": "d", "е": "e", "є": "yie",
    "ж": "zj", "з": "z", "и": "yi", "і": "i", "ї": "yi", "й": "yij", "к": "kc", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "khc", "ц": "tc", "ч": "c", "ш": "s", "щ": "s", "ю": "yij", "я": "yij",
}


def _initial_fits(uk_word: str, en_word: str) -> bool:
    return en_word[:1].lower() in _LATIN_INITIALS.get(uk_word[:1].lower(), "") if en_word else False


def _looks_reversed(uk: list[str], name_en: str) -> bool:
    """True when 'X Y' (uk) corresponds to 'Y X' in the English label by initials."""
    en = name_en.split()
    if len(en) < 2:
        return False
    swapped = _initial_fits(uk[1], en[0]) and _initial_fits(uk[0], en[-1])
    straight = _initial_fits(uk[0], en[0]) and _initial_fits(uk[1], en[-1])
    return swapped and not straight


def canonical_name(name: str, name_en: str = "") -> str:
    """Best-effort 'Ім'я Прізвище' from 'Прізвище Ім'я По-батькові' and similar forms."""
    tokens = _PAREN_RE.sub("", name).split()
    if len(tokens) == 3 and is_patronymic(tokens[2]):
        return f"{tokens[1]} {tokens[0]}"
    if len(tokens) == 3 and is_patronymic(tokens[1]):
        return f"{tokens[0]} {tokens[2]}"
    if len(tokens) == 2 and _looks_reversed(tokens, name_en):
        return f"{tokens[1]} {tokens[0]}"
    return " ".join(tokens)


def _name_tokens(name: str) -> list[str]:
    """Normalized tokens of a name with parentheticals and patronymics dropped."""
    tokens = normalize(_PAREN_RE.sub("", name)).split()
    tokens = [t.strip(".,;:«»\"") for t in tokens]
    tokens = [t for t in tokens if t]
    if len(tokens) >= 3:
        tokens = [tokens[0]] + [t for t in tokens[1:-1] if not is_patronymic(t)] + [tokens[-1]]
        if is_patronymic(tokens[-1]) and len(tokens) >= 3:
            tokens = tokens[:-1]
    return tokens


def _stem(word: str) -> str:
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= _MIN_STEM:
            return word[: -len(ending)]
    return word


def _word_regex(word: str) -> str:
    """Regex for one (normalized) name word, declension-tolerant for Cyrillic."""
    head, _, last = word.rpartition("-")
    prefix = f"{re.escape(head)}-" if head else ""
    if not _CYRILLIC_RE.search(last) or len(last) < _MIN_STEM:
        body = re.escape(last)
    else:
        stem = _stem(last)
        body = re.escape(stem) + _SUFFIX
    return (prefix + body).replace("'", _APOS_CLASS)


def _variant_regex(name: str) -> str | None:
    tokens = _name_tokens(name)
    if len(tokens) < 2:
        return None
    first, last = _word_regex(tokens[0]), _word_regex(tokens[-1])
    forward = rf"{first}{_PATRONYMIC_PART}\s+{last}"
    backward = rf"{last},?\s+{first}"
    return rf"(?<!\w)(?:{forward}|{backward})(?!\w)"


def name_pattern(person: Person) -> re.Pattern | None:
    """Case-insensitive regex for the person's name in running text, or None."""
    variants: list[str] = []
    seen: set[str] = set()
    for name in (person.name_uk, person.name_en, *person.aliases):
        if not name or normalize(name) in seen:
            continue
        seen.add(normalize(name))
        rx = _variant_regex(name)
        if rx and rx not in variants:
            variants.append(rx)
    if not variants:
        return None
    return re.compile("|".join(variants), re.IGNORECASE)


# --- snowball extraction ------------------------------------------------------

_UK_TOKEN = rf"[А-ЯІЇЄҐ][а-яіїєґ{APOSTROPHES}]+(?:-[А-ЯІЇЄҐ][а-яіїєґ{APOSTROPHES}]+)?"
_EN_TOKEN = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?"
_UK_NAME = rf"(?P<name>{_UK_TOKEN}(?:\s+{_UK_TOKEN}){{1,2}})(?![\w{APOSTROPHES}])"
_EN_NAME = r"(?P<name>" + _EN_TOKEN + r"(?:\s+" + _EN_TOKEN + r"){1,2})(?![\w'])"
_UK_LOWER = rf"[а-яіїєґ{APOSTROPHES}-]+"

_UK_ROLE = (r"(?P<role>(?i:(?:екс-|колишн\w*\s+)?(?:випускни\w*|викладач\w*|професор\w*"
            r"|доцент\w*|науков(?:ець|иц|ц)\w*|дослідни\w*|співробітни\w*|проректор\w*"
            r"|ректор\w*|декан\w*|студент\w*|аспірант\w*|магістрант\w*|докторант\w*)))")
_UK_MARKER = (r"(?i:Національн\w*\s+університет\w*\s+[«\"]?Києво-Могилянськ\w*\s+академі\w*[»\"]?"
              r"|Києво-Могилянськ\w*\s+(?:академі\w*|бізнес-школ\w*)|Могилянк\w*"
              r"|НаУКМА|УКМА|kmbs)(?!\w)")
_EN_ROLE = (r"(?P<role>(?i:graduate|alumn(?:us|a|ae|i)|professor|lecturer|student|researcher"
            r"|scholar|faculty\s+member))")
_EN_MARKER = (r"(?i:(?:the\s+)?(?:National\s+University\s+of\s+)?Kyiv[-\s]Mohyla"
              r"(?:\s+(?:Academy|Business\s+School))?|NaUKMA|KMBS)(?!\w)")

_SNOWBALL_PATTERNS: tuple[tuple[re.Pattern, bool], ...] = tuple(
    (re.compile(rx), name_first) for rx, name_first in (
        (rf"(?<!\w){_UK_ROLE}(?:\s+{_UK_LOWER}){{0,3}}?\s+{_UK_MARKER},?\s+{_UK_NAME}", False),
        (rf"(?<![\w{APOSTROPHES}]){_UK_NAME},\s+{_UK_ROLE}(?:\s+{_UK_LOWER}){{0,3}}?\s+{_UK_MARKER}", True),
        (rf"(?<!\w){_EN_MARKER}\s+{_EN_ROLE}\s+{_EN_NAME}", False),
        (rf"(?<![\w']){_EN_NAME},\s+(?:(?i:an?|the)\s+)?(?:(?i:former)\s+)?"
         rf"(?:{_EN_MARKER}\s+{_EN_ROLE}|{_EN_ROLE.replace('<role>', '<role2>')}"
         rf"\s+(?i:of|at|from)\s+{_EN_MARKER})", True),
    )
)

# Capitalized words that are places/institutions, not personal names.
_STOP_PREFIXES = ("київ", "києв", "україн", "львів", "харків", "одес", "академ",
                  "університет", "могилян", "наукма", "національн", "kyiv", "ukrain",
                  "mohyla", "academy", "university", "national", "the ")

_STUDENT_PREFIXES = ("студент", "аспірант", "магістрант", "докторант", "student")
_ALUMNUS_PREFIXES = ("випускни", "graduate", "alumn")


def _role_from_word(word: str) -> str:
    w = normalize(word)
    w = re.sub(r"^(?:екс-|колишн\w*\s+)", "", w)
    if w.startswith(_STUDENT_PREFIXES):
        return "student"
    if w.startswith(_ALUMNUS_PREFIXES):
        return "alumnus"
    return "staff"


def _canonical(name: str, name_first: bool) -> str | None:
    tokens = _APOS_RE.sub("'", name).split()
    if any(normalize(t).startswith(_STOP_PREFIXES) for t in tokens):
        return None
    if len(tokens) == 3:
        if is_patronymic(tokens[1]):
            tokens = [tokens[0], tokens[2]]
        else:
            # Name before a comma may carry a leading sentence word; after a marker,
            # trailing capitalized words are more likely the noise.
            tokens = tokens[1:] if name_first else tokens[:2]
    return " ".join(tokens)


def extract_snowball_mentions(text: str) -> list[tuple[str, str]]:
    """(name, role) pairs the text explicitly introduces as Mohyla people."""
    found: dict[str, str] = {}
    for pattern, name_first in _SNOWBALL_PATTERNS:
        for m in pattern.finditer(text):
            name = _canonical(m.group("name"), name_first)
            if name and name not in found:
                role_word = m.group("role") or m.groupdict().get("role2") or ""
                found[name] = _role_from_word(role_word)
    return list(found.items())


def extract_snowball_names(text: str) -> list[str]:
    """Names explicitly introduced as Mohyla alumni/staff/students, deduplicated."""
    return [name for name, _ in extract_snowball_mentions(text)]
