"""Part D1 -- baseline classifiers. Majority-class baseline comparison is
mandatory per spec (and per Section 7's go/no-go: "Beats majority-class/
naive-heuristic baseline on all holdouts, not just training data").

Two model baselines, deliberately simple and distinct from the D2 ensemble
members so they're a meaningful floor, not a weaker copy of the ensemble:
  - LogisticRegression (linear, standardized features)
  - HistGradientBoostingClassifier (sklearn's native gradient boosting --
    distinct from the LightGBM model used inside the Part D2 ensemble, so
    "gradient boosting" is checked as an independent baseline, not just
    reused as one of the ensemble's own voters)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml.metrics import classification_report_dict
from ml.validation import majority_baseline_predictions

RANDOM_STATE = 20260818


def build_logistic_regression() -> LogisticRegression:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, random_state=RANDOM_STATE))


def build_hist_gradient_boosting() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_iter=300, random_state=RANDOM_STATE)


def evaluate_model_across_partitions(
    model, parts: dict[str, pd.DataFrame], feature_cols: list[str], label_col: str,
) -> dict[str, dict]:
    model.fit(parts["train"][feature_cols], parts["train"][label_col])
    results = {}
    for name, part in parts.items():
        y_true = part[label_col].to_numpy()
        y_proba = model.predict_proba(part[feature_cols])[:, 1]
        y_pred = (y_proba >= 0.5).astype(int)
        results[name] = classification_report_dict(y_true, y_pred, y_proba)
    return results


def evaluate_majority_baseline(parts: dict[str, pd.DataFrame], label_col: str) -> dict[str, dict]:
    train_labels = parts["train"][label_col]
    results = {}
    for name, part in parts.items():
        y_true = part[label_col].to_numpy()
        y_pred = majority_baseline_predictions(train_labels, len(part))
        results[name] = classification_report_dict(y_true, y_pred, y_proba=None)
    return results
