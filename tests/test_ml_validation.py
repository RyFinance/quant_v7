"""Tests for Part D4 (ml/validation.py). The panel-split and class-
completeness tests use real cached Phase 3 data (data/labeled_features.parquet).
The purge-gap and insufficient-history edge cases use a small hand-built
DataFrame with synthetic dates/labels (SYNTHETIC DATA -- noted here
explicitly) since those specific edge conditions (a labeled row whose
forward window crosses a partition boundary, or too little history) don't
reliably occur at natural, inspectable rows in the real dataset and need
to be constructed to verify the exact boundary logic.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.validation import (
    InsufficientHistoryError,
    check_class_completeness,
    majority_baseline_predictions,
    split_time_disjoint_panel,
)

DATA_PATH = Path(__file__).parent.parent / "data" / "labeled_features.parquet"
pytestmark = pytest.mark.skipif(not DATA_PATH.exists(), reason="labeled_features.parquet not built yet")


@pytest.fixture(scope="module")
def real_features():
    return pd.read_parquet(DATA_PATH)


def test_split_produces_five_chronologically_ordered_partitions(real_features):
    parts, partitions = split_time_disjoint_panel(real_features, holding_period=5)
    assert list(parts.keys()) == ["train", "validation", "holdout_a", "holdout_b", "holdout_c"]
    ends = [pd.Timestamp(p.end) for p in partitions]
    starts = [pd.Timestamp(p.start) for p in partitions]
    for i in range(len(partitions) - 1):
        assert ends[i] < starts[i + 1]  # strictly chronological, no overlap


def test_split_purges_boundary_dates(real_features):
    """Every partition except the last should have its final `holding_period`
    dates removed relative to the unpurged boundary -- i.e. there's a real
    gap between one partition's end and the next partition's start."""
    parts, partitions = split_time_disjoint_panel(real_features, holding_period=5)
    all_dates = np.array(sorted(real_features["date"].unique()))
    for i in range(len(partitions) - 1):
        end_date = pd.Timestamp(partitions[i].end)
        next_start = pd.Timestamp(partitions[i + 1].start)
        gap_trading_days = np.sum((all_dates > np.datetime64(end_date)) & (all_dates < np.datetime64(next_start)))
        assert gap_trading_days >= 5  # the purged 5 dates (approximately; boundary may land mid-week)


def test_no_date_appears_in_two_partitions(real_features):
    parts, _ = split_time_disjoint_panel(real_features, holding_period=5)
    seen = set()
    for name, part in parts.items():
        dates = set(part["date"].unique())
        assert not (dates & seen), f"{name} overlaps a previous partition's dates"
        seen |= dates


def test_class_completeness_report_shape(real_features):
    parts, _ = split_time_disjoint_panel(real_features, holding_period=5)
    report = check_class_completeness(parts, "label_cost_adjusted")
    assert set(report.keys()) == set(parts.keys())
    for name, r in report.items():
        assert r["n_class_0"] + r["n_class_1"] == len(parts[name])


def test_majority_baseline_predicts_train_majority_class():
    train_labels = pd.Series([0, 0, 0, 1, 1])  # SYNTHETIC: hand-picked to have a known majority (0)
    preds = majority_baseline_predictions(train_labels, n=10)
    assert (preds == 0).all()
    assert len(preds) == 10


def test_insufficient_history_raises():
    tiny = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10),  # SYNTHETIC: too few dates by construction
        "label_cost_adjusted": [0, 1] * 5,
    })
    with pytest.raises(InsufficientHistoryError):
        split_time_disjoint_panel(tiny, holding_period=5)


def test_class_completeness_flags_missing_class():
    df = pd.DataFrame({
        "date": list(pd.date_range("2024-01-01", periods=100)),
        "label_cost_adjusted": [0] * 100,  # SYNTHETIC: deliberately all-zero to trigger the flag
    })
    parts = {"holdout_x": df}
    report = check_class_completeness(parts, "label_cost_adjusted")
    assert report["holdout_x"]["both_classes_present"] is False
