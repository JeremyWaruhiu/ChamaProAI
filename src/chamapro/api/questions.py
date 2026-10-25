"""Every question set, each in order. v1 is the 40-sentence set of the recorded
corpus (interviews from before question sets existed); v2 is the current one."""
from __future__ import annotations

import json

from chamapro import config

from . import schemas as s
from .db import Interview

QUESTION_SETS: dict[str, list[s.Question]] = {}
for _q in json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8")):
    QUESTION_SETS.setdefault(_q["version"], []).append(s.Question(**_q))
for _qs in QUESTION_SETS.values():
    _qs.sort(key=lambda q: q.order)
CURRENT_SET = "v2"


def question(iv: Interview, sentence_no: int) -> s.Question | None:
    return next((q for q in QUESTION_SETS[iv.question_set] if q.order == sentence_no), None)
