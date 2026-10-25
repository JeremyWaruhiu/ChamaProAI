"""Reasons for members: plain words from the top SHAP factors, in the right
direction, never a feature code or a personal characteristic."""
import re

import pytest

from chamapro.api import member_text as mt

FEATURES = ["household_size", "children", "children_under5", "children_in_school",
            "log_monthly_income", "income_missing", "log_agri_income", "education",
            "sacco_loan_use", "chama_loan_use", "E3B__3", "E3B__7"] + \
           [f"B3A__{i}" for i in range(1, 12)] + [f"F1__{i}" for i in range(1, 6)] + \
           [f"B1L__{i}" for i in range(1, 7)]


def one(feature, value, shap, risk="Low"):
    return mt.reasons(risk, [{"feature": feature, "value": value, "shap": shap}])


def test_the_example_wording():
    assert one("B3A__1", 1.0, 0.3) == ["Your regular farm income counted in your favour."]


@pytest.mark.parametrize("risk, shap, favour", [("Low", 0.2, True), ("Low", -0.2, False),
                                                ("High", 0.2, False), ("High", -0.2, True),
                                                ("Medium", 0.2, False), ("Medium", -0.2, True)])
def test_direction_follows_the_predicted_class(risk, shap, favour):
    (text,) = one("log_agri_income", 9.0, shap, risk)
    assert text.endswith("in your favour.") == favour
    assert text.endswith("against your application.") != favour


@pytest.mark.parametrize("feature", FEATURES)
@pytest.mark.parametrize("value", [0.0, 1.0, 2.0, None])
def test_every_feature_has_plain_words(feature, value):
    (text,) = one(feature, value, 0.1)
    assert not re.search(r"[A-Z0-9]__\d|_", text), text          # no codes, no snake_case
    assert text[0].isupper() and text.endswith(".")


def test_personal_characteristics_are_never_reasons():
    contrib = [{"feature": f, "value": 1.0, "shap": 0.9}
               for f in ("is_female", "age", "marital_married", "marital_widowed")]
    contrib.append({"feature": "F1__2", "value": 1.0, "shap": 0.1})
    assert mt.reasons("Low", contrib) == ["Owning livestock counted in your favour."]


def test_three_largest_and_no_more():
    contrib = [{"feature": f"F1__{i}", "value": 1.0, "shap": s}
               for i, s in enumerate([0.01, -0.5, 0.3, 0.2, 0.4], 1)]
    out = mt.reasons("Low", contrib)
    assert out == ["Owning livestock counted against your application.",
                   "Owning trees counted in your favour.",
                   "Owning jewellery counted in your favour."]


def test_unavailable_shap_gives_no_reasons():
    assert mt.reasons("Low", "unavailable: ImportError: shap") == []


def test_missing_value_is_described_as_missing():
    (text,) = one("log_monthly_income", None, -0.2)
    assert text == "Not having details of your monthly household income counted against " \
                   "your application."


@pytest.mark.parametrize("outcome", ["approve", "approve_reduced", "approve_with_guarantor",
                                     "refer", "decline"])
def test_default_messages_are_plain(outcome):
    text = mt.default_message(outcome, 20000, 2)
    assert text and "_" not in text and "probab" not in text.lower()
