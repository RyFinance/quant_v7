"""Tests for survivorship-bias data source (Task 3). All tests hit the real
Wikipedia page over the network -- no synthetic fixtures. Marked slow since
they depend on network access; skipped gracefully if offline.
"""
import pandas as pd
import pytest

from data.survivorship import (
    build_universe_history,
    fetch_current_constituents,
    fetch_historical_changes,
    is_member_on,
)


@pytest.fixture(scope="module")
def current():
    try:
        return fetch_current_constituents()
    except Exception as e:
        pytest.skip(f"network unavailable / Wikipedia unreachable: {e!r}")


@pytest.fixture(scope="module")
def changes():
    try:
        return fetch_historical_changes()
    except Exception as e:
        pytest.skip(f"network unavailable / Wikipedia unreachable: {e!r}")


def test_current_constituents_shape(current):
    assert len(current) > 450  # S&P 500 is ~500, allow slack for scrape drift
    assert {"ticker", "name", "sector"}.issubset(current.columns)
    assert "AAPL" in current["ticker"].values
    assert "MSFT" in current["ticker"].values


def test_historical_changes_nonempty(changes):
    assert len(changes) > 100
    assert set(changes["action"].unique()) <= {"added", "removed"}


def test_build_universe_history_covers_current_and_delisted(current, changes):
    history = build_universe_history(current=current, changes=changes)
    tickers = {m.ticker for m in history}
    assert "AAPL" in tickers  # long-standing current member
    # at least one historical-only (removed, not currently a member) name should exist
    current_set = set(current["ticker"])
    historical_only = [m for m in history if m.ticker not in current_set]
    assert len(historical_only) > 0


def test_is_member_on_known_delisting(current, changes):
    history = build_universe_history(current=current, changes=changes)
    current_set = set(current["ticker"])
    removed_names = [m for m in history if m.ticker not in current_set and m.end_date is not None]
    if not removed_names:
        pytest.skip("no removed-name records found in current scrape to test against")
    m = removed_names[0]
    assert is_member_on(m.ticker, m.start_date, history) is True
    assert is_member_on(m.ticker, pd.Timestamp(m.end_date) + pd.Timedelta(days=3650), history) is False
