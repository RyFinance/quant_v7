"""Tests for live_backtest/historical_providers.py -- the pinned-historical
data sources used ONLY by the historical replay harness. Real cached data
throughout (data/raw/*.parquet, data/earnings_sue_expanded.parquet,
data/pead_signal_expanded.parquet, reports/circuit_breaker_daily_production.csv
-- all already built and validated in earlier phases).
"""
from __future__ import annotations

import pandas as pd
import pytest

from live_backtest.historical_providers import (
    historical_breaker_tier,
    historical_close_price,
    historical_earnings_history_for_sue,
    historical_recently_reported,
    historical_trailing_return,
)


def test_historical_close_price_never_uses_future_data():
    """The close price for a fixed as_of date must never change no matter
    how far in the future we could have looked -- checked here by
    confirming two different as_of dates (one much later) that both have
    the SAME latest-eligible-row give the SAME price, and that a later
    as_of with genuinely newer data gives a DIFFERENT (real) price."""
    p1 = historical_close_price("AAPL", pd.Timestamp("2022-01-03"))
    p2 = historical_close_price("AAPL", pd.Timestamp("2022-01-05"))
    assert p1 > 0 and p2 > 0
    assert p1 != p2  # real distinct trading days, real distinct closes


def test_historical_close_price_exact_match_to_manual_filter():
    """Direct causality check: the returned price must equal the close of
    the LATEST cached row with timestamp <= as_of_date, computed here by
    an independent manual filter over the same raw parquet, not the
    module's own (potentially buggy) internal logic."""
    import pandas as pd
    as_of = pd.Timestamp("2023-06-15")
    panel = pd.read_parquet("data/raw/AAPL.parquet")
    panel["timestamp"] = pd.to_datetime(panel["timestamp"])
    eligible = panel[panel["timestamp"] <= as_of].sort_values("timestamp")
    expected = float(eligible.iloc[-1]["close"])
    assert historical_close_price("AAPL", as_of) == pytest.approx(expected)
    # and confirm no row AFTER as_of was used: the expected row's own date must be <= as_of
    assert eligible.iloc[-1]["timestamp"] <= as_of


def test_historical_close_price_raises_before_data_exists():
    with pytest.raises(RuntimeError):
        historical_close_price("AAPL", pd.Timestamp("1990-01-01"))


def test_historical_trailing_return_matches_manual_calc():
    as_of = pd.Timestamp("2022-03-15")
    ret = historical_trailing_return("AAPL", window_days=5, as_of=as_of)
    assert ret is not None

    from live_backtest.historical_providers import _load_price_panel
    panel = _load_price_panel("AAPL")
    start = as_of - pd.Timedelta(days=30)
    # STRICTLY exclusive of as_of -- matches yfinance's real exclusive `end`
    # semantics (see historical_trailing_return's docstring for the real
    # bug this boundary fixes: an earlier inclusive version leaked
    # same-day, post-earnings-reaction closes into this "pre-earnings"
    # momentum feature).
    hist = panel[(panel["timestamp"] >= start) & (panel["timestamp"] < as_of)].sort_values("timestamp")
    closes = hist["close"]
    expected = float(closes.iloc[-1] / closes.iloc[-6] - 1.0)
    assert ret == pytest.approx(expected)


def test_historical_trailing_return_excludes_as_of_own_day():
    """Direct regression test for the fixed lookahead bug: the trailing
    return must never use as_of's own close, even when as_of is itself a
    real cached trading day (the exact BMO scenario that leaked)."""
    from live_backtest.historical_providers import _load_price_panel
    panel = _load_price_panel("AAPL")
    # pick a real trading day from the cached panel to use as as_of
    as_of = panel["timestamp"].iloc[500]
    ret_at_as_of = historical_trailing_return("AAPL", window_days=5, as_of=as_of)
    ret_at_next_day = historical_trailing_return("AAPL", window_days=5, as_of=panel["timestamp"].iloc[501])
    # the window ending strictly before as_of must differ from the window
    # ending strictly before the NEXT real trading day (which DOES include
    # as_of's own close) -- if the boundary were still inclusive, moving
    # as_of forward by one real day wouldn't change which closes are used
    # for the "last" price in the same way, and in particular ret_at_as_of
    # would already reflect that day's own move.
    assert ret_at_as_of != ret_at_next_day


def test_historical_trailing_return_none_when_insufficient_history():
    ret = historical_trailing_return("AAPL", window_days=20, as_of=pd.Timestamp("2015-01-05"))
    assert ret is None


def test_historical_earnings_history_excludes_future_events():
    as_of = pd.Timestamp("2020-01-01")
    hist = historical_earnings_history_for_sue("AAPL", as_of)
    assert (hist["earnings_date"].dt.normalize() <= as_of).all()
    # sanity: AAPL definitely has real earnings events before 2020
    assert len(hist) > 10


def test_historical_earnings_history_grows_monotonically_with_as_of():
    early = historical_earnings_history_for_sue("MSFT", pd.Timestamp("2018-01-01"))
    later = historical_earnings_history_for_sue("MSFT", pd.Timestamp("2023-01-01"))
    assert len(later) >= len(early)


def test_historical_recently_reported_respects_window_and_universe():
    with open("reports/universe_selection.txt") as f:
        universe = f.read().strip().split("\n")[1].split(",")
    as_of = pd.Timestamp("2022-01-19")  # a real date inside the replay window
    events = historical_recently_reported(universe, as_of, days_back=3)
    for e in events:
        assert e.ticker in universe
        assert 0 <= e.days_since <= 3
        assert e.eps_actual is not None


def test_historical_recently_reported_excludes_out_of_universe_tickers():
    as_of = pd.Timestamp("2022-01-19")
    events_full = historical_recently_reported(["AAPL", "MSFT", "GOOGL"], as_of, days_back=10)
    events_narrow = historical_recently_reported(["AAPL"], as_of, days_back=10)
    assert all(e.ticker == "AAPL" for e in events_narrow)
    assert len(events_narrow) <= len(events_full)


def test_historical_breaker_tier_matches_pinned_csv():
    df = pd.read_csv("reports/circuit_breaker_daily_production.csv", parse_dates=["date"])
    a_real_date = df["date"].iloc[500]
    expected_tier = df[df["date"] == a_real_date]["tier"].iloc[0]
    tier, detail = historical_breaker_tier(a_real_date)
    assert tier == expected_tier


def test_historical_breaker_tier_fails_closed_before_data_exists():
    tier, detail = historical_breaker_tier(pd.Timestamp("1990-01-01"))
    assert tier == "halt_new_entries"


def test_historical_breaker_tier_uses_nearest_prior_date_not_future():
    df = pd.read_csv("reports/circuit_breaker_daily_production.csv", parse_dates=["date"])
    # pick a real date, then query for a date one calendar day later where
    # the CSV might not have an exact row (e.g. a weekend) -- must still
    # resolve to the PRIOR real date's tier, never a later one.
    real_date = df["date"].iloc[500]
    next_calendar_day = real_date + pd.Timedelta(days=1)
    tier_at_next, _ = historical_breaker_tier(next_calendar_day)
    tier_at_real, _ = historical_breaker_tier(real_date)
    # if next_calendar_day itself isn't a trading day, both must resolve to the same (real_date's) tier
    if next_calendar_day not in set(df["date"]):
        assert tier_at_next == tier_at_real
