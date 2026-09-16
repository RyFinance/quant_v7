"""Tests for the rolling correlation matrix builder (Task 8). Real data:
same AAPL/MSFT/JPM/SPY universe as test_residual_returns.py. Skipped if
offline.
"""
import numpy as np
import pytest

from data.ingestion import fetch_ticker_history
from clustering.residual_returns import compute_residual_returns, compute_simple_returns, fetch_market_returns, _to_close_panel
from clustering.correlation import latest_correlation_matrix, rolling_correlation_matrices


@pytest.fixture(scope="module")
def residuals():
    data = {}
    for ticker in ["AAPL", "MSFT", "JPM", "XOM"]:
        df = fetch_ticker_history(ticker, start="2021-01-01", end="2022-06-01")
        if df.empty:
            pytest.skip("network unavailable / yfinance unreachable")
        data[ticker] = df
    try:
        market = fetch_market_returns(start="2021-01-01", end="2022-06-01")
    except Exception as e:
        pytest.skip(f"network unavailable / could not fetch SPY: {e!r}")

    close_panel = _to_close_panel(data)
    raw_returns = compute_simple_returns(close_panel)
    return compute_residual_returns(raw_returns, market, lookback=60)


def test_rolling_correlation_matrices_are_valid_correlation_matrices(residuals):
    snaps = rolling_correlation_matrices(residuals, lookback=60, step=20)
    assert len(snaps) > 0
    for snap in snaps:
        m = snap.matrix
        assert m.shape == (len(snap.tickers), len(snap.tickers))
        assert np.allclose(m, m.T, atol=1e-8)  # symmetric
        assert np.allclose(np.diag(m), 1.0, atol=1e-8)  # self-correlation
        assert (m >= -1.0001).all() and (m <= 1.0001).all()


def test_latest_correlation_matrix_uses_most_recent_date(residuals):
    snap = latest_correlation_matrix(residuals, lookback=60)
    assert snap.date == residuals.index[-1]


def test_correlation_lookback_is_configurable(residuals):
    snap_30 = latest_correlation_matrix(residuals, lookback=30)
    snap_90 = latest_correlation_matrix(residuals, lookback=90)
    # different lookback windows over noisy real returns should not produce
    # bit-identical matrices
    assert not np.allclose(snap_30.matrix, snap_90.matrix)
