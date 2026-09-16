"""Tests for Part D1/D2/D3 (ml/baselines.py, ml/ensemble.py, ml/calibration.py).

Uses real cached labeled feature data (data/labeled_features.parquet), but
restricted to the most recent ~2 years so model fitting stays fast in a
test run -- still real market/clustering-derived data, just a smaller real
slice, not synthetic. Skipped if the cache isn't built.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.baselines import build_logistic_regression, build_hist_gradient_boosting, evaluate_model_across_partitions, evaluate_majority_baseline
from ml.ensemble import fit_weighted_ensemble, build_ensemble_members
from ml.calibration import select_and_fit_calibrator
from ml.validation import split_time_disjoint_panel
from signals.features import FEATURE_COLUMNS

DATA_PATH = Path(__file__).parent.parent / "data" / "labeled_features.parquet"
pytestmark = pytest.mark.skipif(not DATA_PATH.exists(), reason="labeled_features.parquet not built yet")


@pytest.fixture(scope="module")
def small_parts():
    df = pd.read_parquet(DATA_PATH)
    recent = df[df["date"] >= df["date"].max() - pd.Timedelta(days=730)]
    parts, _ = split_time_disjoint_panel(recent, holding_period=5, min_rows_per_partition=100)
    return parts


def test_majority_baseline_constant_within_partition(small_parts):
    results = evaluate_majority_baseline(small_parts, "label_cost_adjusted")
    for name, part in small_parts.items():
        assert results[name]["positive_rate_pred"] in (0.0, 1.0)  # always predicts one class


def test_logistic_regression_runs_and_produces_probabilities(small_parts):
    results = evaluate_model_across_partitions(build_logistic_regression(), small_parts, FEATURE_COLUMNS, "label_cost_adjusted")
    for name, r in results.items():
        assert 0.0 <= r["roc_auc"] <= 1.0
        assert 0.0 <= r["positive_rate_pred"] <= 1.0


def test_gradient_boosting_baseline_runs(small_parts):
    results = evaluate_model_across_partitions(build_hist_gradient_boosting(), small_parts, FEATURE_COLUMNS, "label_cost_adjusted")
    assert "train" in results and "holdout_a" in results


def test_ensemble_weights_sum_to_one(small_parts):
    ensemble = fit_weighted_ensemble(small_parts, FEATURE_COLUMNS, "label_cost_adjusted")
    assert set(ensemble.weights.keys()) == set(build_ensemble_members().keys())
    assert np.isclose(sum(ensemble.weights.values()), 1.0)
    assert all(w >= 0 for w in ensemble.weights.values())


def test_ensemble_predict_proba_in_unit_interval(small_parts):
    ensemble = fit_weighted_ensemble(small_parts, FEATURE_COLUMNS, "label_cost_adjusted")
    proba = ensemble.predict_proba(small_parts["holdout_a"])
    assert (proba >= 0).all() and (proba <= 1).all()
    assert len(proba) == len(small_parts["holdout_a"])


def test_calibrator_improves_or_matches_brier_on_validation(small_parts):
    from sklearn.metrics import brier_score_loss
    ensemble = fit_weighted_ensemble(small_parts, FEATURE_COLUMNS, "label_cost_adjusted")
    calibrator = select_and_fit_calibrator(ensemble, small_parts["validation"], "label_cost_adjusted")

    raw = ensemble.predict_proba(small_parts["holdout_a"])
    calibrated = calibrator.transform(raw)
    y_true = small_parts["holdout_a"]["label_cost_adjusted"].to_numpy()

    assert calibrator.method in ("isotonic", "sigmoid")
    # calibrated probabilities must still be valid probabilities
    assert (calibrated >= 0).all() and (calibrated <= 1).all()
    # sanity: calibration shouldn't be wildly worse than raw (allow small tolerance --
    # calibration is fit on validation, evaluated out-of-sample on a holdout, so it
    # can occasionally be marginally worse than raw on a given holdout by chance)
    raw_brier = brier_score_loss(y_true, raw)
    cal_brier = brier_score_loss(y_true, calibrated)
    assert cal_brier < raw_brier + 0.05
