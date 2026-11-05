"""A member's profile: what the v2 interview questions collected, held so that
they need not be asked again.

Every change writes a member_profile_history snapshot in the same transaction.
Each field group remembers who last set it: a member's edit is saved at once as
member_update, unverified, and stays what the classifier would read until an
officer verifies it. The audit log gets group names only: it cannot be erased.

profile_features() is the bridge to the classifier: the exact dict
score_interview.score() takes, with where each value came from.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from chamapro import config

from . import audit, ledger
from . import schemas as s
from .batch import Batch
from .db import (PROFILE_GROUPS, Member, MemberProfile, MemberProfileHistory, User, nairobi_today, utcnow)
from .pipeline import score_interview

FIELD_GROUP = {f: g for g, fields in PROFILE_GROUPS.items() for f in fields}
FLAG_KEYS = {"income_sources": score_interview.INCOME_SOURCES,
             "non_monetary_savings": score_interview.SAVINGS,
             "purchases_last_12m": score_interview.PURCHASES}
# score_interview's field -> this table's column, where they are the same value.
SAME_FIELD = ("household_size", "children", "children_under5", "children_in_school",
              "monthly_income_kes", "agri_income_kes", "income_sources", "non_monetary_savings",
              "purchases_last_12m", "chama_loan_use")
FEATURE_GROUP = {f: FIELD_GROUP[f] for f in SAME_FIELD}
# In the history: asked for, not done. Nothing in the profile changed with it.
UPDATE_REQUEST = "update_request"


def age_on(born: date, today: date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def age_of(m: Member, today: date | None = None) -> int | None:
    """From the date of birth where the profile has it, else 0004's birth year."""
    today = today or nairobi_today()
    if m.profile is not None and m.profile.date_of_birth is not None:
        return age_on(m.profile.date_of_birth, today)
    return None if m.birth_year is None else today.year - m.birth_year


# --- profile_features -----------------------------------------------------------------

@dataclass(frozen=True)
class ProfileFeatures:
    features: dict                  # exactly score_interview.FIELDS' keys
    provenance: dict[str, str]      # records | declared | verified | missing
    days_since_confirmed: int | None


def _provenance(p: MemberProfile | None, group: str, value) -> str:
    if value is None:
        return "missing"
    return "verified" if p is not None and getattr(p, f"{group}_verified_at") is not None else "declared"


def profile_features(db: Session, m: Member, today: date | None = None,
                     records: tuple[list[str], bool, bool] | None = None) -> ProfileFeatures:
    """What the classifier needs about this member, and how far to trust it. records:
    ledger.known_to_the_sacco's answer, if the caller has already read it.

    The applicant form of 0004 on the member record fills in for a profile that
    lacks those four values. A member with neither a loan nor any ledger entry
    has no SACCO records to read: their sacco_loan_use and lost_as_guarantor.sacco
    are missing, not a false "never"."""
    today = today or nairobi_today()
    p = m.profile
    statuses, has_entries, lost = records if records is not None else ledger.known_to_the_sacco(db, m.id)
    on_record = bool(statuses) or has_entries

    of = lambda field: None if p is None else getattr(p, field)     # noqa: E731
    sex = of("sex") or m.sex
    education = of("education") if of("education") is not None else m.education
    marital = of("marital_status") or m.marital_status
    age = age_of(m, today)
    chama_lost = of("lost_as_guarantor_chama")
    features = {
        "age": age,
        **{f: of(f) for f in ("household_size", "children", "children_under5", "children_in_school",
                              "monthly_income_kes", "agri_income_kes", "income_sources",
                              "non_monetary_savings")},
        "education_level": education,
        "sacco_loan_use": ledger.sacco_loan_use(statuses) if on_record else None,
        "chama_loan_use": of("chama_loan_use"),
        "is_female": None if sex is None else int(sex == "female"),
        "marital_status": marital,
        "purchases_last_12m": of("purchases_last_12m"),
        "lost_as_guarantor": {"sacco": int(lost) if on_record else None, "chama": chama_lost},
    }
    # The profile's verification covers a value only if the profile holds it.
    personal = lambda field, value: _provenance(p if of(field) is not None else None,     # noqa: E731
                                                "personal", value)
    provenance = {
        "age": personal("date_of_birth", age), "education_level": personal("education", education),
        "is_female": personal("sex", sex), "marital_status": personal("marital_status", marital),
        **{f: _provenance(p, g, features[f]) for f, g in FEATURE_GROUP.items()},
        "sacco_loan_use": "records" if on_record else "missing",
        "lost_as_guarantor.sacco": "records" if on_record else "missing",
        "lost_as_guarantor.chama": _provenance(p, "credit", chama_lost),
    }
    days = None
    if p is not None and p.confirmed_at is not None:
        days = max((today - p.confirmed_at.astimezone(config.NAIROBI).date()).days, 0)
    return ProfileFeatures(features, provenance, days)


# --- Changing a profile ----------------------------------------------------------------

def _clean_flags(field: str, value: dict | None) -> dict | None:
    """Every key the classifier knows, 0 or 1; any other key is refused."""
    if value is None:
        return None
    keys = FLAG_KEYS[field]
    unknown = sorted(set(value) - set(keys))
    if unknown:
        raise HTTPException(422, f"{field}: unknown {', '.join(unknown)}")
    if any(v not in (0, 1) for v in value.values()):
        raise HTTPException(422, f"{field}: each value is 0 or 1")
    return {k: int(value.get(k, 0)) for k in keys}


def snapshot(p: MemberProfile) -> dict:
    """The row as plain JSON: dates as ISO text."""
    out = {}
    for col in MemberProfile.__table__.columns:
        v = getattr(p, col.name)
        out[col.name] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


def record_change(db: Session | Batch, p: MemberProfile, change: str, groups: list[str], actor: User | None) -> None:
    db.add(MemberProfileHistory(member_id=p.member_id, change=change, groups=groups,
                                snapshot=snapshot(p), actor_user_id=actor.id if actor else None))
    audit.record(db, actor, f"profile.{change}", "member", p.member_id, groups=groups)


def mirror_applicant_form(m: Member, p: MemberProfile) -> None:
    """The 0004 flows read the applicant form from the member record, and must see
    what the profile says: the same four values, never a different answer."""
    if p.date_of_birth is not None:
        m.birth_year = p.date_of_birth.year
    if p.sex is not None:
        m.sex = p.sex
    if p.education is not None:
        m.education = p.education
    if p.marital_status is not None:
        m.marital_status = p.marital_status


def save_profile(db: Session, m: Member, values: dict, source: str, actor: User | None,
                 now=None) -> MemberProfile:
    """Set these fields. A group whose values change takes this source and loses
    any verification; a group left as it was keeps both. Sending what is already
    there is a confirmation. The caller commits."""
    now = now or utcnow()
    p = m.profile
    if p is None:
        p = MemberProfile(member=m, created_at=now, updated_at=now)
        db.add(p)
    touched = set()
    for field, value in values.items():
        if field in FLAG_KEYS:
            value = _clean_flags(field, value)
        if getattr(p, field) != value:
            setattr(p, field, value)
            touched.add(FIELD_GROUP[field])
    groups = [g for g in PROFILE_GROUPS if g in touched]
    for g in groups:
        setattr(p, f"{g}_source", source)
        setattr(p, f"{g}_updated_at", now)
        setattr(p, f"{g}_verified_by", None)
        setattr(p, f"{g}_verified_at", None)
    p.confirmed_at = now
    if groups:
        p.updated_at = now
        mirror_applicant_form(m, p)
    db.flush()
    record_change(db, p, source if groups else "confirm", groups, actor)
    return p


def confirm_profile(db: Session, m: Member, actor: User | None) -> MemberProfile:
    """The member says it is all still right. Nothing else changes."""
    if m.profile is None:
        raise HTTPException(409, "there is no profile to confirm yet")
    m.profile.confirmed_at = utcnow()
    db.flush()
    record_change(db, m.profile, "confirm", [], actor)
    return m.profile


def confirm_groups(out: Batch, m: Member, groups: list[str], actor: User | None) -> None:
    """The member heard these groups read out and said they are still right: only these
    are fresh again, since nobody asked about the rest. No figure changes."""
    if m.profile is None or not groups:
        return
    out.update(m.profile, confirmed_at=utcnow())
    record_change(out, m.profile, "confirm", groups, actor)


def request_update(db: Session | Batch, m: Member, values: dict, conversation_id: int, actor: User | None) -> None:
    """The member told the conversation something else. The profile stays as it is and
    its verification with it; the history keeps what they asked for, for an officer to
    act on, and the audit log, which cannot be erased, keeps the group names only."""
    p = m.profile
    if p is None:
        return
    groups = [g for g in PROFILE_GROUPS if any(FIELD_GROUP[f] == g for f in values)]
    db.add(MemberProfileHistory(member_id=m.id, change=UPDATE_REQUEST, groups=groups,
                                snapshot={**snapshot(p), "requested": values, "conversation_id": conversation_id},
                                actor_user_id=actor.id if actor else None))
    audit.record(db, actor, f"profile.{UPDATE_REQUEST}", "member", m.id, groups=groups, conversation_id=conversation_id)


def holds_data(p: MemberProfile, group: str) -> bool:
    return any(getattr(p, f) is not None for f in PROFILE_GROUPS[group])


def verify_profile(db: Session, m: Member, actor: User, groups: list[str] | None = None) -> MemberProfile:
    """An officer has checked these groups, by default all that hold anything."""
    p = m.profile
    if p is None:
        raise HTTPException(409, f"member {m.id} has no profile to verify")
    chosen = [g for g in PROFILE_GROUPS if (g in groups if groups else True) and holds_data(p, g)]
    if not chosen:
        raise HTTPException(409, "those parts of the profile are empty; there is nothing to verify")
    now = utcnow()
    for g in chosen:
        setattr(p, f"{g}_source", "officer_verified")
        setattr(p, f"{g}_verified_by", actor.username)
        setattr(p, f"{g}_verified_at", now)
    p.confirmed_at = now
    db.flush()
    record_change(db, p, "officer_verified", chosen, actor)
    return p


def save_applicant_form(db: Session, m: Member, form: s.ApplicantForm, actor: User | None) -> None:
    """The 0004 applicant form, from the profile page or a first application. It
    writes the member record as before and, where there is a profile, the profile
    too: a date of birth that gives another age than the one typed no longer
    stands, and the typed age is what is left."""
    today = nairobi_today()
    p = m.profile
    keep_born = p is not None and p.date_of_birth is not None and age_on(p.date_of_birth, today) == form.age
    m.birth_year = p.date_of_birth.year if keep_born else today.year - form.age
    m.sex, m.education, m.marital_status = form.sex, form.education, form.marital_status
    if p is not None:
        save_profile(db, m, {"date_of_birth": p.date_of_birth if keep_born else None, "sex": form.sex,
                             "education": form.education, "marital_status": form.marital_status},
                     "member_update", actor)
