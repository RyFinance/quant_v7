"""Tests for spectral + SPONGE-sym clustering (Task 9). Uses a real
correlation matrix built from real market data (same fixture pattern as
test_correlation.py). Skipped if offline.
"""
import numpy as np
import pytest

from data.ingestion import fetch_ticker_history
from clustering.residual_returns import compute_residual_returns, compute_simple_returns, fetch_market_returns, _to_close_panel
from clustering.correlation import latest_correlation_matrix
from clustering.clustering import spectral_cluster, sponge_sym_cluster


@pytest.fixture(scope="module")
def correlation_snapshot():
    data = {}
    for ticker in ["AAPL", "MSFT", "JPM", "XOM", "CVX", "GS", "BAC", "GOOGL"]:
        df = fetch_ticker_history(ticker, start="2020-01-01", end="2022-06-01")
        if df.empty:
            pytest.skip("network unavailable / yfinance unreachable")
        data[ticker] = df
    try:
        market = fetch_market_returns(start="2020-01-01", end="2022-06-01")
    except Exception as e:
        pytest.skip(f"network unavailable / could not fetch SPY: {e!r}")

    close_panel = _to_close_panel(data)
    raw_returns = compute_simple_returns(close_panel)
    residuals = compute_residual_returns(raw_returns, market, lookback=60)
    return latest_correlation_matrix(residuals, lookback=60)


def test_spectral_cluster_valid_partition(correlation_snapshot):
    k = 3
    result = spectral_cluster(correlation_snapshot.matrix, correlation_snapshot.tickers, k=k)
    assert len(result.labels) == len(correlation_snapshot.tickers)
    assert set(result.labels) <= set(range(k))
    assert result.method == "spectral"


def test_sponge_sym_cluster_valid_partition(correlation_snapshot):
    k = 3
    result = sponge_sym_cluster(correlation_snapshot.matrix, correlation_snapshot.tickers, k=k)
    assert len(result.labels) == len(correlation_snapshot.tickers)
    assert set(result.labels) <= set(range(k))
    assert result.method == "sponge_sym"


def test_sponge_sym_deterministic_with_fixed_seed(correlation_snapshot):
    r1 = sponge_sym_cluster(correlation_snapshot.matrix, correlation_snapshot.tickers, k=3, random_state=7)
    r2 = sponge_sym_cluster(correlation_snapshot.matrix, correlation_snapshot.tickers, k=3, random_state=7)
    assert np.array_equal(r1.labels, r2.labels)


def test_spectral_and_sponge_both_use_all_tickers(correlation_snapshot):
    sc = spectral_cluster(correlation_snapshot.matrix, correlation_snapshot.tickers, k=2)
    sp = sponge_sym_cluster(correlation_snapshot.matrix, correlation_snapshot.tickers, k=2)
    assert len(sc.labels) == len(sp.labels) == len(correlation_snapshot.tickers)
