"""About 150 generated members for the demo database (seed_demo.py --demo-db), and
the ledger, loans and guarantors of the demo's named people.

Where the profiles come from. Central Kenya FinAccess respondents, read through
the existing pipeline: experiments/02_finaccess_prep (the labelled frame, or
prep.py on the .dta if the frame has not been built) and encode() in
experiments/03_classifier/model.py, so a value here is the value the classifier
was trained on. Only feature columns are read: E2E, risk_class and risk_label are
left out of the frame's usecols, so the outcome cannot influence anything below.
No county or respondent number is stored. If those files are absent, as in CI,
synthetic_respondents() draws the same fields and the run says so.

No member is one respondent. Respondents are put in strata, income band x
household-size band, and each member takes each field group from a different
respondent of one stratum, chosen by the fixed seed (compose_members):

    Group       Fields
    ----------  --------------------------------------------------------------
    personal    age, sex, education, marital status
    household   household size, children, under five, in school
    income      monthly income, farm income, income sources
    assets      non-monetary savings
    purchases   purchases in the last 12 months
    borrowing   SACCO and chama loan use, lost as guarantor

So the figures that belong together stay together, the mix of households and
incomes stays the survey's, and no row of the licensed microdata is reproduced. A
stratum of fewer than six respondents is not drawn from, and a member who happens
to match a real respondent's whole row is drawn again.

    Field               Rule
    ------------------  -----------------------------------------------------------
    names               invented: first names by the respondent's sex, surnames from
                        a fixed list, each pair used once
    phones              0700 000 101 upwards, the block the demo's people already use
    member numbers      M-2001 upwards
    date of birth       the respondent's age; month and day drawn
    membership          long enough for the loans below and six months' saving before
                        the first; members with no loan 3 to 120 months, so a few are
                        short of the SACCO rule's six months
    monthly deposits    4-10% of monthly income, rounded to KSh 50, at least 200 (KSh
                        300-800 where income is missing), varying +/-20%
    gaps                a month is missed with probability 0.06 (income from 15,000),
                        0.12 (from 5,000) or 0.22 (below, or unknown), and a gap runs
                        one to three months
    share capital       KSh 1,000-5,000 in one to three instalments on joining
    dividends           each March, 8-12% of share capital, to the transactional
                        account and drawn out the next day
    sacco_loan_use 0    no loan
    sacco_loan_use 1    one repaid loan, sometimes two
    sacco_loan_use 2    one loan still owed, sometimes after an earlier repaid one;
                        about one in eight is defaulted, drawn at random, and a quarter
                        of the active ones are one to three instalments behind
    loan size           one to three times deposits when it was paid out, capped so the
                        instalment is at most half of income; 1% a month, flat
    repayments          each instalment comes into the transactional account and goes
                        out to the loan; the payout is drawn out the next day
    lost_as_guarantor   a respondent who lost money guaranteeing a SACCO loan guarantees
      .sacco            a defaulted loan and has a guarantee_recovery from deposits
    active guarantees   two guarantors per active loan, each for half, who must have the
                        capacity; a loan too large for anyone left is made smaller
    standing guarantors two or three pledges per member, each from a member with at
                        least KSh 1,000 of capacity left over
    verification        each field group: verified by an officer with probability 0.6,
                        otherwise source "seed" and unverified
    last confirmed      0 to 400 days ago; each group was last set then

A fixed random seed (SEED) and the date given decide everything, so the same day
gives the same members. Every derived feature agrees with the respondent's answer
by construction, and tests/test_member_database.py checks that it does.

The named people keep what they had. Their deposits are built backwards from their
applications, so the balance on the day each was decided is the savings figure it
was decided on, and the rule beside it reads the same. Their loans follow their
sacco_loan_use. Peter's approved application is the one that has been paid out,
which is why the demo shows an application linked to a loan.
"""
from __future__ import annotations

import importlib
import json
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.orm import Session

from chamapro import config
from chamapro.api import audit, ledger, profiles
from chamapro.api.db import (AccountEntry, Guarantor, GuarantorPledge, LoanAccount, LoanApplication, Member,
                             MemberAccount, MemberProfile, PROFILE_GROUPS, User)
from chamapro.api.ledger import add_months, day_stamp

SEED = 20261104
MEMBERS = 150
FIRST_PHONE, FIRST_MEMBER_NO = 101, 2001
MIN_PLEDGE_CAPACITY = 1000
VERIFIED_SHARE = 0.6
MONTHLY_INTEREST = 0.01
MARITAL = {"marital_married": "married", "marital_single": "single",
           "marital_widowed": "widowed", "marital_divorced": "divorced"}
INCOME_SOURCES = ["farming", "employed", "casual_worker", "own_business", "social_transfer", "renting_out",
                  "investments", "pension", "remittances", "other", "none"]
SAVINGS = ["land_or_buildings", "livestock", "jewellery", "digital_assets", "agroforestry"]
PURCHASES = ["land_or_plot", "new_house", "house_materials", "business_equipment", "farm_equipment",
             "livestock"]
FEMALE = ["Agnes", "Anne", "Beatrice", "Catherine", "Dorcas", "Eunice", "Florence", "Gladys", "Hannah", "Irene",
          "Jane", "Joyce", "Lucy", "Margaret", "Miriam", "Nancy", "Priscah", "Purity", "Rose", "Ruth", "Susan",
          "Teresia", "Virginia", "Winnie"]
MALE = ["Anthony", "Benson", "Charles", "Daniel", "Edward", "Francis", "George", "Henry", "Isaac", "James",
        "Kennedy", "Lawrence", "Martin", "Michael", "Nicholas", "Patrick", "Paul", "Robert", "Simon", "Stephen",
        "Timothy", "Vincent", "Wilson", "Zachary"]
SURNAMES = ["Gachanja", "Gathoni", "Githinji", "Kagwi", "Kamande", "Kanyi", "Karanja", "Kimani", "Kinyua",
            "Macharia", "Maina", "Mbugua", "Muchiri", "Mugo", "Muiruri", "Mungai", "Muriithi", "Mwaura", "Ndegwa",
            "Nderitu", "Ndungu", "Ngugi", "Njenga", "Njuguna", "Thuo", "Wachira", "Wainaina", "Waithaka", "Waweru"]


# --- Who: FinAccess respondents, or the synthetic stand-in ----------------------------------

def _experiments():
    """experiments/02 and 03 are scripts, imported the way export_results.py does."""
    for folder in ("02_finaccess_prep", "03_classifier"):
        path = str(config.EXPERIMENTS_DIR / folder)
        if path not in sys.path:
            sys.path.insert(0, path)
    return importlib.import_module("features"), importlib.import_module("prep"), importlib.import_module("model")


def _respondent(row) -> dict:
    """One encoded row as the keys score_interview takes. A count the survey left
    blank stays None; the classifier's own fills (no children, no farm income)
    are already in the encoded row."""
    def whole(name):
        v = row[name]
        return None if v != v else int(round(float(v)))     # NaN is not equal to itself

    def flags(prefix, keys):
        return {k: int(row[f"{prefix}__{i}"]) for i, k in enumerate(keys, 1)}

    marital = next((v for k, v in MARITAL.items() if row[k]), None)
    return {
        "form": {"age": whole("age"), "sex": "female" if row["is_female"] else "male",
                 "education": None if row["education"] < 0 else int(row["education"]), "marital_status": marital},
        "features": {
            "household_size": whole("household_size"), "children": whole("children"),
            "children_under5": whole("children_under5"), "children_in_school": whole("children_in_school"),
            "monthly_income_kes": None if row["income_missing"] else int(round(math.expm1(row["log_monthly_income"]))),
            "agri_income_kes": int(round(math.expm1(row["log_agri_income"]))),
            "income_sources": flags("B3A", INCOME_SOURCES), "non_monetary_savings": flags("F1", SAVINGS),
            "purchases_last_12m": flags("B1L", PURCHASES),
            "lost_as_guarantor": {"sacco": int(row["E3B__3"]), "chama": int(row["E3B__7"])},
            "sacco_loan_use": int(row["sacco_loan_use"]), "chama_loan_use": int(row["chama_loan_use"])},
    }


def load_central_respondents() -> list[dict] | None:
    """Every Central Kenya respondent, features only; None if the files are absent."""
    try:
        features, prep, model = _experiments()
    except ImportError:
        return None
    wanted = [*features.FEATURES, "county"]
    if model.DEFAULT_FRAME.is_file():
        import pandas as pd
        df = pd.read_csv(model.DEFAULT_FRAME, usecols=wanted, low_memory=False)
    elif prep.DTA.is_file():
        df = prep.build(prep.load(False))[wanted]
    else:
        return None
    df = df[df["county"].isin(features.CENTRAL_KENYA)]
    # encode() also returns the label and region; neither was read, so it is given placeholders.
    encoded, _, _ = model.encode(df.assign(risk_class=0, is_central=True))
    encoded = encoded[encoded["age"].notna()]
    return [_respondent(row) for _, row in encoded.iterrows()]


def synthetic_respondents(n: int, rng: random.Random) -> list[dict]:
    """The same fields, drawn at plausible rates, for machines without FinAccess."""
    out = []
    for _ in range(n):
        children = rng.choices(range(6), [20, 20, 25, 20, 10, 5])[0]
        under5 = rng.randint(0, min(children, 2))
        income = None if rng.random() < 0.1 else int(rng.lognormvariate(9.2, 0.8))
        farming = rng.random() < 0.55
        sources = dict.fromkeys(INCOME_SOURCES, 0)
        sources[rng.choice(INCOME_SOURCES[:9])] = 1
        sources["farming"] = int(farming)
        out.append({
            "form": {"age": rng.randint(21, 72), "sex": "female" if rng.random() < 0.55 else "male",
                     "education": rng.choices(range(9), [5, 12, 22, 12, 25, 6, 10, 3, 5])[0],
                     "marital_status": rng.choices(list(MARITAL.values()), [62, 20, 12, 6])[0]},
            "features": {
                "household_size": children + rng.randint(1, 3), "children": children, "children_under5": under5,
                "children_in_school": rng.randint(0, children - under5),
                "monthly_income_kes": income, "agri_income_kes": int((income or 0) * rng.uniform(0.2, 0.7)) if farming else 0,
                "income_sources": sources,
                "non_monetary_savings": {k: int(rng.random() < 0.3) for k in SAVINGS},
                "purchases_last_12m": {k: int(rng.random() < 0.1) for k in PURCHASES},
                "lost_as_guarantor": {"sacco": int(rng.random() < 0.05), "chama": int(rng.random() < 0.08)},
                "sacco_loan_use": rng.choices((0, 1, 2), [60, 25, 15])[0],
                "chama_loan_use": rng.choices((0, 1, 2), [50, 25, 25])[0]},
        })
    return out


# --- No member is one respondent ---------------------------------------------------------

FIELD_GROUPS = {"household": ("household_size", "children", "children_under5", "children_in_school"),
                "income": ("monthly_income_kes", "agri_income_kes", "income_sources"),
                "assets": ("non_monetary_savings",),
                "purchases": ("purchases_last_12m",),
                "borrowing": ("sacco_loan_use", "chama_loan_use", "lost_as_guarantor")}
DONORS = len(FIELD_GROUPS) + 1      # one for each group, and one for the personal form


def income_band(income: int | None) -> str:
    if income is None:
        return "unknown"
    return "under 5,000" if income < 5000 else "5,000-14,999" if income < 15000 \
        else "15,000-29,999" if income < 30000 else "30,000 and over"


def household_band(size: int | None) -> str:
    if size is None:
        return "unknown"
    return "1-2" if size <= 2 else "3-4" if size <= 4 else "5-6" if size <= 6 else "7 and over"


def stratum(r: dict) -> tuple[str, str]:
    return income_band(r["features"]["monthly_income_kes"]), household_band(r["features"]["household_size"])


def row_key(r: dict) -> str:
    return json.dumps([r["form"], r["features"]], sort_keys=True)


def compose_members(everyone: list[dict], n: int, rng: random.Random) -> list[dict]:
    """n members in the survey's proportions of strata, each with every field group
    from a different respondent of its stratum. Deterministic for a given rng."""
    strata: dict[tuple[str, str], list[dict]] = {}
    for r in everyone:
        strata.setdefault(stratum(r), []).append(r)
    usable = {k: v for k, v in sorted(strata.items()) if len(v) >= DONORS}
    if not usable:
        raise ValueError(f"no stratum has the {DONORS} respondents a member needs")
    real = {row_key(r) for r in everyone}
    bands, sizes = zip(*((k, len(v)) for k, v in usable.items()))
    out = []
    for band in rng.choices(bands, weights=sizes, k=n):
        while True:
            person, *donors = rng.sample(usable[band], DONORS)
            features = {f: donor["features"][f] for donor, fields in zip(donors, FIELD_GROUPS.values()) for f in fields}
            member = {"form": person["form"], "features": features}
            if row_key(member) not in real:
                out.append(member)
                break
    return out


def choose_respondents(n: int, rng: random.Random, log=print) -> tuple[list[dict], str]:
    """(n members' fields, where they came from). The label is never among what is read."""
    everyone = load_central_respondents()
    if not everyone:
        log("FinAccess files absent: members generated by the synthetic generator instead")
        return synthetic_respondents(n, rng), "synthetic"
    log(f"members composed from {len(everyone):,} Central Kenya FinAccess respondents (features only; "
        "no member is one respondent)")
    return compose_members(everyone, n, rng), "finaccess"


# --- The plan: plain data, so the same seed can be compared without a database ---------------

@dataclass
class Loan:
    key: str
    owner: str
    principal: int
    disbursed_on: date
    term: int
    status: str = "active"
    paid_instalments: int = 0
    guarantors: list[tuple[str, int]] = field(default_factory=list)   # (person key, amount)

    @property
    def instalment(self) -> int:
        total = self.principal * (1 + MONTHLY_INTEREST * self.term)
        return int(math.ceil(total / self.term / 10) * 10)


@dataclass
class Person:
    key: str
    member_no: str
    full_name: str
    phone: str
    joined_on: date
    born: date
    form: dict
    features: dict
    # (account kind, entry type, signed amount, day, reference, loan key or None)
    entries: list[tuple] = field(default_factory=list)
    loans: list[Loan] = field(default_factory=list)
    pledges: list[str] = field(default_factory=list)    # keys of those who pledge to guarantee them
    verified: list[str] = field(default_factory=list)   # field groups an officer has checked
    verifier: str = "officer1"
    confirmed_days_ago: int = 0
    # A group last changed before the last confirmation; others were set by then.
    updated_days_ago: dict[str, int] = field(default_factory=dict)

    def deposits(self, upto: date | None = None) -> int:
        return sum(e[2] for e in self.entries if e[0] == "deposits" and (upto is None or e[3] <= upto))


@dataclass
class Plan:
    people: list[Person]
    source: str
    today: date

    def by_key(self) -> dict[str, Person]:
        return {p.key: p for p in self.people}

    def loans(self) -> list[Loan]:
        return [x for p in self.people for x in p.loans]


def fifty(amount: float) -> int:
    return max(int(round(amount / 50) * 50), 50)


def birth_date(age: int, today: date, rng: random.Random) -> date:
    """A birthday already past this year, so age_on(...) gives exactly age."""
    return add_months(today, -(age * 12) - rng.randint(1, 11))


def month_starts(first: date, today: date, day: int) -> list[date]:
    """That day of each month from first up to today."""
    out, n = [], 0
    while (d := add_months(first.replace(day=1), n)) <= today:
        d = d.replace(day=day)
        if first <= d <= today:
            out.append(d)
        n += 1
    return out


def monthly_rate(income: int | None, rng: random.Random) -> int:
    if income is None:
        return rng.choice((300, 500, 800))
    return max(fifty(income * rng.uniform(0.04, 0.10)), 200)


def miss_rate(income: int | None) -> float:
    return 0.06 if income and income >= 15000 else 0.12 if income and income >= 5000 else 0.22


def add_deposits(p: Person, rng: random.Random, today: date) -> None:
    income = p.features["monthly_income_kes"]
    rate, miss, gap = monthly_rate(income, rng), miss_rate(income), 0
    for d in month_starts(p.joined_on, today, rng.randint(1, 28)):
        if gap:
            gap -= 1
            continue
        if rng.random() < miss:
            gap = rng.choices((0, 1, 2), (6, 3, 1))[0]
            continue
        p.entries.append(("deposits", "deposit", fifty(rate * rng.uniform(0.8, 1.2)), d, f"DEP-{d:%Y%m}", None))


def add_share_capital(p: Person, rng: random.Random, today: date, total: int | None = None) -> None:
    total = total or rng.choice((1000, 2000, 3000, 5000))
    parts = rng.randint(1, 3)
    for i in range(parts):
        d = min(add_months(p.joined_on, i), today)
        p.entries.append(("share_capital", "deposit", total // parts, d, f"SHR-{i + 1}", None))


def add_dividends(p: Person, rng: random.Random, today: date) -> None:
    capital = sum(e[2] for e in p.entries if e[0] == "share_capital")
    for year in range(p.joined_on.year + 1, today.year + 1):
        d = date(year, 3, 15)
        amount = int(capital * rng.uniform(0.08, 0.12))
        if d <= today and amount >= 50:
            p.entries.append(("transactional", "dividend", amount, d, f"DIV-{year}", None))
            p.entries.append(("transactional", "withdrawal", -amount, d + timedelta(days=1), f"WDL-DIV-{year}", None))


def add_repaid_loan(p: Person, rng: random.Random, today: date, months_back: int, number: int) -> int:
    """A loan that ended months_back ago; returns how many months back it began."""
    term = rng.choice((6, 12, 18, 24))
    start = months_back + term
    p.loans.append(Loan(f"{p.key}-L{number}", p.key, 0, add_months(today, -start), term, "repaid", term))
    return start


def add_loans(p: Person, rng: random.Random, today: date, default_share: float = 0.12) -> int:
    """The loans sacco_loan_use says this member has, sized later. Returns how far
    back the earliest began, for the membership date."""
    use, earliest = p.features["sacco_loan_use"], 0
    if use == 1:
        earliest = add_repaid_loan(p, rng, today, rng.randint(1, 30), 1)
        if rng.random() < 0.2:
            earliest = add_repaid_loan(p, rng, today, earliest + rng.randint(2, 12), 2)
    elif use == 2:
        if rng.random() < default_share:
            term = rng.choice((12, 18, 24))
            months = rng.randint(6, term + 6)
            paid = rng.randint(1, max(months - 5, 1))
            p.loans.append(Loan(f"{p.key}-L1", p.key, 0, add_months(today, -months), term, "defaulted", min(paid, term)))
        else:
            term = rng.choice((6, 12, 18, 24))
            months = rng.randint(1, term - 1)
            behind = rng.randint(1, 3) if rng.random() < 0.25 else 0
            p.loans.append(Loan(f"{p.key}-L1", p.key, 0, add_months(today, -months), term, "active",
                                max(months - behind, 0)))
        earliest = months
        if rng.random() < 0.25:
            earliest = add_repaid_loan(p, rng, today, months + rng.randint(2, 12), 2)
    return earliest


def size_loans(p: Person, rng: random.Random) -> None:
    """One to three times deposits when paid out, instalment at most half of income.
    A top-up just before the payout makes sure the rule's three times holds."""
    income = p.features["monthly_income_kes"]
    for x in p.loans:
        held = p.deposits(x.disbursed_on)
        amount = max(fifty(held * rng.uniform(1, 3) / 10) * 10, 2000)
        if income:
            amount = max(min(amount, int(income * 0.5 * x.term / (1 + MONTHLY_INTEREST * x.term))), 2000)
        x.principal = fifty(amount)
        if x.principal > held * 3:
            p.entries.append(("deposits", "deposit", -(-(x.principal - held * 3) // 3),
                              x.disbursed_on - timedelta(days=2), f"TOPUP-{x.key}", None))


def add_loan_entries(p: Person, x: Loan, rng: random.Random, today: date) -> None:
    p.entries.append(("transactional", "loan_disbursement", x.principal, x.disbursed_on, f"LOAN-{x.key}", x.key))
    p.entries.append(("transactional", "withdrawal", -x.principal, x.disbursed_on + timedelta(days=1),
                      f"WDL-{x.key}", None))
    for k in range(1, x.paid_instalments + 1):
        d = min(add_months(x.disbursed_on, k) + timedelta(days=rng.randint(-3, 5)), today)
        p.entries.append(("transactional", "deposit", x.instalment, d, f"PAYIN-{x.key}-{k}", None))
        p.entries.append(("transactional", "loan_repayment", -x.instalment, d, f"RPY-{x.key}-{k}", x.key))


def recover_losses(people: list[Person], rng: random.Random, today: date, default_loan: Loan | None) -> None:
    """Everyone whose answer says they lost money guaranteeing a SACCO loan: a
    guarantee on a defaulted loan, and its recovery from their deposits."""
    losers = [p for p in people if p.features["lost_as_guarantor"]["sacco"]]
    defaulted = [x for p in people for x in p.loans if x.status == "defaulted"]
    if default_loan is not None:
        defaulted.append(default_loan)
    for p in losers:
        x = next((y for y in rng.sample(defaulted, len(defaulted)) if y.owner != p.key), None)
        if x is None:
            continue
        when = max(add_months(p.joined_on, 3), x.disbursed_on + timedelta(days=120))
        when = min(when, today - timedelta(days=7))
        held = p.deposits(when)
        amount = fifty(max(held * rng.uniform(0.1, 0.3), 100))
        if amount > held:
            p.entries.append(("deposits", "deposit", amount - held, when - timedelta(days=1), f"TOPUP-REC-{x.key}", None))
        p.entries.append(("deposits", "guarantee_recovery", -amount, when, f"REC-{x.key}", x.key))
        x.guarantors.append((p.key, amount))


def guarantee_active_loans(people: list[Person], rng: random.Random) -> dict[str, int]:
    """Two guarantors for each active loan, the largest first, from among these
    people. A loan too large for anyone left is made smaller. Returns what each
    member has left."""
    left = {p.key: p.deposits() for p in people}
    active = sorted((x for p in people for x in p.loans if x.status == "active"),
                    key=lambda x: (-x.principal, x.key))
    for x in active:
        others = sorted((p.key for p in people if p.key != x.owner), key=lambda k: (-left[k], k))[:30]
        rng.shuffle(others)
        share = -(-x.principal // 2)
        chosen = [k for k in others if left[k] >= share][:2]
        if len(chosen) < 2:
            ranked = sorted((p.key for p in people if p.key != x.owner), key=lambda k: (-left[k], k))
            chosen = ranked[:2]
            x.principal = fifty(max(2 * min(left[k] for k in chosen), 2000))
            share = -(-x.principal // 2)
        for k in chosen:
            x.guarantors.append((k, share))
            left[k] -= share
    return left


def add_pledges(people: list[Person], left: dict[str, int], rng: random.Random) -> None:
    able = [k for k in sorted(left) if left[k] >= MIN_PLEDGE_CAPACITY]
    for p in people:
        pool = [k for k in able if k != p.key]
        p.pledges = rng.sample(pool, min(rng.randint(2, 3), len(pool)))


def verification(p: Person, rng: random.Random) -> None:
    p.verified = [g for g in PROFILE_GROUPS if rng.random() < VERIFIED_SHARE]
    p.verifier = rng.choice(("officer1", "officer2"))
    p.confirmed_days_ago = rng.randint(0, 400)


def invented_names(forms: list[dict], rng: random.Random) -> list[str]:
    """One full name per person, first name by sex, no pair used twice."""
    used, out = set(), []
    for form in forms:
        firsts = FEMALE if form["sex"] == "female" else MALE
        while True:
            name = f"{rng.choice(firsts)} {rng.choice(SURNAMES)}"
            if name not in used:
                used.add(name)
                out.append(name)
                break
    return out


def bulk_people(respondents: list[dict], today: date, rng: random.Random) -> list[Person]:
    names = invented_names([r["form"] for r in respondents], rng)
    people = []
    for i, (r, name) in enumerate(zip(respondents, names)):
        age = r["form"]["age"]
        p = Person(key=f"finaccess-{i + 1:04d}", member_no=f"M-{FIRST_MEMBER_NO + i}", full_name=name,
                   phone=f"0700000{FIRST_PHONE + i:03d}", joined_on=today, born=birth_date(age, today, rng),
                   form=r["form"], features=r["features"])
        earliest = add_loans(p, rng, today)
        # Saved for at least six months before the first loan; a loss needs a year.
        shortest = earliest + 7 if earliest else 12 if p.features["lost_as_guarantor"]["sacco"] else 3
        p.joined_on = add_months(today, -rng.randint(shortest, max(shortest, 120)))
        add_deposits(p, rng, today)
        add_share_capital(p, rng, today)
        add_dividends(p, rng, today)
        size_loans(p, rng)
        verification(p, rng)
        people.append(p)
    return people


# --- The named people --------------------------------------------------------------------

@dataclass(frozen=True)
class Checkpoint:
    day: date
    kes: int


def checkpoints(person_key: str, applications: list[dict], now: datetime) -> list[Checkpoint]:
    """The balance each of this person's applications must read: on the day it was
    decided, or today if it has not been."""
    out = []
    for spec in applications:
        if spec["person"] != person_key:
            continue
        if "decision" in spec:
            t0 = now - timedelta(days=spec["days_ago"], minutes=90)
            when = (t0 + timedelta(days=1)).astimezone(config.NAIROBI).date()
        else:
            when = now.astimezone(config.NAIROBI).date()
        out.append(Checkpoint(when, spec["fields"]["sacco_savings_kes"]))
    return sorted(out, key=lambda c: c.day)


def deposits_reaching(p: Person, goals: list[Checkpoint], losses: dict[date, int], today: date, day: int = 5) -> None:
    """Monthly deposits that bring the balance to each goal exactly, net of any
    recovery by then, and go on at the same rate only after a decided last one
    (an undecided application follows today's balance, which must be its figure)."""
    paid, start, rate = 0, p.joined_on, 0
    for i, goal in enumerate(goals):
        before = goal.day - timedelta(days=1)   # an entry on the decision's own day could fall after it
        months = [d for d in month_starts(start, before, day)] or [before]
        lost = sum(v for d, v in losses.items() if d <= goal.day)
        due = goal.kes + lost - paid
        if due > 0:
            each = due // len(months)
            amounts = [each] * (len(months) - 1) + [due - each * (len(months) - 1)]
            for d, amount in zip(months, amounts):
                p.entries.append(("deposits", "deposit", amount, d, f"DEP-{d:%Y%m}-{i}", None))
            paid += due
            rate = max(each, 200)
        start = goal.day + timedelta(days=1)
    if goals[-1].day < today:
        for d in month_starts(start, today, day):
            p.entries.append(("deposits", "deposit", fifty(rate), d, f"DEP-{d:%Y%m}-t", None))


# Pledges among the named people: borrower -> guarantors. The four of the automatic
# decisions pledge only to each other, so that the demo's other figures stay as they are.
NAMED_PLEDGES = {"grace": ["david", "john"], "peter": ["john", "david"], "mary": ["grace", "john"],
                 "john": ["grace", "david"], "faith": ["john", "mary"], "samuel": ["peter", "mary"],
                 "esther": ["john", "grace", "mary"], "joseph": ["grace", "peter"], "david": ["john", "grace"],
                 "wanjiru": ["lucy", "anne"], "njeri": ["lucy", "anne"], "lucy": ["wanjiru", "anne"],
                 "anne": ["lucy", "wanjiru"]}
NAMED_LOANS = {"john": dict(principal=20000, term=24, months=14, guarantors=[("grace", 10000), ("david", 10000)]),
               "grace": dict(principal=30000, term=12, months=30),
               "david": dict(principal=40000, term=18, months=26),
               "wanjiru": dict(principal=30000, term=12, months=30),
               "lucy": dict(principal=30000, term=12, months=28),
               "anne": dict(principal=20000, term=12, months=26)}


def level_deposits(p: Person, total: int, today: date, day: int = 5) -> None:
    """Deposits reaching this total by yesterday, evenly since joining."""
    months = month_starts(p.joined_on, today - timedelta(days=1), day) or [today - timedelta(days=1)]
    each = total // len(months)
    for i, d in enumerate(months):
        amount = total - each * (len(months) - 1) if i == len(months) - 1 else each
        p.entries.append(("deposits", "deposit", amount, d, f"DEP-{d:%Y%m}", None))
ESTHER_LOSS_DAYS_AGO, ESTHER_LOSS = 60, 1500


def named_people(people: dict[str, dict], applications: list[dict], today: date, now: datetime,
                 rng: random.Random, default_loan: Loan | None) -> list[Person]:
    out = []
    for key, spec in people.items():
        p = Person(key=key, member_no=spec["member_no"], full_name=spec["full_name"], phone=spec["phone"],
                   joined_on=spec["joined_on"], born=birth_date(spec["form"]["age"], today, rng),
                   form=spec["form"], features=spec["features"], pledges=list(NAMED_PLEDGES.get(key, [])))
        losses = {}
        if spec["features"]["lost_as_guarantor"]["sacco"] and default_loan is not None:
            when = today - timedelta(days=ESTHER_LOSS_DAYS_AGO)
            losses[when] = ESTHER_LOSS
            p.entries.append(("deposits", "guarantee_recovery", -ESTHER_LOSS, when, f"REC-{default_loan.key}",
                              default_loan.key))
            default_loan.guarantors.append((key, ESTHER_LOSS))
        if "deposits" in spec:
            level_deposits(p, spec["deposits"], today)
        else:
            deposits_reaching(p, checkpoints(key, applications, now), losses, today)
        add_share_capital(p, rng, today, 3000)
        if (loan := NAMED_LOANS.get(key)) is not None:
            elapsed = loan["months"]
            ended = elapsed >= loan["term"]
            x = Loan(f"{key}-L1", key, loan["principal"], add_months(today, -elapsed), loan["term"],
                     "repaid" if ended else "active", loan["term"] if ended else elapsed,
                     list(loan.get("guarantors", [])))
            p.loans.append(x)
        verification(p, rng)
        if "verified" in spec:      # people whose outcome a test pins down
            p.verified = spec["verified"]
            p.confirmed_days_ago = spec["confirmed_days_ago"]
            p.updated_days_ago = spec.get("updated_days_ago", {})
        out.append(p)
    return out


def generate(respondents: list[dict], source: str, people: dict[str, dict], applications: list[dict],
             today: date, now: datetime, rng: random.Random) -> Plan:
    """Everything to be written. Pure: the same arguments give the same plan."""
    bulk = bulk_people(respondents, today, rng)
    defaulted = next((x for p in bulk for x in p.loans if x.status == "defaulted"), None)
    if defaulted is None:       # a sample with none: the first active loan goes bad, drawn from no outcome
        x = next((y for p in bulk for y in p.loans if y.status == "active"), None)
        if x is not None:
            x.status, defaulted = "defaulted", x
    named = named_people(people, applications, today, now, rng, defaulted)
    recover_losses(bulk, rng, today, None)
    # The two groups guarantee only among themselves: the named people's figures
    # are fixed by their applications and must not be spent by a generated loan.
    add_pledges(bulk, guarantee_active_loans(bulk, rng), rng)
    everyone = bulk + named
    for p in everyone:
        for x in p.loans:
            add_loan_entries(p, x, rng, today)
    return Plan(everyone, source, today)


# --- Writing it ---------------------------------------------------------------------------

def write_profile(db: Session, m: Member, p: Person, verifiers: dict[str, User], now: datetime) -> None:
    f = p.features
    values = {"date_of_birth": p.born, **{k: p.form[k] for k in ("sex", "education", "marital_status")},
              **{k: f[k] for k in ("household_size", "children", "children_under5", "children_in_school",
                                   "monthly_income_kes", "agri_income_kes", "chama_loan_use")},
              "income_sources": {k: int(f["income_sources"].get(k, 0)) for k in INCOME_SOURCES},
              "non_monetary_savings": {k: int(f["non_monetary_savings"].get(k, 0)) for k in SAVINGS},
              "purchases_last_12m": {k: int(f["purchases_last_12m"].get(k, 0)) for k in PURCHASES},
              "lost_as_guarantor_chama": f["lost_as_guarantor"]["chama"]}
    row = MemberProfile(member=m, created_at=now, updated_at=now,
                        confirmed_at=now - timedelta(days=p.confirmed_days_ago), **values)
    officer = verifiers[p.verifier]
    for g in PROFILE_GROUPS:
        verified = g in p.verified
        setattr(row, f"{g}_source", "officer_verified" if verified else "seed")
        setattr(row, f"{g}_updated_at", now - timedelta(days=p.updated_days_ago.get(g, p.confirmed_days_ago)))
        setattr(row, f"{g}_verified_by", officer.username if verified else None)
        setattr(row, f"{g}_verified_at", row.confirmed_at if verified else None)
    db.add(row)
    profiles.mirror_applicant_form(m, row)
    db.flush()
    profiles.record_change(db, row, "seed", list(PROFILE_GROUPS), officer)


def write_plan(db: Session, plan: Plan, members: dict[str, Member], verifiers: dict[str, User],
               applied: LoanApplication | None, actor: User, now: datetime, tag_prefix: str, ensure_member) -> dict:
    """Commits. Members not yet in `members` are created through ensure_member."""
    today = plan.today
    for p in plan.people:
        if p.key not in members:
            members[p.key] = ensure_member(db, {"member_no": p.member_no, "full_name": p.full_name, "phone": p.phone,
                                                "joined_on": p.joined_on}, actor, None, f"{tag_prefix}:{p.key}")
    db.flush()
    for p in plan.people:
        write_profile(db, members[p.key], p, verifiers, now)

    accounts: dict[tuple[str, str], MemberAccount] = {}
    for p in plan.people:
        for kind in ("deposits", "share_capital", "transactional"):
            a = MemberAccount(member_id=members[p.key].id, kind=kind, created_at=day_stamp(p.joined_on))
            db.add(a)
            accounts[p.key, kind] = a
    db.flush()
    account_ids = {k: a.id for k, a in accounts.items()}

    loans: dict[str, LoanAccount] = {}
    for x in plan.loans():
        row = LoanAccount(member_id=members[x.owner].id, principal_kes=x.principal, disbursed_on=x.disbursed_on,
                          term_months=x.term, monthly_instalment_kes=x.instalment, status=x.status,
                          created_by=actor.id, created_at=day_stamp(x.disbursed_on),
                          updated_at=day_stamp(x.disbursed_on))
        db.add(row)
        loans[x.key] = row
    db.flush()

    rows = [{"account_id": account_ids[p.key, kind], "account_kind": kind, "entry_type": entry_type,
             "amount_kes": amount, "posted_at": day_stamp(day), "reference": reference, "created_by": actor.id,
             "loan_account_id": loans[loan_key].id if loan_key else None, "created_at": day_stamp(day)}
            for p in plan.people for kind, entry_type, amount, day, reference, loan_key in p.entries]
    if rows:
        db.execute(insert(AccountEntry), rows)

    people = plan.by_key()
    for x in plan.loans():
        for key, amount in x.guarantors:
            g = members[key]
            db.add(Guarantor(application_id=None, loan_account_id=loans[x.key].id, member_id=g.id,
                             full_name=g.full_name, member_no=g.member_no, phone=g.phone,
                             relationship_="standing guarantor", amount_guaranteed_kes=amount, status="verified",
                             submitted_at=day_stamp(x.disbursed_on), verified_by=actor.id,
                             verified_at=day_stamp(x.disbursed_on)))
    for p in plan.people:
        for key in p.pledges:
            db.add(GuarantorPledge(borrower_member_id=members[p.key].id, guarantor_member_id=members[key].id,
                                   status="active", created_at=day_stamp(max(people[key].joined_on, p.joined_on))))
    db.flush()

    # Peter's approved application is the one that has been paid out.
    if applied is not None:
        principal = applied.interview.decision.approved_amount_kes or applied.amount_requested_kes
        on = today - timedelta(days=35)
        instalment = Loan("x", "x", principal, on, applied.term_months).instalment
        loan = ledger.issue_loan(db, applied.member_id, principal, applied.term_months, instalment, on, applied, actor)
        ledger.post_entry(db, applied.member_id, "transactional", "withdrawal", -principal, f"WDL-LOAN-{loan.id}",
                          actor, day_stamp(on + timedelta(days=1)))
        ledger.post_entry(db, applied.member_id, "transactional", "deposit", instalment, f"PAYIN-LOAN-{loan.id}-1",
                          actor, day_stamp(on + timedelta(days=30)))
        ledger.record_repayment(db, loan, instalment, f"RPY-LOAN-{loan.id}-1", actor,
                                day_stamp(on + timedelta(days=30)))
    audit.record(db, actor, "seed.members", "member", None, members=len(plan.people), entries=len(rows),
                 source=plan.source)
    db.commit()
    return {"members": len(plan.people), "entries": len(rows), "loans": len(plan.loans()), "source": plan.source}
