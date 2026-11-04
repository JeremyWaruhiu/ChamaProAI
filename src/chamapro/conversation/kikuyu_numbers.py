"""Kikuyu numbers: to_words(n) and parse(text), for 0 to 999,999.

FOR NATIVE-SPEAKER REVIEW. None of this has been checked by a Kikuyu speaker. Correct
it in the tables below; everything else follows from them.

    Given in the brief (assumed):
        1 ĩmwe          2 igĩrĩ         3 ithatũ        4 inya          5 ithano
        6 ithathatũ     7 mũgwanja      8 inyanya       9 kenda        10 ikũmi
       20 mĩrongo ĩĩrĩ 30 mĩrongo ĩtatũ 40 mĩrongo ĩna  50 mĩrongo ĩtano
       60 mĩrongo ĩtandatũ              70 mĩrongo mũgwanja
       80 mĩrongo ĩnana                 90 mĩrongo kenda
      100 igana        hundreds: magana
     1000 ngiri        e.g. ngiri ithano = 5,000, ngiri mĩrongo ĩna = 40,000

    Added by the author, to complete the range; the brief does not give them:
        0 gũtirĩ
      200 to 900 with the agreement of magana: magana meerĩ, matatũ, mana, matano,
        matandatũ, mũgwanja, manana, kenda
      "na" (and) between the parts: 15 = ikũmi na ithano, 150 = igana na mĩrongo ĩtano
      a comma before what follows the thousands, which is also a pause when spoken:
        45,000 = ngiri mĩrongo ĩna na ithano, but 40,005 = ngiri mĩrongo ĩna, na ithano.
        With no comma, as ASR may write it, the rest is read as part of the thousands,
        the likelier amount for a loan
      VARIANTS: spellings the author expects from ASR and from typing, not ones observed

A noun's class can change these words in a real sentence (ng'ombe igĩrĩ, but andũ eerĩ).
to_words gives the counting form, in the form a template's {amount} slot needs.
"""
from __future__ import annotations

import re
import unicodedata

UNITS = {1: "ĩmwe", 2: "igĩrĩ", 3: "ithatũ", 4: "inya", 5: "ithano", 6: "ithathatũ", 7: "mũgwanja", 8: "inyanya",
         9: "kenda"}
ZERO = "gũtirĩ"
TEN = "ikũmi"
TENS_WORD = "mĩrongo"
TENS = {2: "ĩĩrĩ", 3: "ĩtatũ", 4: "ĩna", 5: "ĩtano", 6: "ĩtandatũ", 7: "mũgwanja", 8: "ĩnana", 9: "kenda"}
HUNDRED = "igana"
HUNDREDS_WORD = "magana"
HUNDREDS = {2: "meerĩ", 3: "matatũ", 4: "mana", 5: "matano", 6: "matandatũ", 7: "mũgwanja", 8: "manana", 9: "kenda"}
THOUSAND = "ngiri"
AND = "na"
# Other ways to write a word, without tildes: spelling -> the word it stands for, also without.
VARIANTS = {
    "emwe": "imwe", "umwe": "imwe", "igeri": "igiri", "egiri": "igiri", "ithatu": "ithatu", "ithato": "ithatu",
    "enya": "inya", "inia": "inya", "ithanu": "ithano", "ethano": "ithano", "ithathatu": "ithathatu",
    "thathatu": "ithathatu", "ithathato": "ithathatu", "mogwanja": "mugwanja", "mugwania": "mugwanja",
    "inyania": "inyanya", "nyanya": "inyanya", "kienda": "kenda", "ikomi": "ikumi", "ikumu": "ikumi", "ikumii": "ikumi",
    "mirongu": "mirongo", "morongo": "mirongo", "miringo": "mirongo", "mirong'o": "mirongo", "iri": "iiri", "yiri": "iiri",
    "eeri": "iiri", "itato": "itatu", "itatho": "itatu", "inna": "ina", "yina": "ina", "itanu": "itano",
    "itandato": "itandatu", "inanna": "inana", "ikana": "igana", "igaana": "igana", "makana": "magana", "magaana": "magana",
    "meri": "meeri", "merii": "meeri", "ngeri": "ngiri", "ngili": "ngiri", "ngirii": "ngiri", "ngiiri": "ngiri",
    "n'giri": "ngiri", "gutiri": "gutiri", "gutire": "gutiri",
}


def plain(text: str) -> str:
    """Lower case, no tildes or other marks; apostrophes straightened."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).replace("’", "'").replace("`", "'")


def _key(word: str) -> str:
    return plain(word)


_BARE = {_key(w): n for n, w in UNITS.items()}
# After mĩrongo or magana: their own forms, or a counting form from someone less careful.
_AGREEING = {**_BARE, **{_key(w): n for n, w in TENS.items()}, **{_key(w): n for n, w in HUNDREDS.items()}}
_TEN, _TENS_WORD, _HUNDRED, _HUNDREDS_WORD = map(_key, (TEN, TENS_WORD, HUNDRED, HUNDREDS_WORD))
_THOUSAND, _ZERO = _key(THOUSAND), _key(ZERO)
TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?|,")


def tokens(text: str) -> list[str]:
    return [VARIANTS.get(t, t) for t in TOKEN.findall(plain(text))]


def unit_value(word: str) -> int | None:
    """A single word's value in any agreement: for "miaka ĩĩrĩ" (two years) and the like."""
    return _AGREEING.get(VARIANTS.get(plain(word), plain(word)))


# --- Words ------------------------------------------------------------------------------

def _below_thousand(n: int) -> str:
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(HUNDRED if hundreds == 1 else f"{HUNDREDS_WORD} {HUNDREDS[hundreds]}")
    tens, units = divmod(rest, 10)
    if tens:
        parts.append(TEN if tens == 1 else f"{TENS_WORD} {TENS[tens]}")
    if units:
        parts.append(UNITS[units])
    return f" {AND} ".join(parts)


def to_words(n: int) -> str:
    if not 0 <= n <= 999_999:
        raise ValueError(f"{n} is outside 0 to 999,999")
    if n == 0:
        return ZERO
    thousands, rest = divmod(n, 1000)
    if not thousands:
        return _below_thousand(rest)
    head = f"{THOUSAND} {_below_thousand(thousands)}"
    return f"{head}, {AND} {_below_thousand(rest)}" if rest else head


# --- Parsing ----------------------------------------------------------------------------

def _hundreds(t: list[str], i: int) -> tuple[int, int] | None:
    if i < len(t) and t[i] == _HUNDRED:
        return 100, i + 2 if i + 1 < len(t) and t[i + 1] == _key(UNITS[1]) else i + 1
    if i + 1 < len(t) and t[i] == _HUNDREDS_WORD and t[i + 1] in _AGREEING and _AGREEING[t[i + 1]] > 1:
        return _AGREEING[t[i + 1]] * 100, i + 2
    return None


def _tens(t: list[str], i: int) -> tuple[int, int] | None:
    if i < len(t) and t[i] == _TEN:
        return 10, i + 1
    if i + 1 < len(t) and t[i] == _TENS_WORD and t[i + 1] in _AGREEING and _AGREEING[t[i + 1]] > 1:
        return _AGREEING[t[i + 1]] * 10, i + 2
    return None


def _units(t: list[str], i: int) -> tuple[int, int] | None:
    return (_BARE[t[i]], i + 1) if i < len(t) and t[i] in _BARE else None


def _next_part(t: list[str], i: int, reader) -> tuple[int, int] | None:
    """A lower part after a higher one, with or without "na"."""
    if i < len(t) and t[i] == AND:
        return reader(t, i + 1)
    return reader(t, i)


def _below_thousand_at(t: list[str], i: int) -> tuple[int, int] | None:
    """Hundreds, tens and units, largest first, each part optional, as long as there is one."""
    value, at, found = 0, i, False
    for reader in (_hundreds, _tens, _units):
        got = _next_part(t, at, reader) if found else reader(t, at)
        if got is not None:
            value, at, found = value + got[0], got[1], True
    return (value, at) if found else None


def _number_at(t: list[str], i: int) -> tuple[int, int] | None:
    if t[i] == _ZERO:
        return 0, i + 1
    if t[i] != _THOUSAND:
        return _below_thousand_at(t, i)
    count = _below_thousand_at(t, i + 1)
    value, at = ((count[0] or 1) * 1000, count[1]) if count else (1000, i + 1)
    if at < len(t) and t[at] == ",":
        at += 1
    rest = _next_part(t, at, _below_thousand_at)
    return (value + rest[0], rest[1]) if rest else (value, at)


def parse(text: str) -> int | None:
    """The largest number written in the text, or None. "Ngũkwenda ngiri mĩrongo ĩna
    ngũre ng'ombe igĩrĩ" is 40,000: the two cows are a smaller number."""
    t, i, found = tokens(text), 0, []
    while i < len(t):
        got = _number_at(t, i) if t[i] != "," else None
        if got is None:
            i += 1
        else:
            found.append(got[0])
            i = got[1]
    return max(found) if found else None
