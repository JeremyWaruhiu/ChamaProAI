"""English numbers: to_words(n) to read an amount aloud, parse(text) to find one in an
answer: "thirty thousand", "30k", "30,000", "30 000", "KSh 30000", "two hundred and fifty"."""
from __future__ import annotations

import re

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "x x twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
VALUES = {**{w: i for i, w in enumerate(ONES)}, **{w: i * 10 for i, w in enumerate(TENS) if i >= 2}}
TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+|,")


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = [f"{ONES[hundreds]} hundred"] if hundreds else []
    if rest:
        parts.append(ONES[rest] if rest < 20 else TENS[rest // 10] + (f"-{ONES[rest % 10]}" if rest % 10 else ""))
    return " and ".join(parts)


def to_words(n: int) -> str:
    if not 0 <= n <= 999_999_999:
        raise ValueError(f"{n} is outside 0 to 999,999,999")
    if n == 0:
        return "zero"
    millions, rest = divmod(n, 1_000_000)
    thousands, below = divmod(rest, 1000)
    parts = []
    if millions:
        parts.append(f"{_below_thousand(millions)} million")
    if thousands:
        parts.append(f"{_below_thousand(thousands)} thousand")
    if below:
        parts.append(_below_thousand(below))
    if len(parts) > 1 and 0 < below < 100:
        return " ".join(parts[:-1]) + " and " + parts[-1]
    return " ".join(parts)


def _clean(text: str) -> str:
    text = text.lower().replace("-", " ")
    text = re.sub(r"(?<=\d)[, ](?=\d{3}\b)", "", text)                    # 30,000 and 30 000
    return re.sub(r"(\d+(?:\.\d+)?)\s*(k|m)\b", lambda m: f"{m[1]} {'thousand' if m[2] == 'k' else 'million'}", text)


def _runs(tokens: list[str]) -> list[int]:
    """The value of each unbroken run of number words and figures."""
    out, total, current, in_run = [], 0, None, False

    def close():
        nonlocal total, current, in_run
        if in_run:
            out.append(int(total + (current or 0)))
        total, current, in_run = 0, None, False

    for i, t in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        figure = t[0].isdigit()
        if figure or t in VALUES:
            value = float(t) if figure else VALUES[t]
            adds_on = current is not None and not figure and (value < 100 and current % 100 == 0
                                                               or value < 10 and current % 10 == 0 and current % 100 >= 20)
            if in_run and current is not None and not adds_on:
                close()
            current = (current or 0) + value if adds_on else value
            in_run = True
        elif t in SCALES:
            scale = SCALES[t]
            if scale == 100:
                current = (current if current is not None else 1) * 100
            else:
                total += (current if current is not None else 1) * scale
                current = None
            in_run = True
        elif t == "a" and following in SCALES:
            continue
        elif t == "and" and in_run and following is not None and (following[0].isdigit() or following in VALUES):
            continue
        else:
            close()
    close()
    return out


def parse(text: str) -> int | None:
    """The largest number in the text, or None."""
    found = _runs(TOKEN.findall(_clean(text)))
    return max(found) if found else None
