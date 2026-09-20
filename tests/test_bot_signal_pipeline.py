"""Tests for bot/signal_pipeline.py. Fits (or loads a cached fit of) the
real ensemble/calibrator against the real cached PEAD dataset, then scores
one real, known historical earnings event end-to-end.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import bot.earnings_watcher as ew
import bot.signal_pipeline as sp

DATA_PATH = Path(__file__).parent.parent / "data" / "pead_labeled_features.parquet"


@pytest.fixture(scope="module")
def pipeline():
    if not DATA_PATH.exists():
        pytest.skip("pead_labeled_features.parquet not built yet")
    return sp.fit_or_load()


def test_fit_or_load_produces_a_usable_pipeline(pipeline):
    assert pipeline.payoff.b > 0
    assert abs(sum(pipeline.ensemble.weights.values()) - 1.0) < 1e-6


def test_fit_or_load_caches_to_disk(pipeline):
    assert sp.MODEL_PATH.exists()


def test_score_real_known_event(pipeline):
    """AAPL's 2025-05-01 report -- a real reported event, used elsewhere in
    this project's own reports/ pipeline as real data. The row is read from
    the live history rather than hardcoded: providers revise the exact
    timestamp (yfinance 0.2.x said 16:30, 1.x says 16:00), and scoring
    matches on it exactly."""
    history = sp.fetch_ticker_earnings_live("AAPL")
    if history.empty:
        pytest.skip("network unavailable / yfinance unreachable for earnings history")
    rows = history[history["earnings_date"].dt.normalize() == pd.Timestamp("2025-05-01")]
    assert len(rows) == 1
    row = rows.iloc[0]
    event = ew.ReportedEarnings(
        ticker="AAPL", earnings_date=row["earnings_date"], eps_estimate=row["eps_estimate"],
        eps_actual=row["eps_actual"], surprise_pct=row["surprise_pct"], days_since=2,
    )
    scored = sp.score_event(event, pipeline)
    if scored is None:
        pytest.skip("network unavailable / yfinance unreachable for feature build")
    assert 0.0 <= scored.calibrated_proba <= 1.0
    assert scored.direction in {"long", "short"}
    assert scored.sue != 0.0


def test_build_feature_row_returns_none_for_unknown_ticker():
    event = ew.ReportedEarnings(
        ticker="NOT_A_REAL_TICKER_XYZ", earnings_date=pd.Timestamp("2024-01-01"),
        eps_estimate=1.0, eps_actual=1.0, surprise_pct=0.0, days_since=1,
    )
    row = sp.build_feature_row(event)
    assert row is None
