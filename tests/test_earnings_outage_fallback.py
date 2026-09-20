"""The live earnings feed must keep working when yfinance's dated endpoint
(`get_earnings_dates`) returns nothing -- as it did for every ticker on
2026-09-18. Before the fallback, each new actual came back dated at fiscal
quarter-end, outside the watcher's window, and the staleness alarm stayed quiet
because quarter-end dates looked recent: the bot silently stopped trading.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import bot.earnings_watcher as ew
import earnings.ingestion as ing
from bot import run_cycle


def fake_ticker(dated: pd.DataFrame | None, history: pd.DataFrame | None, next_date=None):
    class FakeTicker:
        def __init__(self, *_a, **_k):
            pass

        def get_earnings_dates(self, limit=100):
            return dated

        @property
        def earnings_history(self):
            return history

        @property
        def calendar(self):
            return {"Earnings Date": [next_date]} if next_date is not None else {}

    return FakeTicker


HISTORY = pd.DataFrame(
    {"epsActual": [1.50, 1.65], "epsEstimate": [1.40, 1.60], "surprisePercent": [0.0714, 0.0313]},
    index=pd.to_datetime(["2026-03-31", "2026-06-30"]).rename("quarter"),
)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Announcement-dated history as the training pipeline caches it."""
    monkeypatch.setattr(ing, "RAW_DIR", tmp_path)
    rows = pd.DataFrame({
        "ticker": "AAA",
        "earnings_date": pd.to_datetime(["2025-01-30 16:30", "2025-05-01 16:30"]),
        "eps_estimate": [1.2, 1.3], "eps_actual": [1.25, 1.35], "surprise_pct": [4.0, 3.8],
    })
    rows.to_parquet(tmp_path / "AAA.parquet", index=False)
    return tmp_path


def log_date(date: str, ticker: str = "AAA") -> None:
    with open(ing.SCHEDULE_LOG_FILE, "a") as f:
        f.write(json.dumps({"ticker": ticker, "date": date, "source": "calendar", "seen_at": 0}) + "\n")


def test_outage_dates_new_actual_from_schedule_log(monkeypatch, cache):
    monkeypatch.setattr(ing.yf, "Ticker", fake_ticker(None, HISTORY, next_date=pd.Timestamp("2026-10-29").date()))
    log_date("2026-07-30")
    df = ing.fetch_ticker_earnings_live("AAA", now=pd.Timestamp("2026-08-01"))
    assert df.attrs["primary_ok"] is False
    row = df[df["eps_actual"] == 1.65].iloc[0]
    assert row["earnings_date"] == pd.Timestamp("2026-07-30 16:00")        # stamped at the close
    assert row["date_source"] == "scheduled"
    assert ew.effective_trading_date(row["earnings_date"]) == pd.Timestamp("2026-07-31")  # next session
    # the cached announcement-dated history is there for SUE's trailing surprises
    assert (df["date_source"] == "announced").sum() == 2
    # a quarter with no logged date keeps its quarter-end placeholder
    assert df[df["eps_actual"] == 1.50].iloc[0]["date_source"] == "quarter_end"
    # the calendar's next date was logged, and returned as an upcoming row
    assert pd.Timestamp("2026-10-29") in ing.scheduled_dates_seen("AAA")
    upcoming = df[df["eps_actual"].isna()]
    assert upcoming["earnings_date"].tolist() == [pd.Timestamp("2026-10-29")]


def test_outage_never_uses_a_scheduled_date_that_has_not_happened(monkeypatch, cache):
    monkeypatch.setattr(ing.yf, "Ticker", fake_ticker(None, HISTORY))
    log_date("2026-07-30")
    df = ing.fetch_ticker_earnings_live("AAA", now=pd.Timestamp("2026-07-20"))
    assert df[df["eps_actual"] == 1.65].iloc[0]["date_source"] == "quarter_end"


def test_working_feed_records_future_dates_for_later_outages(monkeypatch, tmp_path):
    monkeypatch.setattr(ing, "RAW_DIR", tmp_path)
    dated = pd.DataFrame(
        {"EPS Estimate": [1.7, 1.6], "Reported EPS": [float("nan"), 1.65], "Surprise(%)": [float("nan"), 3.1]},
        index=pd.to_datetime(["2026-10-29 16:30", "2026-07-30 16:30"]),
    )
    monkeypatch.setattr(ing.yf, "Ticker", fake_ticker(dated, HISTORY))
    df = ing.fetch_ticker_earnings_live("AAA")
    assert df.attrs["primary_ok"] is True
    assert ing.scheduled_dates_seen("AAA") == [pd.Timestamp("2026-10-29")]
    ing.fetch_ticker_earnings_live("AAA")                      # a second sighting is not re-logged
    assert len(ing.SCHEDULE_LOG_FILE.read_text().splitlines()) == 1


def test_watcher_flags_dated_feed_outage_and_ignores_quarter_end_dates(monkeypatch, cache):
    monkeypatch.setattr(ing.yf, "Ticker", fake_ticker(None, HISTORY))
    watcher = ew.EarningsWatcher(tickers=["AAA"])
    reported = watcher.get_recently_reported(days_back=3, now=pd.Timestamp("2026-08-03"))
    assert reported == []
    assert watcher.dated_feed_down()
    # the 2026-06-30 quarter-end placeholder is not evidence of a current feed;
    # the newest trusted date is the cached 2025-05-01 announcement -> stale
    assert watcher.newest_report == pd.Timestamp("2025-05-01 16:30")
    assert watcher.feed_looks_stale(now=pd.Timestamp("2026-08-03"))


def test_watcher_detects_schedule_dated_report(monkeypatch, cache):
    monkeypatch.setattr(ing.yf, "Ticker", fake_ticker(None, HISTORY))
    log_date("2026-07-30")
    watcher = ew.EarningsWatcher(tickers=["AAA"])
    reported = watcher.get_recently_reported(days_back=3, now=pd.Timestamp("2026-07-31"))
    assert [(r.ticker, r.earnings_date) for r in reported] == [("AAA", pd.Timestamp("2026-07-30 16:00"))]
    assert watcher.schedule_dated_reports == 1


def test_event_key_is_one_decision_per_announcement_day():
    assert run_cycle._event_key("AAA", "2026-07-30T16:00:00") == run_cycle._event_key("AAA", "2026-07-30T16:05:00")
    assert run_cycle._event_key("AAA", "2026-07-30T16:00:00") != run_cycle._event_key("AAA", "2026-07-31T08:00:00")
