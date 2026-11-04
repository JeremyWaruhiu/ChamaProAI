"""Rehearse a conversation in the terminal: type the member's answers, and see each turn,
what was read from it, and how it was worked out. It runs the code the API runs.

    python scripts/converse.py --member "Wanjiru Kamau" --language en
    python scripts/converse.py --member "Njeri Mwangi" --language kik --live

It never touches another database: demo_self_service sets a throwaway SQLite file, whatever
.env says, before chamapro is imported, and builds the four self-service people on it.
Nothing reaches Gemini without --live: only the parsers read the answers. Speech is made
and cached in data/tts_cache/ unless --no-speech; models and classifier need to be on disk.
Answers can be piped in, one per line.
"""
from __future__ import annotations

import demo_self_service  # noqa: I001  (first: it chooses the database)

import argparse
import json
import sys
import time

from chamapro import config
from chamapro.api import self_service
from chamapro.api.db import LoanApplication, SessionLocal, User, engine, init_db
from chamapro.conversation import service, tts


def show_turn(t) -> None:
    who = "BOT   " if t.speaker == "bot" else "MEMBER"
    print(f"\n{who} [{t.template_id}] {t.text}")
    if t.speaker == "bot":
        heard = f"audio {t.audio_ref[:12]}... ({t.tts_ms} ms)" if t.audio_ref else "audio none"
        print(f"       {heard}" + ("  kik_pending" if t.kik_pending else ""))
        if t.spoken_text != t.text:
            print(f"       spoken: {t.spoken_text}")
    else:
        if t.translation and t.translation != t.text:
            print(f"       translation: {t.translation}")
        print("       extraction: " + json.dumps({k: t.extraction[k] for k in ("parser", "model", "model_error", "used",
                                                                                 "amount_conflict")}, ensure_ascii=False))
        print(f"       latency ms: extract {t.extract_ms}, evaluate {t.evaluate_ms}, tts {t.tts_ms}")


def show_explain(explain: dict) -> None:
    print("\n--- explain")
    print(f"  outcome      {explain['outcome']} ({explain['reason_code']}): {explain['reason']}")
    print(f"  risk class   {explain['risk_class']}  {explain['probabilities']}")
    for s in explain["top_shap"][:5]:
        print(f"  SHAP         {s['shap']:+.3f} {'for    ' if s['in_favour'] else 'against'} {s['label']}")
    print(f"  maximums     {explain['maximums']}")
    for c in explain["checks"]:
        mark = {True: "pass", False: "FAIL", None: "n/a "}[c["passed"]]
        print(f"  {mark}         {c['check']}: {json.dumps(c['values'], ensure_ascii=False)}")
    print(f"  sources      {json.dumps(explain['sources'])}")


def read_answer() -> str | None:
    try:
        return input("\nyou> ").strip()
    except EOFError:
        return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--member", required=True, help="one of the four self-service people, by full name")
    ap.add_argument("--language", required=True, choices=["en", "kik"])
    ap.add_argument("--live", action="store_true", help="let Gemini read the answers; without it nothing calls Gemini")
    ap.add_argument("--no-speech", action="store_true", help="text only")
    a = ap.parse_args()
    if engine.url.get_backend_name() != "sqlite":      # demo_self_service has set this; never go on if not
        sys.exit("this script runs on its own throwaway SQLite database")
    config.CONVERSATION_GEMINI_LIVE = a.live
    config.TTS_ENABLED = not a.no_speech

    init_db()
    started = time.perf_counter()
    with SessionLocal() as db:
        members = demo_self_service.build(db)
        member = next((m for m in members.values() if m.full_name.casefold() == a.member.casefold()), None)
        if member is None:
            sys.exit(f"no member called {a.member!r}; choose from: " + ", ".join(m.full_name for m in members.values()))
        user = User(username="rehearsal.member", password_hash="!", role="member", is_active=False)
        db.add(user)
        db.flush()
        member.user_id = user.id
        db.commit()
        print(f"Set up in {time.perf_counter() - started:.1f} s. Gemini {'ON' if a.live else 'off'}, "
              f"speech {'on' if config.TTS_ENABLED else 'off'}. Database: {engine.url.database}")

        started = time.perf_counter()
        conv, _ = service.start(db, member, a.language)
        for t in service.turns_of(db, conv):
            show_turn(t)
        spent = 0.0
        last_seen = conv.turn_count
        while conv.status == "open":
            answer = read_answer()
            if answer is None:
                print("\nNo more answers: left as it is, and it would be abandoned when idle.")
                return
            t0 = time.perf_counter()
            spoken, bots, explain = service.reply(db, conv, member, user, text=answer)
            spent += time.perf_counter() - t0
            last_seen = conv.turn_count
            show_turn(spoken)
            for t in bots:
                show_turn(t)
            if explain:
                show_explain(explain)
        print(f"\nEnded: {conv.status}. {last_seen} turns; {spent:.2f} s of server work across the replies.")
        actions = [x for t in service.turns_of(db, conv) for x in (t.actions or [])]
        for x in actions:
            print(f"Offered: {x['label']} ({x['id']}, application {x['application_id']})")
        if any(x["id"] == "request_review" for x in actions):
            print("\nType review to ask an officer, or anything else to finish.")
            if (read_answer() or "").lower() == "review":
                app = db.get(LoanApplication, conv.application_id)
                print(self_service.request_review(db, app, f"rehearsal-{conv.id}", user)["message"])
    tts.reset()


if __name__ == "__main__":
    main()
