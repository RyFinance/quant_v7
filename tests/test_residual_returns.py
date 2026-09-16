"""Tests for residual return calculation (Task 7). Real data: AAPL, MSFT,
JPM, SPY daily bars via yfinance over a multi-year window (long enough for
a 60-day rolling beta to warm up). Skipped if offline.
"""
import numpy as np
import pytest

from data.ingestion import fetch_ticker_history
from clustering.residual_returns import (
    compute_residual_returns,
    compute_simple_returns,
    fetch_market_returns,
    _to_close_panel,
)


@pytest.fixture(scope="module")
def universe_data():
    data = {}
    for ticker in ["AAPL", "MSFT", "JPM"]:
        df = fetch_ticker_history(ticker, start="2021-01-01", end="2022-06-01")
        if df.empty:
            pytest.skip("network unavailable / yfinance unreachable")
        data[ticker] = df
    return data


@pytest.fixture(scope="module")
def market_returns():
    try:
        return fetch_market_returns(start="2021-01-01", end="2022-06-01")
    except Exception as e:
        pytest.skip(f"network unavailable / could not fetch SPY: {e!r}")


def test_residualization_reduces_market_correlation(universe_data, market_returns):
    """The point of stripping beta: residuals should correlate with the
    market noticeably less than raw returns do."""
    close_panel = _to_close_panel(universe_data)
    raw_returns = compute_simple_returns(close_panel)
    residuals = compute_residual_returns(raw_returns, market_returns, lookback=60)

    aligned_raw = raw_returns.join(market_returns, how="inner")
    aligned_resid = residuals.join(market_returns, how="inner")

    for ticker in universe_data:
        raw_corr = abs(aligned_raw[ticker].corr(aligned_raw[market_returns.name]))
        resid_corr = abs(aligned_resid[ticker].corr(aligned_resid[market_returns.name]))
        assert resid_corr < raw_corr, f"{ticker}: residual |corr|={resid_corr:.3f} not < raw |corr|={raw_corr:.3f}"


def test_residual_returns_warmup_drops_short_history(universe_data, market_returns):
    close_panel = _to_close_panel(universe_data)
    raw_returns = compute_simple_returns(close_panel)
    residuals = compute_residual_returns(raw_returns, market_returns, lookback=60)
    assert len(residuals) < len(raw_returns)  # first `lookback` rows dropped as NaN
    assert not residuals.iloc[0].isna().all()  # first surviving row should be usable


def test_residual_returns_no_nan_after_warmup(universe_data, market_returns):
    close_panel = _to_close_panel(universe_data)
    raw_returns = compute_simple_returns(close_panel)
    residuals = compute_residual_returns(raw_returns, market_returns, lookback=60)
    assert np.isfinite(residuals.to_numpy()).all()
