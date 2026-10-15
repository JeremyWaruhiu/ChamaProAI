"""Fit the selected classifier and save it for inference.

Uses the same encoding and training protocol as experiments/03_classifier/model.py
by importing encode() from it, so the saved model matches the reported results.

    python scripts/train_and_save.py
    python scripts/train_and_save.py --estimator random_forest
    python scripts/train_and_save.py --frame .../modelling_frame_suspect.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "03_classifier"))
from model import DEFAULT_FRAME, RISK, encode  # noqa: E402

OUT = ROOT / "models"

ESTIMATORS = {
    "random_forest": lambda s: RandomForestClassifier(
        n_estimators=500, min_samples_leaf=5,
        class_weight="balanced_subsample", n_jobs=-1, random_state=s),
    "hist_gradient_boosting": lambda s: HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06,
        class_weight="balanced", random_state=s),
}

ap = argparse.ArgumentParser()
ap.add_argument("--frame", default=str(DEFAULT_FRAME))
ap.add_argument("--estimator", default="hist_gradient_boosting",
                choices=list(ESTIMATORS))
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--all-rows", action="store_true",
                help="train on every row; default holds out Central Kenya "
                     "to match the reported evaluation protocol")
a = ap.parse_args()

frame = Path(a.frame)
if not frame.exists():
    raise SystemExit(f"frame not found: {frame}\nRun experiments/02_finaccess_prep/prep.py first")

df = pd.read_csv(frame, low_memory=False)
X, y3, central = encode(df)

if a.all_rows:
    Xtr, ytr, protocol = X, y3, "all_rows"
else:
    idx = X.index[~central]
    Xtr, ytr, protocol = X.loc[idx], y3.loc[idx], "central_kenya_held_out"

print(f"training {a.estimator} on {len(Xtr)} rows, {X.shape[1]} features ({protocol})")
m = ESTIMATORS[a.estimator](a.seed)
m.fit(Xtr, ytr)

OUT.mkdir(parents=True, exist_ok=True)
joblib.dump(m, OUT / "classifier.joblib")

meta = {
    "estimator": a.estimator,
    "frame": frame.name,
    "protocol": protocol,
    "seed": a.seed,
    "n_train": int(len(Xtr)),
    "n_features": int(X.shape[1]),
    "feature_order": list(X.columns),
    "classes": {str(k): v for k, v in RISK.items()},
    "trained_on": date.today().isoformat(),
}
(OUT / "classifier_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

print(f"saved  {OUT / 'classifier.joblib'}")
print(f"saved  {OUT / 'classifier_meta.json'}")
print(f"\nfeature contract: {X.shape[1]} columns, first 8:")
for c in list(X.columns)[:8]:
    print(f"  {c}")
