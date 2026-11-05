"""Import graduate lists from archived alumni.ukma.edu.ua / ukma.kiev.ua cohort pages.

The live site returns 403, so pages come from the Internet Archive (raw `id_` snapshots).
Each page is a sequence of headings and names: degree (Бакалаврат / Магістри / Спеціалісти),
faculty ("Факультет ..."), optional specialty, then "Прізвище Ім'я По-батькові" entries.
Output is personal data of private individuals: it is written to data/private/ (gitignored),
never to the public site or repository.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

import httpx

from mohyla.http import FetchError, fetch
from mohyla.models import ALUMNUS, Edge, Person
from mohyla.people.names import normalize

log = logging.getLogger(__name__)

WAYBACK = "https://web.archive.org/web/{ts}id_/{url}"
_LETTER = "а-яіїєґ'’`ʼ"
_FULL_NAME = re.compile(
    rf"^(?:\d+\.\s*)?([А-ЯІЇЄҐ][{_LETTER}-]+)\s+([А-ЯІЇЄҐ][{_LETTER}-]+)\s+"
    rf"([А-ЯІЇЄҐ][{_LETTER}]+(?:ович|евич|євич|ївна|івна|овна|ич|іч))$")
_DEGREES = {"бакалавр": "бакалавр", "магістр": "магістр", "спеціаліст": "спеціаліст"}
_SKIP = re.compile(r"^(\d+\.?|\d{4}|-->|.*:.*)$")  # numbering, years, TOC "Бакалаври: ..."


@dataclass(frozen=True)
class Graduate:
    surname: str
    first: str
    patronymic: str
    year: int
    degree: str = ""
    faculty: str = ""
    specialty: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.surname} {self.first} {self.patronymic}"


def _decode(raw: bytes) -> str:
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I)
    enc = m.group(1).decode().lower().replace("windows-", "cp") if m else "cp1251"
    try:
        return raw.decode(enc, "replace")
    except LookupError:
        return raw.decode("cp1251", "replace")


def text_chunks(raw: bytes) -> list[str]:
    """Visible text between tags, in document order, whitespace-collapsed."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>|<!--.*?-->", " ", _decode(raw))
    chunks = (re.sub(r"\s+", " ", html.unescape(c)).strip() for c in re.split(r"<[^>]+>", s))
    return [c for c in chunks if c]


def _degree(chunk: str) -> str | None:
    low = chunk.lower()
    if len(low) > 20:
        return None
    return next((v for k, v in _DEGREES.items() if low.startswith(k)), None)


def parse_cohort_page(raw: bytes, year: int) -> list[Graduate]:
    """Stateful walk: headings set context, full names become Graduate records."""
    degree = faculty = specialty = ""
    out: list[Graduate] = []
    for chunk in text_chunks(raw):
        if _SKIP.match(chunk):
            continue
        if (d := _degree(chunk)) is not None:
            degree, faculty, specialty = d, "", ""
        elif chunk.startswith(("Факультет", "Інститут", "Школа")) and len(chunk) < 90:
            faculty, specialty = chunk, ""
        elif m := _FULL_NAME.match(chunk):
            out.append(Graduate(*m.groups(), year=year, degree=degree,
                                faculty=faculty, specialty=specialty))
        elif faculty and len(chunk) < 80 and chunk[:1].isupper() and len(chunk.split()) <= 6:
            specialty = chunk
    return out


def archive_id(full_name: str) -> str:
    """Opaque id: public files (digests, graph) never carry full names with patronymics."""
    return "alumni:" + hashlib.sha256(normalize(full_name).encode()).hexdigest()[:12]


def _describe(grads: Sequence[Graduate]) -> str:
    parts = [f"{g.degree or 'випуск'} {g.year}" + (f", {g.faculty}" if g.faculty else "")
             for g in sorted(grads, key=lambda g: g.year)]
    return "Випускник(ця) НаУКМА: " + "; ".join(parts)


def to_people(grads: Iterable[Graduate], source: str) -> list[Person]:
    """One Person per full name (bachelor + master records of one person are merged)."""
    by_name: dict[str, list[Graduate]] = {}
    for g in grads:
        by_name.setdefault(normalize(g.full_name), []).append(g)
    people = []
    for key, gs in sorted(by_name.items()):
        g = gs[0]
        people.append(Person(
            id=archive_id(g.full_name),
            name_uk=f"{g.first} {g.surname}",
            aliases=(g.full_name,),
            roles=(ALUMNUS,),
            description=_describe(gs),
            sources=(source,),
            prominence=0.0,
        ))
    return people


def cohort(person: Person) -> tuple[str, ...]:
    """Cohort keys like '2003|Факультет економічних наук' parsed back from the description."""
    body = person.description.split(": ", 1)[-1]
    keys = []
    for part in body.split("; "):
        m = re.match(r"\S+ (\d{4})(?:, (.+))?$", part)
        if m:
            keys.append(f"{m.group(1)}|{m.group(2) or ''}")
    return tuple(keys)


def faculty_abbr(faculty: str) -> str:
    """'Факультет економічних наук' -> 'ФЕН' (conjunctions skipped)."""
    words = [w for w in re.split(r"[\s-]+", faculty) if w and w.lower() not in {"і", "та", "й"}]
    return "".join(w[0].upper() for w in words)


def cohort_label(person: Person) -> str:
    """Short chip text from cohort keys, e.g. 'ФЕН 2003, ФЕН 2005'."""
    labels = []
    for key in cohort(person):
        year, _, faculty = key.partition("|")
        labels.append(f"{faculty_abbr(faculty)} {year}".strip() if faculty else year)
    return ", ".join(dict.fromkeys(labels))


def fetch_archive(client: httpx.Client, pages: Sequence[dict], delay: float = 2.0) -> list[Graduate]:
    """Download each configured snapshot ({year, url, ts}) and parse it. Failures are logged."""
    grads: list[Graduate] = []
    for i, page in enumerate(pages):
        url = WAYBACK.format(ts=page["ts"], url=page["url"])
        try:
            raw = fetch(client, url).content
        except FetchError as exc:
            log.warning("archive %s failed: %s", page["year"], exc.reason)
            continue
        found = parse_cohort_page(raw, int(page["year"]))
        log.info("archive %s: %d graduates", page["year"], len(found))
        grads.extend(found)
        if i < len(pages) - 1:
            time.sleep(delay)
    return grads


def without_public(archived: Sequence[Person], public: Sequence[Person]) -> list[Person]:
    """Drop graduates already in the public base (the public one wins), matching by label
    and by aliases, e.g. a writer's legal name listed as an alias of their pen name."""
    names = {normalize(n) for p in public for n in (p.name_uk, *p.aliases) if n}
    return [p for p in archived
            if normalize(p.name_uk) not in names and not names & {normalize(a) for a in p.aliases}]


def cohort_edges(ids: Iterable[str], people_by_id: dict[str, Person]) -> list[Edge]:
    """Classmate edges (same year + faculty) among graduates that appeared in the news."""
    groups: dict[str, list[str]] = {}
    for pid in sorted(set(ids)):
        person = people_by_id.get(pid)
        for key in cohort(person) if person else ():
            groups.setdefault(key, []).append(pid)
    edges = []
    for key, members in sorted(groups.items()):
        for i, a in enumerate(members):
            edges.extend(Edge(a=a, b=b, kind="cohort", evidence=(key,)) for b in members[i + 1:])
    return edges
