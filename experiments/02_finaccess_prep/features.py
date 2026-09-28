"""Feature specification for the ChamaPro AI credit-scoring model.

Every variable named here was verified to exist in
`2024_Finaccess_Publicdata.dta` (20,871 rows x 3,816 variables) on
28 September 2026. Groups mirror the domains of the structured interview
instrument, so each model feature traces back to a question a SACCO loan
officer can actually ask.
"""

TARGET = "E2E"

# E2E is an ordinal default outcome. Higher ordinal = higher credit risk.
# Wording: "In the past 12 months did you pay any of your loans late, miss a
# payment, pay less, or not pay at all?"
TARGET_MAP = {
    "I did not default/always pay on time": 0,  # Low    -> approve, standard terms
    "Paid late/Missed a payment/Paid less": 1,  # Medium -> reduced amount / extra guarantor
    "Didn't pay at all":                    2,  # High   -> decline / refer to committee
}
RISK_LABELS = {0: "Low", 1: "Medium", 2: "High"}

# Blank E2E means the respondent did not borrow -- filter, never impute.
# "Don't know" / "Refused to Answer" are dropped (40 rows nationally).
UNLABELLED = {"Don't know", "Don’t know", "Refused to Answer"}

CENTRAL_KENYA = ["Kiambu", "Murang'a", "Kirinyaga", "Nyeri", "Nyandarua"]

# --- Features, by interview domain -----------------------------------------

DEMOGRAPHIC = ["A18", "Sex", "A20", "A21", "NHM", "A22i", "A22ii", "A22iii"]

# B3A is a multi-select income-source battery. 1-10 are sources, 11 is
# "None of these" (informative: no income source at all). 98/99 are
# don't-know / refused and are dropped.
INCOME = [f"B3A__{i}" for i in range(1, 12)] + ["Q1"]

ASSETS = [f"B1L__{i}" for i in range(1, 7)]

# Non-monetary savings holdings: land/buildings, livestock, jewellery,
# digital assets, agroforestry. F1__96 ("other") is dropped as uninterpretable.
SAVINGS = [f"F1__{i}" for i in (1, 2, 3, 4, 5)]

# SACCO / chama relationship kept as features, not filters: filtering to SACCO
# borrowers alone leaves only a few hundred rows.
CREDIT_RELATIONSHIP = ["C1_17", "C1_21"]

# Guarantor exposure -- social capital. Concerns loans the respondent
# guaranteed for OTHERS, so it is not an echo of their own default.
GUARANTOR = ["E3B__3", "E3B__7"]

FEATURES = DEMOGRAPHIC + INCOME + ASSETS + SAVINGS + CREDIT_RELATIONSHIP + GUARANTOR

# --- Excluded on leakage grounds -------------------------------------------
# Kept as an explicit, documented list rather than silently omitted: an
# examiner should be able to see the decision and the reason.

LEAKAGE_EXCLUDED = {
    "defaulted":
        "Derived binary variable that does not reconcile with E2E and whose "
        "derivation is undocumented in the file. Using it would be circular.",
    **{f"E2F__{i}":
        "Records WHICH loan was defaulted. Derived from the same default "
        "event as the target -- direct leakage."
       for i in list(range(1, 22)) + [96]},
}

# Defensible either way, so excluded by default and testable with
# --include-suspect. Report the sensitivity result rather than asserting.
SUSPECT = {
    "E1":
        "Loan denial in the last 12 months may be a CONSEQUENCE of default "
        "rather than a predictor of it.",
    "E3__13":
        "CRB negative listing is frequently an administrative record OF the "
        "default being predicted.",
    "managedebt_perception":
        "Self-reported perception of managing existing debt is close to "
        "tautological with the target.",
    "B1G":
        "Debt-burden perception, same tautology risk as above.",
    "B1H":
        "Emergency-funds access is measured contemporaneously; direction of "
        "causation with default is not established.",
    "B1Ii":
        "Ability to raise KSh 13,000 in 30 days, same concern as B1H.",
}

WEIGHTS = ["indWeight", "hhWeight"]
