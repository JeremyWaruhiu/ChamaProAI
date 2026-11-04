"""Print the two demo members' evaluations, before and after they answer, on a throwaway
SQLite database. It never touches another database: the location is set here, before
chamapro is imported, whatever .env says. Needs models/ and nothing else.

    python scripts/demo_self_service.py
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory(prefix="chamapro-demo-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP.name) / 'demo.db'}"
os.environ["STORAGE_BACKEND"] = "local"

from chamapro.api.db import SessionLocal, User, init_db, nairobi_today, utcnow  # noqa: E402
from chamapro.api.decisions import Evaluation, LoanRequest, evaluate  # noqa: E402

import seed_demo  # noqa: E402
import seed_members  # noqa: E402

DAIRY = LoanRequest(40000, "A dairy cow")
SCHOOL = LoanRequest(60000, "School fees", 12)


def build(db) -> dict:
    """The four people of the automatic decisions, and nobody else."""
    actor = User(username="demo.officer", password_hash="!", role="officer", is_active=False)
    db.add(actor)
    db.flush()
    today, now = nairobi_today(), utcnow()
    people = {k: {**p, "joined_on": seed_demo.months_ago(p["joined"])} for k, p in seed_demo.SELF_SERVICE_PEOPLE.items()}
    plan = seed_members.generate([], "fixed", people, [], today, now, random.Random(seed_members.SEED))
    members: dict = {}
    seed_members.write_plan(db, plan, members, {"officer1": actor, "officer2": actor}, None, actor, now, "demo",
                            seed_demo.ensure_member)
    return members


def show(title: str, ev: Evaluation) -> None:
    w = ev.worked
    print(f"\n--- {title}")
    print(f"outcome      {ev.outcome}" + (f"  KSh {ev.amount_kes:,}" if ev.amount_kes else ""))
    print(f"reason       {ev.reason}")
    print(f"questions    {ev.questions or 'none'}")
    print(f"risk class   {ev.risk_class}  {ev.probabilities}")
    print(f"maximums     rule KSh {w.rule_max_kes:,}  affordable "
          f"{'unknown' if w.affordable_max_kes is None else f'KSh {w.affordable_max_kes:,}'}")
    if ev.instalment_kes:
        print(f"instalment   KSh {ev.instalment_kes:,} a month for {ev.facts.term_months} months")
    print("SHAP         " + ", ".join(f"{c['feature']} {c['shap']:+.3f}" for c in ev.contributions[:5]))
    failed = [c["check"] for c in ev.trace["checks"] if c["passed"] is False]
    print(f"failed       {failed or 'no check'}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    init_db()
    with SessionLocal() as db:
        members = build(db)
        print("Wanjiru Kamau asks for KSh 40,000 for a dairy cow, and gives no term.")
        show("before", evaluate(db, members["wanjiru"], DAIRY))
        show("after answering C1: 12 months", evaluate(db, members["wanjiru"], DAIRY, {"term_months": 12}))
        print("\nNjeri Mwangi asks for KSh 60,000 for school fees over 12 months. "
              "Her profile says KSh 10,000 a month, entered 240 days ago and never checked.")
        show("before", evaluate(db, members["njeri"], SCHOOL))
        show("after answering C2: KSh 30,000 a month", evaluate(db, members["njeri"], SCHOOL, {"monthly_income_kes": 30000}))
        show("after accepting the offer", evaluate(db, members["njeri"], SCHOOL,
                                                   {"monthly_income_kes": 30000, "accepted_amount_kes": 45000}, final=True))


if __name__ == "__main__":
    main()
