"""Tests for bot/earnings_watcher.py. Hits real yfinance earnings-calendar
data -- skipped gracefully if offline or if the live calendar has no
events in the probed window, matching tests/test_ingestion.py's convention.
`now` is pinned to a real, known-good historical window rather than
wall-clock "now" so the test doesn't depend on yfinance's calendar horizon
matching whatever the system clock says at run time.
"""
from __future__ import annotations

import pandas as pd
import pytest

import bot.earnings_watcher as ew


def test_load_validated_universe_returns_the_phase1_universe():
    tickers = ew.load_validated_universe()
    assert len(tickers) == 75
    assert "AAPL" in tickers


def test_get_recently_reported_real_data():
    watcher = ew.EarningsWatcher(tickers=["AAPL"])
    events = watcher.get_recently_reported(days_back=10, now=pd.Timestamp("2025-05-03"))
    if not events:
        pytest.skip("network unavailable / yfinance unreachable")
    assert events[0].ticker == "AAPL"
    assert events[0].eps_actual is not None
    assert 0 <= events[0].days_since <= 10


def test_get_recently_reported_excludes_unreported_future_rows():
    watcher = ew.EarningsWatcher(tickers=["AAPL"])
    events = watcher.get_recently_reported(days_back=3650, now=pd.Timestamp("2020-01-01"))
    if not events:
        pytest.skip("network unavailable / yfinance unreachable")
    assert all(e.eps_actual is not None for e in events)


def test_get_recently_reported_detects_same_day_bmo_event(monkeypatch):
    """Regression test for a real bug found 2026-08-19: comparing a raw
    (time-of-day-bearing) earnings_date against a midnight-normalized `now`
    meant a before-market-open (BMO) report was never detected on its own
    announcement day, only the day after. SYNTHETIC data (a hand-built
    fetch_ticker_earnings_live response) since the point is to pin an exact,
    known announcement time and assert same-day detection deterministically
    -- a real BMO event happening to exist at the exact moment a test runs
    can't be relied on."""
    synthetic_history = pd.DataFrame({
        "ticker": ["AAPL"], "earnings_date": [pd.Timestamp("2024-03-15 08:00:00")],
        "eps_estimate": [1.50], "eps_actual": [1.60], "surprise_pct": [6.67],
    })
    monkeypatch.setattr(ew, "fetch_ticker_earnings_live", lambda ticker: synthetic_history)

    watcher = ew.EarningsWatcher(tickers=["AAPL"])
    events = watcher.get_recently_reported(days_back=3, now=pd.Timestamp("2024-03-15"))  # SAME day as the BMO report
    assert len(events) == 1
    assert events[0].ticker == "AAPL"
    assert events[0].days_since == 0


def test_get_upcoming_earnings_real_data():
    watcher = ew.EarningsWatcher(tickers=["AAPL"])
    events = watcher.get_upcoming_earnings(days_ahead=200, now=pd.Timestamp("2024-12-01"))
    if not events:
        pytest.skip("network unavailable / yfinance unreachable")
    assert events[0].ticker == "AAPL"
    assert events[0].days_until >= 0
    assert events == sorted(events, key=lambda e: e.days_until)


def test_get_upcoming_earnings_respects_window():
    watcher = ew.EarningsWatcher(tickers=["AAPL"])
    events = watcher.get_upcoming_earnings(days_ahead=5, now=pd.Timestamp("2024-12-01"))
    assert all(e.days_until <= 5 for e in events)
