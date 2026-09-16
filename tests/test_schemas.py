"""Tests for the unified data schema (Task 4). All values below are real,
plausible market data (an actual AAPL daily bar and a real historical S&P
500 membership fact), not randomly generated fixtures -- construction is
still hand-written literals rather than fetched live, since the point here
is to test pydantic validation logic, not the data source itself.
"""
from datetime import datetime

import pytest
from pydantic import ValidationError

from schemas.market_data import AssetClass, DataSource, OHLCVBar, UniverseMember


def test_ohlcv_bar_valid():
    bar = OHLCVBar(
        ticker="aapl", timestamp=datetime(2024, 1, 2),
        open=187.15, high=188.44, low=183.89, close=185.64, volume=82488700,
    )
    assert bar.ticker == "AAPL"  # normalized upper
    assert bar.asset_class == AssetClass.EQUITY
    assert bar.source == DataSource.YFINANCE


def test_ohlcv_bar_rejects_high_below_low():
    with pytest.raises(ValidationError):
        OHLCVBar(
            ticker="AAPL", timestamp=datetime(2024, 1, 2),
            open=187.15, high=180.0, low=183.89, close=185.64, volume=82488700,
        )


def test_ohlcv_bar_rejects_negative_price():
    with pytest.raises(ValidationError):
        OHLCVBar(
            ticker="AAPL", timestamp=datetime(2024, 1, 2),
            open=-1.0, high=188.44, low=183.89, close=185.64, volume=82488700,
        )


def test_universe_member_open_interval():
    m = UniverseMember(ticker="nvda", name="NVIDIA Corp", start_date=datetime(2001, 11, 30))
    assert m.ticker == "NVDA"
    assert m.end_date is None


def test_universe_member_closed_interval():
    m = UniverseMember(ticker="ge", start_date=datetime(1907, 1, 1), end_date=datetime(2018, 6, 26))
    assert m.end_date == datetime(2018, 6, 26)
