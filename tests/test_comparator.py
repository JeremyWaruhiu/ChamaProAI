"""The SACCO rule from Chapter 5 beside the model: savings x 3, two guarantors,
six months' membership."""
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest

from chamapro.api import comparator as cmp


def application(amount=30000, savings=10000, joined=date(2020, 1, 1), applied=date(2026, 10, 1),
                guarantors=(), mode="live"):
    return NS(amount_requested_kes=amount, sacco_savings_kes=savings,
              member=NS(joined_on=joined),
              created_at=datetime(applied.year, applied.month, applied.day, tzinfo=timezone.utc),
              guarantors=[NS(status=s) for s in guarantors], interview=NS(mode=mode))


def conditions(c):
    return {x.name: x for x in c.conditions}


@pytest.mark.parametrize("start, end, months", [
    (date(2026, 4, 1), date(2026, 10, 1), 6), (date(2026, 4, 2), date(2026, 10, 1), 5),
    (date(2025, 10, 31), date(2026, 4, 30), 5), (date(2026, 10, 2), date(2026, 10, 1), 0),
    (date(2020, 1, 15), date(2026, 10, 15), 81)])
def test_months_between(start, end, months):
    assert cmp.months_between(start, end) == months


def test_maximum_borrowable_is_three_times_savings():
    assert conditions(cmp.evaluate(application(30000, 10000), "Low"))["savings_multiple"].result == "pass"
    c = cmp.evaluate(application(30001, 10000), "Low")
    assert c.max_borrowable_kes == 30000 and conditions(c)["savings_multiple"].result == "fail"


def test_tenure_counts_from_joining_to_the_application():
    ok = cmp.evaluate(application(joined=date(2026, 4, 1), applied=date(2026, 10, 1)), "Low")
    short = cmp.evaluate(application(joined=date(2026, 4, 2), applied=date(2026, 10, 1)), "Low")
    assert (conditions(ok)["tenure"].result, ok.tenure_months) == ("pass", 6)
    assert (conditions(short)["tenure"].result, short.tenure_months) == ("fail", 5)


@pytest.mark.parametrize("statuses, result", [
    ((), "pending"),                              # before any are submitted: pending, not failed
    (("pending", "pending"), "pending"),
    (("verified", "pending"), "pending"),
    (("verified", "verified"), "pass"),
    (("verified", "rejected"), "fail"),
    (("rejected", "rejected", "verified", "verified"), "pass")])
def test_guarantor_condition(statuses, result):
    c = cmp.evaluate(application(guarantors=statuses), "Low")
    assert conditions(c)["guarantors"].result == result


@pytest.mark.parametrize("risk, model, agreement", [("Low", "approve", "agree"),
                                                    ("Medium", "refer", "undetermined"),
                                                    ("High", "decline", "diverge")])
def test_rule_met_but_for_guarantors(risk, model, agreement):
    c = cmp.evaluate(application(), risk)
    assert c.result == "pending" and c.rule_recommendation == "approve_with_guarantors"
    assert (c.model_recommendation, c.agreement) == (model, agreement)
    by = conditions(c)
    assert by["guarantors"].agreement == "pending"
    assert by["savings_multiple"].agreement == agreement


def test_a_failed_condition_declines_and_agrees_with_high_risk():
    c = cmp.evaluate(application(amount=99999), "High")
    assert (c.result, c.rule_recommendation, c.agreement) == ("fail", "decline", "agree")
    assert conditions(c)["savings_multiple"].agreement == "agree"
    assert conditions(c)["tenure"].agreement == "diverge"       # tenure passed; model declined


def test_everything_passes():
    c = cmp.evaluate(application(guarantors=("verified", "verified")), "Low")
    assert (c.result, c.rule_recommendation, c.agreement) == ("pass", "approve", "agree")


def test_tenure_uses_the_date_in_kenya():
    app = application(joined=date(2026, 4, 1), applied=date(2026, 9, 30))
    app.created_at = datetime(2026, 9, 30, 21, 30, tzinfo=timezone.utc)   # 00:30 on 1 Oct in Nairobi
    assert cmp.evaluate(app, "Low").tenure_months == 6


def test_practice_mode_is_reported():
    assert cmp.evaluate(application(mode="practice"), "Low").mode == "practice"
