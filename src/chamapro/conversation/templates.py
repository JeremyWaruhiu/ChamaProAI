"""Every word the bot says comes from templates.yaml, by id, with its slots filled in;
the language model writes none of it. A turn is rendered three ways: what is shown, the
English of it for the record and for the officer, and what is read aloud, in which every
number is words."""
from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from chamapro import config

from . import english_numbers, kikuyu_numbers

PATH = Path(__file__).with_name("templates.yaml")
NUMERIC_SLOTS = {"amount", "monthly_income", "capacity", "max_amount", "instalment", "term", "household_size", "children",
                 "months", "min_guarantors"}
LANGUAGES = ("en", "kik")


class TemplateError(ValueError):
    """templates.yaml cannot be used as it stands."""


@dataclass(frozen=True)
class Rendered:
    template_id: str
    text: str           # what is shown
    text_en: str
    spoken: str         # what is read aloud
    voice: str          # en | kik
    kik_pending: bool


def slots_of(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def check(entries: dict) -> dict:
    """Refuse at load rather than in front of a member: a missing language, or a Kikuyu
    entry asking for a slot the English one does not fill."""
    for tid, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != set(LANGUAGES):
            raise TemplateError(f"{tid}: needs exactly {' and '.join(LANGUAGES)}")
        if not entry["en"]:
            raise TemplateError(f"{tid}: the English text is empty")
        unknown = slots_of(entry["kik"] or "") - slots_of(entry["en"])
        if unknown:
            raise TemplateError(f"{tid}: the kik text uses {', '.join(sorted(unknown))}, which the en text does not")
    return entries


@lru_cache(maxsize=1)
def load(path: Path = PATH) -> dict:
    return check(yaml.safe_load(path.read_text(encoding="utf-8")))


def kikuyu_number(n: int) -> str:
    try:
        return kikuyu_numbers.to_words(n)
    except ValueError:
        return f"{n:,}"     # beyond the words we have: a figure, not a wrong number


def _values(slots: dict, number) -> dict:
    return {k: number(v) if k in NUMERIC_SLOTS else v for k, v in slots.items()}


def render(template_id: str, language: str, **slots) -> Rendered:
    entry = load()[template_id]
    text_en = entry["en"].format(**_values(slots, lambda n: f"{n:,}"))
    if language == "kik" and entry["kik"]:
        text = entry["kik"].format(**_values(slots, kikuyu_number))
        return Rendered(template_id, text, text_en, text, "kik", False)
    return Rendered(template_id, text_en, text_en, entry["en"].format(**_values(slots, english_numbers.to_words)), "en",
                    language == "kik")


def text_of(template_id: str, language: str = "en") -> str:
    """The wording with no slots to fill."""
    return render(template_id, language).text


def consent_version() -> str:
    """Names the exact wording, in every language, that a consent was given to."""
    entry = load()["CONSENT"]
    return "consent-" + hashlib.sha256(f"{entry['en']}\0{entry['kik']}".encode()).hexdigest()[:12]


def fixed_lines() -> list[Rendered]:
    """Every rendering that does not depend on the member or the loan, for the cache."""
    out = {}
    for tid, entry in load().items():
        if slots_of(entry["en"]) <= {"sacco_name"}:
            for language in LANGUAGES:
                r = render(tid, language, sacco_name=config.SACCO_NAME)
                out[(r.voice, r.spoken)] = r
    return list(out.values())
