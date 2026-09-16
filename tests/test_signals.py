"""Tests for Part C (signals/mean_reversion.py, signals/labeling.py,
signals/features.py). Uses the real cached Phase 3 artifacts
(data/cluster_assignments.parquet, computed from real 2015-2026 market
data in earlier phases) rather than rebuilding from scratch or
synthesizing -- rebuilding takes ~1-2 minutes and these are already real.
Skipped if the cache files aren't present (run reports/run_pipeline.py and
reports/run_ml_filter.py first to produce them).
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data.ingestion import load_universe
from clustering.residual_returns import build_residual_returns
from clustering.cluster_assignments import load_or_build_cluster_assignments, CACHE_PATH
from signals.mean_reversion import compute_deviation_signal, MIN_CLUSTER_SIZE_FOR_SIGNAL
from signals.labeling import build_labeled_signals, compute_forward_position_return, add_labels, HOLDING_PERIOD_DAYS
from signals.features import build_feature_matrix, compute_market_stability_series, FEATURE_COLUMNS

pytestmark = pytest.mark.skipif(not CACHE_PATH.exists(), reason="cluster_assignments.parquet not built yet")


@pytest.fixture(scope="module")
def residuals():
    with open(Path(__file__).parent.parent / "reports" / "universe_selection.txt") as f:
        tickers = f.read().strip().split("\n")[1].split(",")
    data = load_universe(tickers)
    return build_residual_returns(data, lookback=60, start="2015-01-01")


@pytest.fixture(scope="module")
def assignments(residuals):
    return load_or_build_cluster_assignments(residuals)


@pytest.fixture(scope="module")
def signal_df(residuals, assignments):
    return compute_deviation_signal(residuals, assignments)


def test_deviation_signal_zero_sums_within_cluster(residuals, assignments):
    sig = compute_deviation_signal(residuals, assignments)
    # deviations are demeaned within (date, cluster) by construction -- should sum ~0
    grouped = sig.groupby(["date", "cluster_id"])["deviation"].sum()
    assert np.allclose(grouped, 0, atol=1e-9)


def test_deviation_signal_respects_min_cluster_size(residuals, assignments):
    sig = compute_deviation_signal(residuals, assignments)
    assert (sig["cluster_size"] >= MIN_CLUSTER_SIZE_FOR_SIGNAL).all()


def test_signal_sign_convention(signal_df):
    # signal = -z_score: a ticker that outperformed its cluster (positive
    # deviation/z) should get a NEGATIVE (bearish) signal, and vice versa.
    positive_dev = signal_df[signal_df["z_score"] > 1]
    negative_dev = signal_df[signal_df["z_score"] < -1]
    assert (positive_dev["signal"] < 0).mean() > 0.99
    assert (negative_dev["signal"] > 0).mean() > 0.99


def test_forward_position_return_no_lookahead_into_same_day(residuals, signal_df):
    """forward_return at date t must only use residual returns strictly after t."""
    small_signal = signal_df[signal_df["date"] == signal_df["date"].unique()[100]]
    out = compute_forward_position_return(residuals, small_signal, holding_period=5)
    # manually recompute for one row and check it matches
    row = out.iloc[0]
    ticker, date = row["ticker"], row["date"]
    idx = residuals.index.get_loc(date)
    expected = residuals[ticker].iloc[idx + 1: idx + 1 + HOLDING_PERIOD_DAYS].sum()
    assert np.isclose(row["forward_return"], expected, atol=1e-10)


def test_labels_are_binary_and_consistent_with_threshold(residuals, signal_df):
    labeled = build_labeled_signals(residuals, signal_df, holding_period=5, fixed_threshold=0.005, cost_bps=10.0)
    assert set(labeled["label_fixed_threshold"].unique()) <= {0, 1}
    assert set(labeled["label_cost_adjusted"].unique()) <= {0, 1}
    # fixed threshold (50bps) is stricter than cost-adjusted (10bps) -- every
    # fixed-threshold positive must also be a cost-adjusted positive
    fixed_positive = labeled[labeled["label_fixed_threshold"] == 1]
    assert (fixed_positive["label_cost_adjusted"] == 1).all()


def test_market_stability_series_matches_phase2_definition(assignments):
    stability = compute_market_stability_series(assignments)
    assert stability["market_ari_vs_prev"].iloc[0] != stability["market_ari_vs_prev"].iloc[0]  # NaN for first date
    assert stability["market_ari_vs_prev"].dropna().between(-1.0001, 1.0001).all()


def test_feature_matrix_has_no_nans_in_feature_columns(residuals, signal_df, assignments):
    labeled = build_labeled_signals(residuals, signal_df)
    feats = build_feature_matrix(labeled, residuals, assignments)
    assert not feats[FEATURE_COLUMNS].isna().any().any()
    assert len(feats) > 0
