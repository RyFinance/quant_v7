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


def test_load_validated_universe_is_the_full_validated_sample():
    """The traded universe is the same 503-name set the production model was
    fit and validated on, not the Phase-1 top-75 slice it used to trade."""
    tickers = ew.load_validated_universe()
    assert len(tickers) == 503
    assert "AAPL" in tickers and "ABNB" in tickers  # a top-75 name and one only in the wider set
    assert len(set(tickers)) == len(tickers)


def test_breaker_universe_stays_the_calibrated_basket():
    """The circuit breaker's thresholds were calibrated on the top-75 basket,
    so its input must not follow the traded universe."""
    breaker = ew.load_breaker_universe()
    assert len(breaker) == 75
    assert set(breaker) < set(ew.load_validated_universe())


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


def _history(rows):
    return pd.DataFrame(rows, columns=["ticker", "earnings_date", "eps_estimate", "eps_actual", "surprise_pct"])


def test_after_close_report_becomes_eligible_the_next_business_day(monkeypatch):
    """An after-close report must not be tradable at that same day's close
    (the label and the backtest enter at the NEXT session's close)."""
    history = _history([["ORCL", pd.Timestamp("2026-09-10 16:05:00"), 1.74, 1.92, 10.45]])
    monkeypatch.setattr(ew, "fetch_ticker_earnings_live", lambda ticker: history)
    watcher = ew.EarningsWatcher(tickers=["ORCL"])

    assert watcher.get_recently_reported(days_back=3, now=pd.Timestamp("2026-09-10")) == []
    events = watcher.get_recently_reported(days_back=3, now=pd.Timestamp("2026-09-11"))
    assert [e.ticker for e in events] == ["ORCL"]


def test_friday_after_close_report_is_eligible_monday(monkeypatch):
    history = _history([["ADBE", pd.Timestamp("2026-09-11 16:05:00"), 6.08, 6.13, 0.71]])
    monkeypatch.setattr(ew, "fetch_ticker_earnings_live", lambda ticker: history)
    watcher = ew.EarningsWatcher(tickers=["ADBE"])

    assert ew.effective_trading_date(pd.Timestamp("2026-09-11 16:05:00")) == pd.Timestamp("2026-09-14")
    assert len(watcher.get_recently_reported(days_back=3, now=pd.Timestamp("2026-09-14"))) == 1


def test_quarter_end_dated_rows_are_never_a_fresh_report(monkeypatch):
    """Regression for the 2026-09 bug: a report surfaced only via a
    quarter-end-dated row was weeks outside the window when it appeared."""
    history = _history([["AAPL", pd.Timestamp("2026-06-30"), 1.89, 2.02, 6.74]])
    monkeypatch.setattr(ew, "fetch_ticker_earnings_live", lambda ticker: history)
    watcher = ew.EarningsWatcher(tickers=["AAPL"])
    assert watcher.get_recently_reported(days_back=3, now=pd.Timestamp("2026-07-31")) == []


def test_schedule_and_staleness_come_from_the_same_fetch(monkeypatch):
    history = _history([
        ["JPM", pd.Timestamp("2026-07-14 06:00:00"), 5.80, 6.14, 5.86],
        ["JPM", pd.Timestamp("2026-10-13 08:00:00"), 5.89, None, None],
    ])
    calls = []
    monkeypatch.setattr(ew, "fetch_ticker_earnings_live", lambda ticker: calls.append(ticker) or history)
    watcher = ew.EarningsWatcher(tickers=["JPM"])
    now = pd.Timestamp("2026-09-17")
    watcher.get_recently_reported(days_back=3, now=now)

    scheduled = watcher.scheduled_from_last_fetch(days_ahead=60, now=now)
    assert calls == ["JPM"]
    assert [(e.ticker, e.timing, e.days_until) for e in scheduled] == [("JPM", "before_open", 26)]
    assert watcher.feed_looks_stale(now=now) is False
    assert watcher.feed_looks_stale(now=pd.Timestamp("2027-01-01")) is True
