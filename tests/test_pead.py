"""Tests for the PEAD investigation (earnings/ingestion.py, sue.py,
signal.py, labeling.py, features.py). Uses real cached data
(data/earnings_sue.parquet, data/pead_signal.parquet,
data/pead_labeled_features.parquet, built from real yfinance earnings
history) where available; a couple of edge-case tests construct small
hand-built earnings histories (SYNTHETIC, noted explicitly) to verify the
small-denominator winsorization fix and the BMO/AMC timing-alignment
logic against known inputs.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from earnings.sue import compute_sue, SURPRISE_PCT_WINSOR_LIMIT
from earnings.signal import _effective_trading_date, build_pead_signal
from earnings.labeling import build_labeled_pead_signals

DATA_DIR = Path(__file__).parent.parent / "data"


def test_sue_winsorizes_extreme_surprise():
    """SYNTHETIC: a hand-built history with one small-denominator blowup
    (real bug found during this build -- XOM 2020-05-01 had a +135,997%
    surprise from a near-zero EPS estimate)."""
    df = pd.DataFrame({
        "ticker": ["X"] * 6,
        "earnings_date": pd.date_range("2020-01-01", periods=6, freq="90D"),
        "eps_estimate": [1.0, 1.0, 1.0, 1.0, 1.0, 0.001],
        "eps_actual": [1.05, 0.95, 1.02, 0.98, 1.03, 1.36],
        "surprise_pct": [5.0, -5.0, 2.0, -2.0, 3.0, 135997.0],  # last one is the blowup
    })
    out = compute_sue(df)
    assert out["surprise_pct_winsorized"].max() <= SURPRISE_PCT_WINSOR_LIMIT
    assert np.isfinite(out["sue"].dropna()).all()  # no inf leaking through


def test_sue_no_lookahead():
    """SUE at event t must only use surprises strictly BEFORE t."""
    df = pd.DataFrame({
        "ticker": ["X"] * 10,
        "earnings_date": pd.date_range("2020-01-01", periods=10, freq="90D"),
        "eps_estimate": [1.0] * 10,
        "eps_actual": [1.0] * 10,
        "surprise_pct": [1, 2, 3, 4, 5, 6, 7, 8, 9, 100],  # last is a big outlier
    })
    out = compute_sue(df, window=8, min_periods=4)
    # the SUE for the 5th event (index 4) must not be affected by the 10th event's outlier
    early_sue = out.iloc[4]["sue"]
    df2 = df.iloc[:5].copy()  # truncate before the outlier ever existed
    out2 = compute_sue(df2, window=8, min_periods=4)
    assert np.isclose(early_sue, out2.iloc[4]["sue"], equal_nan=True)


def test_effective_trading_date_after_market_close_rolls_to_next_day():
    trading_dates = pd.date_range("2024-01-01", "2024-01-10", freq="B")
    amc_announcement = pd.Timestamp("2024-01-02 16:30:00")  # after 16:00 -> next session
    eff = _effective_trading_date(amc_announcement, trading_dates)
    assert eff == pd.Timestamp("2024-01-03")


def test_effective_trading_date_before_market_open_same_day():
    trading_dates = pd.date_range("2024-01-01", "2024-01-10", freq="B")
    bmo_announcement = pd.Timestamp("2024-01-02 07:00:00")  # before 16:00 -> same session
    eff = _effective_trading_date(bmo_announcement, trading_dates)
    assert eff == pd.Timestamp("2024-01-02")


@pytest.mark.skipif(not (DATA_DIR / "earnings_sue.parquet").exists(), reason="earnings data not ingested yet")
def test_real_sue_distribution_sane():
    sue_df = pd.read_parquet(DATA_DIR / "earnings_sue.parquet")
    assert np.isfinite(sue_df["sue"]).all()  # regression test for the inf-from-zero-std bug
    assert sue_df["surprise_pct_winsorized"].abs().max() <= SURPRISE_PCT_WINSOR_LIMIT + 1e-9


@pytest.mark.skipif(not (DATA_DIR / "pead_signal.parquet").exists(), reason="PEAD signal not built yet")
def test_real_pead_signal_matches_sue_sign():
    sig = pd.read_parquet(DATA_DIR / "pead_signal.parquet")
    sue_df = pd.read_parquet(DATA_DIR / "earnings_sue.parquet")
    merged = sig.merge(sue_df[["ticker", "earnings_date", "sue"]],
                        left_on=["ticker", "earnings_date_raw"], right_on=["ticker", "earnings_date"], how="inner")
    assert np.allclose(merged["signal"], merged["sue"])


@pytest.mark.skipif(not (DATA_DIR / "pead_labeled_features.parquet").exists(), reason="PEAD features not built yet")
def test_real_labeled_features_class_balance_reasonable():
    df = pd.read_parquet(DATA_DIR / "pead_labeled_features.parquet")
    assert 0.2 < df["label_cost_adjusted"].mean() < 0.8
    assert 0.2 < df["label_fixed_threshold"].mean() < 0.8
    assert len(df) > 1000  # real, substantial sample despite the sparser event cadence


@pytest.mark.skipif(not (DATA_DIR / "residual_returns_wide.parquet").exists(), reason="residual returns not built yet")
def test_labeling_fixed_stricter_than_cost_adjusted():
    sig = pd.read_parquet(DATA_DIR / "pead_signal.parquet")
    resid = pd.read_parquet(DATA_DIR / "residual_returns_wide.parquet")
    labeled = build_labeled_pead_signals(resid, sig.head(200), holding_period=20, fixed_threshold=0.01, cost_bps=10.0)
    fixed_positive = labeled[labeled["label_fixed_threshold"] == 1]
    assert (fixed_positive["label_cost_adjusted"] == 1).all()
