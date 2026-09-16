"""Part D3 -- probability calibration.

The raw ensemble output (ml/ensemble.py's weighted-average probability) is
not guaranteed to be a calibrated probability -- e.g. tree ensembles are
well known to push probabilities toward 0/1 more than the true frequency
warrants. Kelly sizing (Part E1) needs an actually-calibrated probability,
since Kelly fraction is a direct function of edge = 2p-1 -- an
overconfident p silently oversizes every position.

Two calibrators are tried -- isotonic regression (flexible, non-parametric,
can overfit on small calibration sets) and Platt/sigmoid scaling (a single
logistic fit, less flexible but more stable on limited data) -- and picked
by Brier score, per spec D3. Selection uses a further chronological split
INSIDE the validation partition (first 70% of validation dates to fit each
candidate, last 30% to score them) so the calibrator selection itself
isn't evaluated on the same rows it was fit on. The winning method is then
refit on the FULL validation partition for the calibrator actually used
downstream. Train and the three holdouts are never touched by this
process -- they remain untouched for the final, honest evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

from ml.ensemble import FittedEnsemble


@dataclass
class Calibrator:
    method: str
    model: object

    def transform(self, raw_proba: np.ndarray) -> np.ndarray:
        if self.method == "isotonic":
            return self.model.predict(raw_proba)
        else:
            return self.model.predict_proba(raw_proba.reshape(-1, 1))[:, 1]


def _fit_isotonic(raw: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    model = IsotonicRegression(out_of_bounds="clip")
    model.fit(raw, y)
    return model


def _fit_sigmoid(raw: np.ndarray, y: np.ndarray) -> LogisticRegression:
    model = LogisticRegression()
    model.fit(raw.reshape(-1, 1), y)
    return model


def select_and_fit_calibrator(ensemble: FittedEnsemble, validation_df: pd.DataFrame, label_col: str) -> Calibrator:
    validation_df = validation_df.sort_values("date")
    dates = validation_df["date"].unique()
    split_idx = int(len(dates) * 0.7)
    fit_dates, eval_dates = dates[:split_idx], dates[split_idx:]

    fit_df = validation_df[validation_df["date"].isin(fit_dates)]
    eval_df = validation_df[validation_df["date"].isin(eval_dates)]

    raw_fit = ensemble.predict_proba(fit_df)
    y_fit = fit_df[label_col].to_numpy()
    raw_eval = ensemble.predict_proba(eval_df)
    y_eval = eval_df[label_col].to_numpy()

    candidates = {
        "isotonic": _fit_isotonic(raw_fit, y_fit),
        "sigmoid": _fit_sigmoid(raw_fit, y_fit),
    }
    scores = {}
    for method, model in candidates.items():
        calibrated = Calibrator(method=method, model=model).transform(raw_eval)
        scores[method] = brier_score_loss(y_eval, calibrated)

    uncalibrated_brier = brier_score_loss(y_eval, raw_eval)
    best_method = min(scores, key=scores.get)
    logger.info(f"calibration selection: {scores}, uncalibrated_brier={uncalibrated_brier:.6f}, chose {best_method!r}")

    raw_full = ensemble.predict_proba(validation_df)
    y_full = validation_df[label_col].to_numpy()
    if best_method == "isotonic":
        final_model = _fit_isotonic(raw_full, y_full)
    else:
        final_model = _fit_sigmoid(raw_full, y_full)
    return Calibrator(method=best_method, model=final_model)


def reliability_table(y_true: np.ndarray, y_proba: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    frac_pos, mean_pred = calibration_curve(y_true, y_proba, n_bins=n_bins, strategy="quantile")
    return pd.DataFrame({"mean_predicted_prob": mean_pred, "observed_frequency": frac_pos})
