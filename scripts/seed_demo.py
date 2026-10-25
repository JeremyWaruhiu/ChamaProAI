"""Create the demo interviews without re-running Whisper.

1. The Kikuyu demo (question set v1, live): reads the saved ASR output
   (data/asr_paza.csv) and the matching clips in data/audio_16k/, and writes
   one interview whose 40 responses are all marked transcribed.
2. An English practice interview (question set v2, practice) for a fictional
   applicant: the applicant form filled in and all eight answers typed. Needs
   no audio, so it can be seeded on any machine.
3. Demo accounts: one loan officer and two fictional members with their own
   logins, each member with a loan application on a typed, assessable
   practice interview. With the classifier present (models/), both are
   assessed with fixed features (no Gemini, no network; the assessment says
   so in extraction_model) and decided by the demo officer: Grace's is
   approved, Peter's needs two guarantors, which he can add after signing in.
   Without the classifier they wait at "interview completed" for the
   dashboard. Passwords are random, printed once here and never written to
   a file; a re-run leaves existing logins and their passwords alone.

The interviews are ready for review and assessment in the dashboard.

    python scripts/seed_demo.py
    python scripts/seed_demo.py --practice-only    # without the audio corpus
    python scripts/seed_demo.py --no-accounts      # interviews only

Idempotent: it ensures one open demo interview holds every row of the CSV,
and one open practice interview holds every typed answer.
A second run changes nothing; a run after a response was deleted restores
only that response; a run after the demo was assessed (assessments are
immutable) starts a fresh demo interview.

Audio is copied into data/uploads/<interview_id>/ like any upload, so
re-recording in the dashboard deletes the copy, never the corpus file.
"""
from __future__ import annotations

import argparse, csv, json, math, secrets, shutil, sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import soundfile as sf
from sqlalchemy import select

from chamapro import config
from chamapro.api import audit, loans, storage
from chamapro.api import schemas as s
from chamapro.api.auth import hash_password
from chamapro.api.db import (Applicant, Assessment, Interview, LoanApplication, Member,
                             Response, SessionLocal, User, init_db, utcnow)

import score_interview  # scripts/, next to this file

DEMO_NAME = "Demo applicant (S01)"
# The model that produced data/asr_paza.csv, recorded as each row's provenance.
CSV_ASR_MODEL = "microsoft/paza-whisper-large-v3-turbo"

# The practice applicant is invented: no real person's details.
PRACTICE_NAME = "Practice: Mary Wambui (fictional)"
PRACTICE_FORM = {"age": 38, "sex": "female", "education": 4,   # Secondary completed
                 "marital_status": "married"}
# One typed English answer per v2 question, keyed by its order.
PRACTICE_ANSWERS = {
    1: "There are five of us at home: my husband, me and our three children. "
       "Two of the children are in school, and the youngest is three, so one is under five.",
    2: "My main income is selling milk from our two dairy cows to the cooperative. "
       "In a normal month the household earns about 18,000 shillings altogether.",
    3: "My husband does casual work on building sites, and my sister in Nairobi sometimes "
       "sends us money. About 12,000 shillings a month comes from farming: the milk and "
       "some vegetables.",
    4: "Yes. We have the two cows and some goats, and we keep maize in the store after the "
       "harvest. We also own the land our house is on.",
    5: "This year we bought a dairy goat and put new iron sheets on the kitchen roof. "
       "We did not buy any land or equipment.",
    6: "Yes, once. I guaranteed a friend's SACCO loan and she stopped paying, so I lost "
       "5,000 shillings from my deposits. It was a SACCO loan, not a chama loan.",
    7: "Yes. I took a SACCO loan to buy the cows and finished repaying it last year.",
    8: "Yes, I have a small loan from my chama now, which I am still repaying.",
}


@dataclass
class Seeded:
    interview_id: int
    created: bool       # a new interview was made
    added: int          # responses written this run
    total: int          # responses the interview now holds


def read_rows(csv_path: Path, audio_dir: Path) -> list[dict]:
    """CSV rows with their source clip; refuses if any clip is missing."""
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{csv_path} has no rows")
    for r in rows:
        r["sentence_no"] = int(r["sentence_no"])
        r["audio"] = audio_dir / f"{r['id']}.wav"
    missing = [r["audio"].name for r in rows if not r["audio"].exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} clip(s) missing from {audio_dir}: "
                                + ", ".join(missing[:5]))
    nos = [r["sentence_no"] for r in rows]
    if len(set(nos)) != len(nos):
        raise ValueError(f"{csv_path} repeats a sentence_no")
    return rows


def seed(csv_path: Path, audio_dir: Path, name: str = DEMO_NAME,
         asr_model: str = CSV_ASR_MODEL) -> Seeded:
    rows = read_rows(csv_path, audio_dir)
    init_db()
    copied: list[str] = []
    with SessionLocal() as db:
        iv = db.scalars(select(Interview).join(Applicant)
                        .where(Applicant.name == name, Interview.status == "open")
                        .order_by(Interview.id.desc())).first()
        created = iv is None
        if created:
            iv = Interview(applicant=Applicant(name=name), question_set="v1",
                           language="kik", mode="live")
            db.add(iv)
            db.flush()

        have = {r.sentence_no for r in iv.responses}
        todo = [r for r in rows if r["sentence_no"] not in have]
        store = storage.backend()
        try:
            now = utcnow()
            for r in todo:
                resp = Response(
                    interview_id=iv.id, sentence_no=r["sentence_no"],
                    domain=r["domain"] or None, audio_path="",
                    duration_s=round(sf.info(str(r["audio"])).duration, 2),
                    status="transcribed", transcript=r["hypothesis"],
                    transcript_asr=r["hypothesis"], asr_model=asr_model,
                    asr_seconds=float(r["asr_seconds"]) if r.get("asr_seconds") else None,
                    transcribed_at=now)
                db.add(resp)
                db.flush()
                key = storage.clip_key(iv.id, resp.id, r["sentence_no"])
                dst = config.UPLOADS_DIR / key
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(r["audio"], dst)
                resp.audio_path = store.save(dst, key)
                copied.append(resp.audio_path)
            db.commit()
        except BaseException:
            db.rollback()
            for ref in copied:
                store.delete(ref)
            raise
        return Seeded(iv.id, created, len(todo), len(have) + len(todo))


def seed_practice(name: str = PRACTICE_NAME) -> Seeded:
    """The English practice interview: form filled, every v2 answer typed."""
    questions = {q["order"]: q for q in json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
                 if q["version"] == "v2"}
    if sorted(questions) != sorted(PRACTICE_ANSWERS):
        raise ValueError("practice answers do not match question set v2")
    init_db()
    with SessionLocal() as db:
        iv = db.scalars(select(Interview).join(Applicant)
                        .where(Applicant.name == name, Interview.status == "open",
                               Interview.mode == "practice")
                        .order_by(Interview.id.desc())).first()
        created = iv is None
        if created:
            iv = Interview(applicant=Applicant(name=name, **PRACTICE_FORM), question_set="v2",
                           language="en", mode="practice")
            db.add(iv)
            db.flush()
        have = {r.sentence_no for r in iv.responses}
        todo = [n for n in sorted(PRACTICE_ANSWERS) if n not in have]
        for n in todo:
            db.add(Response(interview_id=iv.id, sentence_no=n, domain=questions[n]["topic"],
                            source="typed", audio_path="", status="transcribed",
                            transcript=PRACTICE_ANSWERS[n]))
        db.commit()
        return Seeded(iv.id, created, len(todo), len(have) + len(todo))


# --- Demo accounts and loan applications (all fictional) ----------------------

OFFICER = "demo.officer"
# Recorded on each seeded assessment instead of a Gemini model name.
SEED_EXTRACTION = "seed_demo.py: fixed features, no extraction model"
MEMBERS = [
    {"login": "demo.grace", "member_no": "DEMO-001", "full_name": "Grace Njeri (fictional)",
     "phone": "0700000001", "joined_on": date(2019, 3, 1),
     "form": {"age": 41, "sex": "female", "education": 4, "marital_status": "married"},
     "answers": {
         1: "Four of us: my husband, me and our two children. Both children are in school; "
            "none is under five.",
         2: "I sell milk to the cooperative and run a small kiosk. In a normal month we earn "
            "about 25,000 shillings.",
         3: "Farming and my own business. About 15,000 shillings a month comes from the cows "
            "and the shamba.",
         4: "We own our land and the house, and we keep three dairy cows.",
         5: "We bought a heifer this year. Nothing else.",
         6: "No, I have never lost money as a guarantor.",
         7: "Yes, I repaid a SACCO loan for the kiosk two years ago.",
         8: "Yes, I borrowed from my chama last year and repaid it.",
     },
     "features": {"household_size": 4, "children": 2, "children_under5": 0,
                  "children_in_school": 2, "monthly_income_kes": 25000, "agri_income_kes": 15000,
                  "income_sources": {"farming": 1, "own_business": 1},
                  "non_monetary_savings": {"land_or_buildings": 1, "livestock": 1},
                  "purchases_last_12m": {"livestock": 1},
                  "lost_as_guarantor": {"sacco": 0, "chama": 0},
                  "sacco_loan_use": 1, "chama_loan_use": 1},
     "application": {"amount_requested_kes": 40000, "purpose": "A second dairy cow",
                     "term_months": 12, "sacco_savings_kes": 20000},
     "decision": {"outcome": "approve",
                  "officer_notes": "Demo record (fictional member). Repaid an earlier loan on time.",
                  "member_message": "Your loan of KSh 40,000 has been approved. Please visit the "
                                    "branch to sign the loan form."}},
    {"login": "demo.peter", "member_no": "DEMO-002", "full_name": "Peter Kamau (fictional)",
     "phone": "0700000002", "joined_on": date(2023, 5, 1),
     "form": {"age": 35, "sex": "male", "education": 3, "marital_status": "married"},
     "answers": {
         1: "Six of us: my wife, me and four children. One is under five and three are in school.",
         2: "I grow maize and beans and do casual work on building sites. About 14,000 shillings "
            "in a normal month.",
         3: "Farming and casual work. About 6,000 shillings a month comes from the farm.",
         4: "We keep goats and chickens. We do not own the land; we rent it.",
         5: "No, we did not buy any of those this year.",
         6: "Yes. I guaranteed a chama loan for a neighbour and lost 3,000 shillings.",
         7: "No, I have never taken a SACCO loan.",
         8: "Yes, I am repaying a chama loan now.",
     },
     "features": {"household_size": 6, "children": 4, "children_under5": 1,
                  "children_in_school": 3, "monthly_income_kes": 14000, "agri_income_kes": 6000,
                  "income_sources": {"farming": 1, "casual_worker": 1},
                  "non_monetary_savings": {"livestock": 1}, "purchases_last_12m": {},
                  "lost_as_guarantor": {"sacco": 0, "chama": 1},
                  "sacco_loan_use": 0, "chama_loan_use": 2},
     "application": {"amount_requested_kes": 60000, "purpose": "School fees and farm inputs",
                     "term_months": 18, "sacco_savings_kes": 25000},
     "decision": {"outcome": "approve_with_guarantor", "guarantors_required": 2,
                  "officer_notes": "Demo record (fictional member). First SACCO loan; "
                                   "ask for guarantors.",
                  "member_message": "Your loan can be approved once two guarantors who are SACCO "
                                    "members have been confirmed. Please add them here."}},
]


@dataclass
class AccountsSeeded:
    passwords: dict[str, str] = field(default_factory=dict)   # new logins only, never stored
    existing: list[str] = field(default_factory=list)
    applications: list[tuple[str, int, str, bool]] = field(default_factory=list)  # no, id, status, new
    assessed: bool = False


def ensure_user(db, username: str, role: str, out: AccountsSeeded) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        out.existing.append(username)
        return user
    password = secrets.token_urlsafe(12)
    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    audit.record(db, None, "user.create", "user", user.id, role=role, via="seed_demo.py")
    out.passwords[username] = password
    return user


def seed_interview(db, spec: dict, officer: User) -> Interview:
    """A practice interview (fictional people stay out of live statistics),
    English, v2, the form filled in and every answer typed."""
    questions = {q["order"]: q for q in json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
                 if q["version"] == "v2"}
    if sorted(questions) != sorted(spec["answers"]):
        raise ValueError(f"{spec['login']}: answers do not match question set v2")
    iv = Interview(applicant=Applicant(name=spec["full_name"], **spec["form"]),
                   question_set="v2", language="en", mode="practice")
    db.add(iv)
    db.flush()
    audit.record(db, officer, "interview.create", "interview", iv.id, question_set="v2",
                 language="en", mode="practice", via="seed_demo.py")
    for n, text in sorted(spec["answers"].items()):
        db.add(Response(interview_id=iv.id, sentence_no=n, domain=questions[n]["topic"],
                        source="typed", audio_path="", status="transcribed", transcript=text))
    db.flush()
    return iv


def seed_assessment(db, iv: Interview, spec: dict, officer: User) -> None:
    """Score with the real classifier on fixed features; provenance says so."""
    form = score_interview.form_values(**spec["form"])
    scored = score_interview.score(spec["features"], config.CLASSIFIER_PATH,
                                   config.CLASSIFIER_META_PATH, form=form)
    out = scored.assessment
    vector = {c: None if math.isnan(v := float(x)) else v for c, x in scored.vector.iloc[0].items()}
    a = Assessment(interview=iv, risk_class=out["risk_class"], probabilities=out["probabilities"],
                   feature_vector=vector, contributions=out["top_contributions"],
                   extracted=out["extracted"], applicant_form=out["applicant_form"],
                   extraction_completeness=out["extraction_completeness"],
                   features_populated=out["features_populated"],
                   features_total=out["features_total"],
                   features_not_extractable=out["features_not_extractable_from_interview"],
                   extraction_model=SEED_EXTRACTION, model_file=scored.model_file,
                   model_sha256=scored.model_sha256, assessed_by=officer.username)
    db.add(a)
    iv.status = "assessed"
    db.flush()
    audit.record(db, officer, "assessment.create", "assessment", a.id, interview_id=iv.id,
                 risk_class=a.risk_class, via="seed_demo.py")
    loans.sync_with_interview(db, iv, officer)


def seed_accounts(officer_login: str = OFFICER, members: list[dict] = MEMBERS) -> AccountsSeeded:
    out = AccountsSeeded()
    out.assessed = config.CLASSIFIER_PATH.exists() and config.CLASSIFIER_META_PATH.exists()
    init_db()
    with SessionLocal() as db:
        officer = ensure_user(db, officer_login, "officer", out)
        for spec in members:
            user = ensure_user(db, spec["login"], "member", out)
            member = db.scalar(select(Member).where(Member.member_no == spec["member_no"]))
            if member is None:
                member = Member(member_no=spec["member_no"], full_name=spec["full_name"],
                                phone=spec["phone"], joined_on=spec["joined_on"])
                db.add(member)
                db.flush()
                audit.record(db, officer, "member.create", "member", member.id, via="seed_demo.py")
            if member.user_id is None:
                member.user_id = user.id
                audit.record(db, None, "user.link_member", "user", user.id, member_id=member.id,
                             via="seed_demo.py")
            app = db.scalar(select(LoanApplication).where(LoanApplication.member_id == member.id)
                            .order_by(LoanApplication.id))
            if app is not None:
                out.applications.append((member.member_no, app.id, app.status, False))
                continue
            app = LoanApplication(member=member, created_by=officer.id, status="draft",
                                  **spec["application"])
            db.add(app)
            db.flush()
            audit.record(db, officer, "application.create", "loan_application", app.id,
                         status="draft", member_id=member.id,
                         amount_requested_kes=app.amount_requested_kes, via="seed_demo.py")
            loans.link_interview(db, app, seed_interview(db, spec, officer).id, officer)
            if out.assessed:
                seed_assessment(db, app.interview, spec, officer)
                db.commit()
                loans.decide(db, app.interview, s.DecisionCreate(**spec["decision"]), officer)
            db.commit()
            out.applications.append((member.member_no, app.id, app.status, True))
        db.commit()
    return out


def report_accounts(res: AccountsSeeded) -> None:
    if res.passwords:
        print("demo logins created; passwords are shown once and not saved anywhere:")
        for name, pw in res.passwords.items():
            print(f"  {name:14} {pw}")
    for name in res.existing:
        print(f"login {name} already exists; password unchanged (an admin can reset it)")
    for no, app_id, status, new in res.applications:
        print(f"{'created' if new else 'kept'} loan application {app_id} for {no}: {status}")
    if not res.assessed:
        print("  classifier missing (models/): applications wait at interview_complete; "
              "assess and decide them in the dashboard")


def report(kind: str, res: Seeded) -> None:
    if res.created:
        print(f"created {kind} interview {res.interview_id} with {res.added} responses")
    elif res.added:
        print(f"{kind} interview {res.interview_id}: restored {res.added} missing responses")
    else:
        print(f"{kind} interview {res.interview_id} already complete; nothing to do")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=config.DATA_DIR / "asr_paza.csv")
    ap.add_argument("--audio", type=Path, default=config.DATA_DIR / "audio_16k")
    ap.add_argument("--name", default=DEMO_NAME, help="applicant name that marks the demo")
    ap.add_argument("--asr-model", default=CSV_ASR_MODEL,
                    help="model that produced the CSV, stored as provenance")
    ap.add_argument("--practice-only", action="store_true",
                    help="skip the Kikuyu demo interview (no audio corpus needed)")
    ap.add_argument("--no-accounts", action="store_true",
                    help="skip the demo officer, members and loan applications")
    a = ap.parse_args()

    if not a.practice_only:
        try:
            res = seed(a.csv, a.audio, a.name, a.asr_model)
        except (OSError, ValueError, KeyError) as e:
            sys.exit(f"seed failed, nothing written: {e}")
        report("demo", res)
        print(f"  {res.total} responses, database {config.DB_PATH}")

    res = seed_practice()
    report("practice", res)
    print(f"  {res.total} typed English answers, database {config.DB_PATH}")

    if not a.no_accounts:
        report_accounts(seed_accounts())


if __name__ == "__main__":
    main()
