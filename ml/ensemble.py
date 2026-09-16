"""Part D2 -- ensemble construction.

4 members (spec asks for 3-5): MLP, AdaBoost, LightGBM (the
"HistGradientBoosting/LightGBM" slot -- using LightGBM specifically here so
it's distinct from the sklearn HistGradientBoostingClassifier already used
as the standalone Part D1 baseline), RandomForest.

Performance-weighted voting: each member's vote weight is derived from its
OWN validation-set ROC-AUC (never train-set -- weighting by in-sample
performance would just hand the most overfit member the most influence).
weight_i = max(AUC_i - 0.5, 0) -- a member that's at-or-below chance on
validation gets zero weight rather than a small positive one, since a
below-chance validator is actively unreliable, not just "less good."
Weights are renormalized to sum to 1; if every member is at/below chance
(possible, and reported honestly if so -- see Phase 3 report), weights
fall back to uniform so the ensemble still produces a defined probability
rather than dividing by zero.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import AdaBoostClassifier, RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier
from lightgbm import LGBMClassifier

RANDOM_STATE = 20260818


def build_ensemble_members() -> dict[str, object]:
    return {
        "mlp": MLPClassifier(hidden_layer_sizes=(32, 16), max_iter=500, random_state=RANDOM_STATE, early_stopping=True),
        "adaboost": AdaBoostClassifier(n_estimators=100, random_state=RANDOM_STATE),
        "lightgbm": LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15,
                                    random_state=RANDOM_STATE, verbosity=-1),
        "random_forest": RandomForestClassifier(n_estimators=200, max_depth=6, random_state=RANDOM_STATE, n_jobs=-1),
    }


@dataclass
class FittedEnsemble:
    members: dict[str, object]
    weights: dict[str, float]
    feature_cols: list[str]

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        preds = np.zeros(len(X))
        for name, model in self.members.items():
            preds += self.weights[name] * model.predict_proba(X[self.feature_cols])[:, 1]
        return preds


def fit_weighted_ensemble(
    parts: dict[str, pd.DataFrame], feature_cols: list[str], label_col: str,
) -> FittedEnsemble:
    members = build_ensemble_members()
    X_train, y_train = parts["train"][feature_cols], parts["train"][label_col]
    X_val, y_val = parts["validation"][feature_cols], parts["validation"][label_col]

    weights = {}
    for name, model in members.items():
        model.fit(X_train, y_train)
        val_proba = model.predict_proba(X_val)[:, 1]
        auc = roc_auc_score(y_val, val_proba)
        weights[name] = max(auc - 0.5, 0.0)

    total = sum(weights.values())
    if total <= 0:
        n = len(weights)
        weights = {k: 1.0 / n for k in weights}
    else:
        weights = {k: v / total for k, v in weights.items()}

    return FittedEnsemble(members=members, weights=weights, feature_cols=feature_cols)
