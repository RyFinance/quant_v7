"""Tests for OHLCV ingestion (Task 2). Hits real yfinance data (AAPL, MSFT,
a short recent window) -- no synthetic price series. Skipped if offline.
"""
from pathlib import Path

import pandas as pd
import pytest

from data.ingestion import fetch_ticker_history, ingest_universe, load_universe, to_bars
from schemas.market_data import OHLCVBar


@pytest.fixture(scope="module")
def aapl_df():
    df = fetch_ticker_history("AAPL", start="2024-01-01", end="2024-02-01")
    if df.empty:
        pytest.skip("network unavailable / yfinance unreachable")
    return df


def test_fetch_ticker_history_shape(aapl_df):
    assert not aapl_df.empty
    assert {"timestamp", "open", "high", "low", "close", "volume"}.issubset(aapl_df.columns)
    assert len(aapl_df) >= 15  # ~ a month of trading days


def test_to_bars_produces_valid_models(aapl_df):
    bars = to_bars("AAPL", aapl_df)
    assert len(bars) == len(aapl_df)
    assert all(isinstance(b, OHLCVBar) for b in bars)
    assert all(b.ticker == "AAPL" for b in bars)


def test_ingest_universe_writes_parquet(tmp_path):
    results = ingest_universe(["AAPL", "MSFT"], start="2024-01-01", end="2024-02-01", out_dir=tmp_path)
    if not results:
        pytest.skip("network unavailable / yfinance unreachable")
    assert set(results.keys()) <= {"AAPL", "MSFT"}
    for ticker, df in results.items():
        assert (tmp_path / f"{ticker}.parquet").exists()
        assert not df.empty

    reloaded = load_universe(list(results.keys()), data_dir=tmp_path)
    assert set(reloaded.keys()) == set(results.keys())
    for ticker in results:
        pd.testing.assert_frame_equal(
            reloaded[ticker].reset_index(drop=True),
            results[ticker].reset_index(drop=True),
        )
