"""Words the deterministic backstops know: yes and no, and a few purposes in Kikuyu.

FOR NATIVE-SPEAKER REVIEW, like kikuyu_numbers.py. The brief gives ii/ĩĩ, aca, ni guo and
ti guo; the other Kikuyu spellings here, and KIKUYU_PURPOSES, are the author's assumptions.
"""
from __future__ import annotations

import re

from .kikuyu_numbers import plain

EN_NEGATED = re.compile(r"\b(not|isn t|isnt|don t|dont|do not|never)\s+(correct|right|true|okay|ok|agree|sure|fine)\b")
EN_YES_PHRASES = re.compile(r"\b(go ahead|no problem|that is right|thats right|please do)\b")
EN_YES = {"yes", "yeah", "yep", "yea", "correct", "right", "sure", "ok", "okay", "agree", "true", "fine", "proceed",
          "absolutely", "definitely"}
EN_NO = {"no", "nope", "nah", "not", "never", "incorrect", "wrong", "disagree", "cancel", "stop"}
KIK_YES_PHRASES = re.compile(r"\b(ni guo|niguo|ni uguo|ni wega|ni kuo)\b")
KIK_NO_PHRASES = re.compile(r"\b(ti guo|tiguo|ti uguo|ti kuo)\b")
KIK_YES = {"ii", "iii", "iih", "ee", "eeh"}
KIK_NO = {"aca", "acha", "aaca"}
# English the speaker may use whatever the language: "no" alone only, because the same
# letters are a Kikuyu word (no, "but") that begins other sentences.
EN_IN_KIK_YES = {"yes", "yeah", "ok", "okay", "correct", "sure"}
KIKUYU_PURPOSES = {"ng'ombe": "cow", "ngombe": "cow", "mburi": "goat", "ngoima": "sheep", "nguku": "chicken",
                   "cukuru": "school fees", "thukuru": "school fees", "mugunda": "farm", "biashara": "business",
                   "duka": "shop", "nyumba": "house", "thibitari": "medical bills"}
NOBODY_EN = re.compile(r"\b(no one|nobody|none|no body|nothing)\b")
NOBODY_KIK = re.compile(r"\b(gutiri|hatiri|hakuna|ndiri)\b")


def _words(text: str) -> str:
    return re.sub(r"[^a-z' ]+", " ", plain(text)).replace("'", " ").strip()


def _decide(says_yes: bool, says_no: bool) -> str | None:
    return None if says_yes == says_no else ("yes" if says_yes else "no")


def yes_no(text: str, language: str) -> str | None:
    """"yes", "no", or None when it says neither or both."""
    words = _words(text)
    tokens = set(words.split())
    if language == "kik":
        says_no = bool(KIK_NO_PHRASES.search(words)) or bool(tokens & KIK_NO) or words == "no"
        says_yes = bool(KIK_YES_PHRASES.search(words)) or bool(tokens & KIK_YES) or bool(tokens & EN_IN_KIK_YES)
        return _decide(says_yes, says_no)
    if EN_NEGATED.search(words):
        return "no"
    if EN_YES_PHRASES.search(words):
        return "yes"
    return _decide(bool(tokens & EN_YES), bool(tokens & EN_NO))


def says_nobody(text: str, language: str) -> bool:
    return bool((NOBODY_KIK if language == "kik" else NOBODY_EN).search(_words(text)))


def kikuyu_purpose(text: str) -> str | None:
    """A purpose in English, from words a Kikuyu answer may use."""
    for word in plain(text).replace("’", "'").split():
        if (english := KIKUYU_PURPOSES.get(word.strip(".,;:!?"))) is not None:
            return english
    return None
