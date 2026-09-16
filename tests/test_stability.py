"""Tests for the cluster stability monitor (Task 11). The ARI-mechanics
tests construct ClusterResult label arrays directly (hand-picked integers,
not simulated market data) to check known ARI edge cases exactly. The
end-to-end test uses real market data (AAPL/MSFT/JPM/XOM/CVX/GS/BAC/GOOGL)
run through the real residual-return -> correlation -> clustering pipeline.
Skipped if offline.
"""
import json

import pandas as pd
import pytest

from clustering.clustering import ClusterResult, spectral_cluster
from clustering.stability import compute_stability_series, stability_dataframe


def test_identical_labels_give_ari_one():
    tickers = ["A", "B", "C", "D"]
    r1 = ClusterResult(labels=[0, 0, 1, 1], tickers=tickers, k=2, method="spectral")
    r2 = ClusterResult(labels=[0, 0, 1, 1], tickers=tickers, k=2, method="spectral")
    points = compute_stability_series(
        [(pd.Timestamp("2024-01-01"), r1), (pd.Timestamp("2024-01-02"), r2)]
    )
    assert points[0].ari_vs_prev is None  # no prior snapshot
    assert points[1].ari_vs_prev == pytest.approx(1.0)


def test_relabeled_but_equivalent_partition_gives_ari_one():
    tickers = ["A", "B", "C", "D"]
    r1 = ClusterResult(labels=[0, 0, 1, 1], tickers=tickers, k=2, method="spectral")
    r2 = ClusterResult(labels=[1, 1, 0, 0], tickers=tickers, k=2, method="spectral")  # same partition, swapped ids
    points = compute_stability_series(
        [(pd.Timestamp("2024-01-01"), r1), (pd.Timestamp("2024-01-02"), r2)]
    )
    assert points[1].ari_vs_prev == pytest.approx(1.0)


def test_completely_different_partition_flags_low_ari_and_logs(tmp_path):
    tickers = ["A", "B", "C", "D"]
    r1 = ClusterResult(labels=[0, 0, 1, 1], tickers=tickers, k=2, method="spectral")
    r2 = ClusterResult(labels=[0, 1, 0, 1], tickers=tickers, k=2, method="spectral")  # orthogonal split

    log_path = tmp_path / "stability.jsonl"
    points = compute_stability_series(
        [(pd.Timestamp("2024-01-01"), r1), (pd.Timestamp("2024-01-02"), r2)],
        log_path=log_path,
    )
    assert points[1].ari_vs_prev is not None and points[1].ari_vs_prev < 0.5

    lines = log_path.read_text().strip().splitlines()
    kinds = [json.loads(l)["kind"] for l in lines]
    assert "cluster_membership_shift" in kinds


def test_cluster_count_change_is_logged(tmp_path):
    tickers = ["A", "B", "C", "D"]
    r1 = ClusterResult(labels=[0, 0, 1, 1], tickers=tickers, k=2, method="spectral")
    r2 = ClusterResult(labels=[0, 1, 1, 2], tickers=tickers, k=3, method="spectral")

    log_path = tmp_path / "stability.jsonl"
    compute_stability_series(
        [(pd.Timestamp("2024-01-01"), r1), (pd.Timestamp("2024-01-02"), r2)],
        log_path=log_path,
    )
    lines = log_path.read_text().strip().splitlines()
    kinds = [json.loads(l)["kind"] for l in lines]
    assert "cluster_count_changed" in kinds


def test_stability_dataframe_shape():
    tickers = ["A", "B", "C", "D"]
    r1 = ClusterResult(labels=[0, 0, 1, 1], tickers=tickers, k=2, method="spectral")
    points = compute_stability_series([(pd.Timestamp("2024-01-01"), r1)])
    df = stability_dataframe(points)
    assert list(df.columns) == ["date", "k", "n_tickers", "ari_vs_prev"]
    assert len(df) == 1


@pytest.fixture(scope="module")
def real_dated_results():
    from data.ingestion import fetch_ticker_history
    from clustering.residual_returns import compute_residual_returns, compute_simple_returns, fetch_market_returns, _to_close_panel
    from clustering.correlation import rolling_correlation_matrices
    from clustering.cluster_count import explained_variance_k

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
    snaps = rolling_correlation_matrices(residuals, lookback=60, step=20)[-8:]

    dated_results = []
    for snap in snaps:
        k, _ = explained_variance_k(snap.matrix, threshold=0.90)
        k = max(2, min(k, len(snap.tickers) - 1))
        dated_results.append((snap.date, spectral_cluster(snap.matrix, snap.tickers, k=k)))
    return dated_results


def test_end_to_end_stability_series_on_real_data(real_dated_results):
    points = compute_stability_series(real_dated_results)
    assert len(points) == len(real_dated_results)
    assert points[0].ari_vs_prev is None
    assert all(p.ari_vs_prev is None or -1.0001 <= p.ari_vs_prev <= 1.0001 for p in points[1:])
