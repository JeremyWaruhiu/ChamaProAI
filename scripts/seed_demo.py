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

--demo-db builds a separate, self-contained database for an online demo
instead: an admin, two officers, nine fictional members and twelve LIVE loan
applications covering every application status and every decision outcome,
each assessed interview scored by the real classifier on fixed features. It
needs models/ but no audio, no Gemini and no network. It never writes to
data/chamapro.db, refuses a file that is not an earlier demo database, and
rebuilds an earlier one only with --replace (new passwords, printed once).

    python scripts/seed_demo.py --demo-db data/demo.db
    python scripts/seed_demo.py --demo-db data/demo.db --replace

Idempotent: it ensures one open demo interview holds every row of the CSV,
and one open practice interview holds every typed answer.
A second run changes nothing; a run after a response was deleted restores
only that response; a run after the demo was assessed (assessments are
immutable) starts a fresh demo interview.

Audio is copied into data/uploads/<interview_id>/ like any upload, so
re-recording in the dashboard deletes the copy, never the corpus file.
"""
from __future__ import annotations

import argparse, csv, json, math, os, secrets, shutil, sqlite3, sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# config reads the database location once, at import: --demo-db has to be in
# the environment before anything from chamapro is imported. An explicit
# DATABASE_URL wins over both CHAMAPRO_DB and .env.
if __name__ == "__main__":
    _early = argparse.ArgumentParser(add_help=False)
    _early.add_argument("--demo-db", type=Path)
    if (_demo_db := _early.parse_known_args()[0].demo_db) is not None:
        os.environ["DATABASE_URL"] = f"sqlite:///{_demo_db.resolve()}"

import soundfile as sf
from sqlalchemy import event, select

from chamapro import config
from chamapro.api import audit, loans, storage
from chamapro.api import schemas as s
from chamapro.api.auth import hash_password
from chamapro.api.db import (APPLICATION_STATUSES, Applicant, Assessment, Guarantor, Interview,
                             LoanApplication, Member, Response, SessionLocal, User, init_db,
                             utcnow)

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


def seed_interview(db, spec: dict, officer: User, mode: str = "practice",
                   answered: int | None = None) -> Interview:
    """An English v2 interview with the form filled in and every answer typed,
    or only the first `answered`. Practice by default, so fictional people stay
    out of the live statistics of a real database; the demo database is all live."""
    questions = {q["order"]: q for q in json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
                 if q["version"] == "v2"}
    if sorted(questions) != sorted(spec["answers"]):
        raise ValueError(f"{spec['full_name']}: answers do not match question set v2")
    iv = Interview(applicant=Applicant(name=spec["full_name"], **spec["form"]),
                   question_set="v2", language="en", mode=mode)
    db.add(iv)
    db.flush()
    audit.record(db, officer, "interview.create", "interview", iv.id, question_set="v2",
                 language="en", mode=mode, via="seed_demo.py")
    for n, text in sorted(spec["answers"].items())[:answered]:
        db.add(Response(interview_id=iv.id, sentence_no=n, domain=questions[n]["topic"],
                        source="typed", audio_path="", status="transcribed", transcript=text))
    db.flush()
    return iv


def ensure_member(db, spec: dict, officer: User, user: User | None) -> Member:
    """The member record numbered spec["member_no"], linked to user if given."""
    member = db.scalar(select(Member).where(Member.member_no == spec["member_no"]))
    if member is None:
        member = Member(member_no=spec["member_no"], full_name=spec["full_name"],
                        phone=spec["phone"], joined_on=spec["joined_on"])
        db.add(member)
        db.flush()
        audit.record(db, officer, "member.create", "member", member.id, via="seed_demo.py")
    if user is not None and member.user_id is None:
        member.user_id = user.id
        audit.record(db, None, "user.link_member", "user", user.id, member_id=member.id,
                     via="seed_demo.py")
    return member


def create_application(db, member: Member, officer: User, fields: dict) -> LoanApplication:
    app = LoanApplication(member=member, created_by=officer.id, status="draft", **fields)
    db.add(app)
    db.flush()
    audit.record(db, officer, "application.create", "loan_application", app.id,
                 status="draft", member_id=member.id,
                 amount_requested_kes=app.amount_requested_kes, via="seed_demo.py")
    return app


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
            member = ensure_member(db, spec, officer, user)
            app = db.scalar(select(LoanApplication).where(LoanApplication.member_id == member.id)
                            .order_by(LoanApplication.id))
            if app is not None:
                out.applications.append((member.member_no, app.id, app.status, False))
                continue
            app = create_application(db, member, officer, spec["application"])
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


# --- Self-contained demo database (--demo-db) ----------------------------------------

DEMO_STAFF = [("demo.admin", "admin"), ("demo.officer1", "officer"), ("demo.officer2", "officer")]
# Every person is invented: "(fictional)" is part of each name, every phone
# number is 0700 000 xxx, and every member number starts DEMO-.
# joined: months of membership before today; login: members who can sign in.
DEMO_PEOPLE = {
    "grace": {"full_name": "Grace Njeri (fictional)", "joined": 70, "login": "demo.grace",
              "form": {"age": 48, "sex": "female", "education": 6, "marital_status": "married"},
              "features": {"household_size": 4, "children": 2, "children_under5": 0,
                           "children_in_school": 2, "monthly_income_kes": 45000,
                           "agri_income_kes": 20000,
                           "income_sources": {"farming": 1, "own_business": 1},
                           "non_monetary_savings": {"land_or_buildings": 1, "livestock": 1},
                           "purchases_last_12m": {"livestock": 1, "farm_equipment": 1},
                           "lost_as_guarantor": {"sacco": 0, "chama": 0},
                           "sacco_loan_use": 1, "chama_loan_use": 1}},
    "peter": {"full_name": "Peter Kamau (fictional)", "joined": 30, "login": "demo.peter",
              "form": {"age": 35, "sex": "male", "education": 3, "marital_status": "married"},
              "features": {"household_size": 6, "children": 4, "children_under5": 1,
                           "children_in_school": 3, "monthly_income_kes": 14000,
                           "agri_income_kes": 6000,
                           "income_sources": {"farming": 1, "casual_worker": 1},
                           "non_monetary_savings": {"livestock": 1}, "purchases_last_12m": {},
                           "lost_as_guarantor": {"sacco": 0, "chama": 1},
                           "sacco_loan_use": 0, "chama_loan_use": 2}},
    "mary": {"full_name": "Mary Wanjiku (fictional)", "joined": 26, "login": "demo.mary",
             "form": {"age": 33, "sex": "female", "education": 4, "marital_status": "married"},
             "features": {"household_size": 5, "children": 3, "children_under5": 1,
                          "children_in_school": 2, "monthly_income_kes": 18000,
                          "agri_income_kes": 3000, "income_sources": {"own_business": 1},
                          "non_monetary_savings": {"livestock": 1}, "purchases_last_12m": {},
                          "lost_as_guarantor": {"sacco": 0, "chama": 0},
                          "sacco_loan_use": 0, "chama_loan_use": 1}},
    "john": {"full_name": "John Mwangi (fictional)", "joined": 96,
             "form": {"age": 62, "sex": "male", "education": 5, "marital_status": "married"},
             "features": {"household_size": 2, "children": 0, "children_under5": 0,
                          "children_in_school": 0, "monthly_income_kes": 30000,
                          "agri_income_kes": 10000,
                          "income_sources": {"pension": 1, "farming": 1, "renting_out": 1},
                          "non_monetary_savings": {"land_or_buildings": 1, "agroforestry": 1},
                          "purchases_last_12m": {}, "lost_as_guarantor": {"sacco": 0, "chama": 0},
                          "sacco_loan_use": 2, "chama_loan_use": 0}},
    "faith": {"full_name": "Faith Wairimu (fictional)", "joined": 50,
              "form": {"age": 67, "sex": "female", "education": 0, "marital_status": "widowed"},
              "features": {"household_size": 3, "children": 1, "children_under5": 1,
                           "children_in_school": 0, "monthly_income_kes": 4000,
                           "agri_income_kes": 1500,
                           "income_sources": {"social_transfer": 1, "remittances": 1},
                           "non_monetary_savings": {}, "purchases_last_12m": {},
                           "lost_as_guarantor": {"sacco": 0, "chama": 1},
                           "sacco_loan_use": 0, "chama_loan_use": 2}},
    "samuel": {"full_name": "Samuel Otieno (fictional)", "joined": 14,
               "form": {"age": 31, "sex": "male", "education": 2, "marital_status": "single"},
               "features": {"household_size": 3, "children": 1, "children_under5": 1,
                            "children_in_school": 0, "monthly_income_kes": 9000,
                            "agri_income_kes": 0, "income_sources": {"own_business": 1},
                            "non_monetary_savings": {},
                            "purchases_last_12m": {"business_equipment": 1},
                            "lost_as_guarantor": {"sacco": 0, "chama": 0},
                            "sacco_loan_use": 0, "chama_loan_use": 0}},
    # Joined four months ago: short of the SACCO rule's six months' membership.
    "esther": {"full_name": "Esther Nyambura (fictional)", "joined": 4, "login": "demo.esther",
               "form": {"age": 29, "sex": "female", "education": 1, "marital_status": "divorced"},
               "features": {"household_size": 4, "children": 3, "children_under5": 2,
                            "children_in_school": 1, "monthly_income_kes": 7000,
                            "agri_income_kes": 0, "income_sources": {"own_business": 1},
                            "non_monetary_savings": {}, "purchases_last_12m": {},
                            "lost_as_guarantor": {"sacco": 1, "chama": 0},
                            "sacco_loan_use": 0, "chama_loan_use": 2}},
    "joseph": {"full_name": "Joseph Kiprono (fictional)", "joined": 20,
               "form": {"age": 27, "sex": "male", "education": 3, "marital_status": "single"},
               "features": {"household_size": 2, "children": 0, "children_under5": 0,
                            "children_in_school": 0, "monthly_income_kes": 5000,
                            "agri_income_kes": 0, "income_sources": {"casual_worker": 1},
                            "non_monetary_savings": {}, "purchases_last_12m": {},
                            "lost_as_guarantor": {"sacco": 0, "chama": 1},
                            "sacco_loan_use": 0, "chama_loan_use": 0}},
    "david": {"full_name": "David Mutua (fictional)", "joined": 40,
              "form": {"age": 39, "sex": "male", "education": 8, "marital_status": "married"},
              "features": {"household_size": 5, "children": 3, "children_under5": 1,
                           "children_in_school": 2, "monthly_income_kes": 60000,
                           "agri_income_kes": 5000, "income_sources": {"employed": 1, "farming": 1},
                           "non_monetary_savings": {"land_or_buildings": 1},
                           "purchases_last_12m": {"house_materials": 1},
                           "lost_as_guarantor": {"sacco": 0, "chama": 0},
                           "sacco_loan_use": 1, "chama_loan_use": 0}},
}
for _no, _p in enumerate(DEMO_PEOPLE.values(), 1):
    _p.update(member_no=f"DEMO-{_no:03d}", phone=f"0700000{_no:03d}")

NOTE = "Demo record (fictional member). "
# Oldest first. answered: typed answers (None: no interview yet); assess: score
# it; guarantors: (person, verdict) after the member submits them, verdict
# "pending" left for an officer to review in the dashboard. Comments give the
# model's risk class for these fixed features.
DEMO_APPLICATIONS = [
    {"person": "joseph", "days_ago": 58, "officer": "demo.officer2",          # High
     "fields": {"amount_requested_kes": 50000, "purpose": "Stock for a mitumba stall",
                "term_months": 12, "sacco_savings_kes": 6000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "decline",
                  "officer_notes": NOTE + "Irregular income; savings cover a fifth of the amount.",
                  "member_message": "We cannot approve this loan now. Building your SACCO "
                                    "savings for six months will help a future application."}},
    {"person": "grace", "days_ago": 52, "officer": "demo.officer1",           # Low
     "fields": {"amount_requested_kes": 40000, "purpose": "A second dairy cow",
                "term_months": 12, "sacco_savings_kes": 20000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "approve",
                  "officer_notes": NOTE + "Repaid an earlier SACCO loan on time.",
                  "member_message": "Your loan of KSh 40,000 has been approved. Please visit "
                                    "the branch to sign the loan form."}},
    {"person": "peter", "days_ago": 45, "officer": "demo.officer1",           # Medium
     "fields": {"amount_requested_kes": 60000, "purpose": "School fees and farm inputs",
                "term_months": 18, "sacco_savings_kes": 25000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "approve_with_guarantor", "guarantors_required": 2,
                  "officer_notes": NOTE + "First SACCO loan; ask for guarantors.",
                  "member_message": "Your loan can be approved once two guarantors who are "
                                    "SACCO members have been confirmed. Please add them here."},
     "guarantors": [("john", "verified"), ("david", "verified")]},
    {"person": "john", "days_ago": 38, "officer": "demo.officer2",            # Low
     "fields": {"amount_requested_kes": 150000, "purpose": "Roof and water tank for rental rooms",
                "term_months": 24, "sacco_savings_kes": 40000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "approve_reduced", "approved_amount_kes": 120000,
                  "officer_notes": NOTE + "Reduced to three times savings.",
                  "member_message": "We have approved KSh 120,000, three times your SACCO "
                                    "savings. Please visit the branch to sign."}},
    {"person": "faith", "days_ago": 30, "officer": "demo.officer1",           # Medium
     "fields": {"amount_requested_kes": 20000, "purpose": "Medical bills",
                "term_months": 6, "sacco_savings_kes": 12000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "refer",
                  "officer_notes": NOTE + "Refer to the credit committee: income is mostly "
                                          "transfers from family.",
                  "member_message": "Your application has gone to the credit committee, "
                                    "which meets next week."}},
    {"person": "samuel", "days_ago": 24, "officer": "demo.officer2",          # High
     "fields": {"amount_requested_kes": 80000, "purpose": "A second-hand motorbike",
                "term_months": 18, "sacco_savings_kes": 10000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "decline",
                  "officer_notes": NOTE + "Amount is eight times savings.",
                  "member_message": "We cannot approve this loan. A smaller amount, up to three "
                                    "times your savings, could be considered."}},
    {"person": "esther", "days_ago": 14, "officer": "demo.officer1",          # Medium
     "fields": {"amount_requested_kes": 15000, "purpose": "Stock for a vegetable stall",
                "term_months": 6, "sacco_savings_kes": 8000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "approve_with_guarantor", "guarantors_required": 2,
                  "officer_notes": NOTE + "New member; guarantors needed.",
                  "member_message": "Your loan can be approved once two guarantors who are "
                                    "SACCO members have been confirmed."},
     "guarantors": [("mary", "verified"), ("joseph", "rejected")]},
    {"person": "mary", "days_ago": 9, "officer": "demo.officer2",             # Medium
     "fields": {"amount_requested_kes": 35000, "purpose": "A sewing machine for the shop",
                "term_months": 12, "sacco_savings_kes": 15000},
     "answered": 8, "assess": True,
     "decision": {"outcome": "approve_with_guarantor", "guarantors_required": 2,
                  "officer_notes": NOTE + "Business income only; guarantors needed.",
                  "member_message": "Your loan can be approved once two guarantors who are "
                                    "SACCO members have been confirmed."},
     "guarantors": [("grace", "verified"), ("faith", "pending")]},
    {"person": "samuel", "days_ago": 2, "officer": "demo.officer2",
     "fields": {"amount_requested_kes": 25000, "purpose": "Motorbike repairs",
                "term_months": 6, "sacco_savings_kes": 10000},
     "answered": None},
    {"person": "david", "days_ago": 1, "officer": "demo.officer1",            # Low
     "fields": {"amount_requested_kes": 90000, "purpose": "Building a kitchen",
                "term_months": 24, "sacco_savings_kes": 45000},
     "answered": 8, "assess": True},
    {"person": "joseph", "days_ago": 0, "officer": "demo.officer2",
     "fields": {"amount_requested_kes": 12000, "purpose": "Tools for casual work",
                "term_months": 6, "sacco_savings_kes": 9000},
     "answered": 8},
    {"person": "grace", "days_ago": 0, "officer": "demo.officer1",
     "fields": {"amount_requested_kes": 30000, "purpose": "Fencing the paddock",
                "term_months": 12, "sacco_savings_kes": 26000},
     "answered": 3},
]
REJECTED_BECAUSE = "Has a declined application of his own; cannot guarantee another loan."

SOURCE_WORDS = {"farming": "farming", "employed": "a salaried job", "casual_worker": "casual work",
                "own_business": "my own business", "social_transfer": "Inua Jamii",
                "renting_out": "renting out rooms", "investments": "investments",
                "pension": "my pension", "remittances": "money my family sends"}
SAVINGS_WORDS = {"land_or_buildings": "our land and house", "livestock": "animals",
                 "jewellery": "jewellery", "digital_assets": "something online",
                 "agroforestry": "trees we planted to sell"}
PURCHASE_WORDS = {"land_or_plot": "land", "new_house": "a new house",
                  "house_materials": "iron sheets and cement for the house",
                  "business_equipment": "equipment for my business",
                  "farm_equipment": "a sprayer for the farm", "livestock": "a heifer"}
LOAN_USE = {0: "No, never.", 1: "Yes, before, and I repaid it.",
            2: "Yes, I am repaying one now."}


def listed(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def demo_answers(f: dict) -> dict[int, str]:
    """The eight typed v2 answers, written from the fixed features so the
    interview says what the assessment was scored on."""
    def flags(group, words):
        return [words[k] for k, v in f[group].items() if v]

    sources = flags("income_sources", SOURCE_WORDS)
    kids = f["children"]
    lost = [k.upper() if k == "sacco" else k for k, v in f["lost_as_guarantor"].items() if v]
    return {
        1: f"There are {f['household_size']} of us at home. "
           + (f"{kids} are my children: {f['children_under5']} under five and "
              f"{f['children_in_school']} in school." if kids else "I have no children."),
        2: f"Mostly {sources[0]}. In a normal month I earn about "
           f"{f['monthly_income_kes']:,} shillings.",
        3: f"From {listed(sources)}. "
           + (f"About {f['agri_income_kes']:,} shillings a month comes from farming."
              if f["agri_income_kes"] else "Nothing comes from farming."),
        4: f"Yes: {listed(saved)}." if (saved := flags("non_monetary_savings", SAVINGS_WORDS))
           else "No, only the money in the SACCO.",
        5: f"Yes, I bought {listed(bought)}." if (bought := flags("purchases_last_12m",
                                                                  PURCHASE_WORDS))
           else "No, none of those.",
        6: f"Yes, once, on a {lost[0]} loan." if lost else "No, never.",
        7: LOAN_USE[f["sacco_loan_use"]],
        8: LOAN_USE[f["chama_loan_use"]],
    }


def months_ago(n: int) -> date:
    today = date.today()
    y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
    return date(y, m + 1, 1)


class Clock:
    """Backdates the demo: every row the session writes while `now` is set is
    stamped with it instead of the real time, so the records span weeks, not
    one second. Rows are only ever inserted with their time, never updated
    afterwards, so the immutable tables stay untouched."""

    def __init__(self, db):
        self.now = None
        event.listen(db, "before_flush", self._stamp)

    def _stamp(self, session, _ctx, _instances):
        for obj in session.new:
            for attr in ("created_at", "submitted_at"):
                if hasattr(obj, attr) and getattr(obj, attr) is None:
                    setattr(obj, attr, self.now)
            if isinstance(obj, LoanApplication):
                obj.updated_at = self.now
        for obj in session.dirty:
            if isinstance(obj, LoanApplication):
                obj.updated_at = self.now
            elif isinstance(obj, Guarantor) and obj.verified_at is not None:
                obj.verified_at = self.now


@dataclass
class DemoSeeded:
    passwords: dict[str, str]                       # shown once, never stored
    applications: list[tuple[int, str, str, str]]   # id, member, risk class, status


def seed_demo_db() -> DemoSeeded:
    """Fill an empty database with the demo; see the module docstring."""
    if not (config.CLASSIFIER_PATH.exists() and config.CLASSIFIER_META_PATH.exists()):
        raise FileNotFoundError(f"the demo is scored by the real classifier; "
                                f"{config.CLASSIFIER_PATH} is missing")
    init_db()
    out, apps = AccountsSeeded(), []
    now = utcnow()
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            raise ValueError("the demo needs an empty database; this one already has users")
        clock = Clock(db)
        clock.now = now - timedelta(days=100)
        users = {name: ensure_user(db, name, role, out) for name, role in DEMO_STAFF}
        admin = users["demo.admin"]
        members = {}
        for key, p in DEMO_PEOPLE.items():
            user = ensure_user(db, p["login"], "member", out) if "login" in p else None
            members[key] = ensure_member(db, {**p, "joined_on": months_ago(p["joined"])},
                                         admin, user)
            users[key] = user
        db.commit()

        for spec in DEMO_APPLICATIONS:
            person = {**DEMO_PEOPLE[spec["person"]]}
            person["answers"] = demo_answers(person["features"])
            officer = users[spec["officer"]]
            t0 = now - timedelta(days=spec["days_ago"], minutes=90)
            clock.now = t0
            app = create_application(db, members[spec["person"]], officer, spec["fields"])
            if spec["answered"] is not None:
                clock.now = t0 + timedelta(minutes=20)
                iv = seed_interview(db, person, officer, mode="live", answered=spec["answered"])
                loans.link_interview(db, app, iv.id, officer)
            db.commit()
            if spec.get("assess"):
                clock.now = t0 + timedelta(minutes=50)
                seed_assessment(db, app.interview, person, officer)
                db.commit()
            if "decision" in spec:
                clock.now = t0 + timedelta(days=1, hours=2)
                loans.decide(db, app.interview, s.DecisionCreate(**spec["decision"]), officer)
            if "guarantors" in spec:
                clock.now = t0 + timedelta(days=3)
                share = (app.interview.decision.approved_amount_kes or app.amount_requested_kes) // 2
                body = s.GuarantorSubmit(guarantors=[
                    s.GuarantorIn(full_name=DEMO_PEOPLE[g]["full_name"],
                                  member_no=DEMO_PEOPLE[g]["member_no"],
                                  phone=DEMO_PEOPLE[g]["phone"], relationship="chama member",
                                  amount_guaranteed_kes=share)
                    for g, _ in spec["guarantors"]])
                loans.submit_guarantors(app.id, body, db=db, user=users[spec["person"]])
                for i, (g, (_, verdict)) in enumerate(zip(list(app.guarantors), spec["guarantors"])):
                    if verdict != "pending":
                        clock.now = t0 + timedelta(days=4, minutes=30 * i)
                        loans.review(db, g, verdict, officer,
                                     REJECTED_BECAUSE if verdict == "rejected" else None)
            db.refresh(app)
            risk = app.interview.assessment.risk_class \
                if app.interview and app.interview.assessment else "-"
            apps.append((app.id, app.member.member_no, risk, app.status))
    missing = set(APPLICATION_STATUSES) - {status for *_, status in apps}
    if missing:   # the point of the demo is that every screen has something on it
        raise RuntimeError(f"demo misses application statuses: {', '.join(sorted(missing))}")
    return DemoSeeded(out.passwords, apps)


def demo_db_refusal(path: Path, replace: bool) -> str | None:
    """Why --demo-db must not build at path, or None. Opens nothing but an
    existing demo file, read-only."""
    path = path.resolve()
    if path in {(config.DATA_DIR / "chamapro.db").resolve(), config.DB_PATH.resolve()}:
        return f"{path} is the working database; the demo goes in its own file"
    if config.DATABASE_URL != f"sqlite:///{path}":
        return f"DATABASE_URL is {config.DATABASE_URL}, not the demo file {path}"
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            is_demo = con.execute("SELECT 1 FROM users WHERE username = 'demo.admin'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        is_demo = None
    if not is_demo:
        return f"{path} exists and is not a demo database; choose another file"
    if not replace:
        return f"{path} already holds a demo; pass --replace to rebuild it with new passwords"
    return None


def build_demo_db(path: Path, replace: bool) -> None:
    if (why := demo_db_refusal(path, replace)) is not None:
        sys.exit(f"demo database not built: {why}")
    for f in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        f.unlink(missing_ok=True)
    try:
        res = seed_demo_db()
    except (OSError, ValueError) as e:
        sys.exit(f"demo database not built: {e}")
    print(f"built demo database {path.resolve()}")
    print("demo logins; passwords are shown once and not saved anywhere:")
    for name, pw in res.passwords.items():
        print(f"  {name:14} {pw}")
    for app_id, member_no, risk, status in res.applications:
        print(f"  application {app_id:>2} {member_no}  {risk:6}  {status}")


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
    ap.add_argument("--demo-db", type=Path, metavar="FILE",
                    help="build the self-contained online-demo database in FILE instead "
                         "(e.g. data/demo.db); nothing else is seeded")
    ap.add_argument("--replace", action="store_true",
                    help="with --demo-db: rebuild an existing demo database")
    a = ap.parse_args()

    if a.demo_db is not None:
        build_demo_db(a.demo_db, a.replace)
        return

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
