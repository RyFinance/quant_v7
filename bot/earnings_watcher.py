"""Watches the validated universe for upcoming and just-reported earnings.

DATA SOURCE FIX (2026-08-18, found during the live dry run): originally
built on `earnings.ingestion.fetch_ticker_earnings`
(`Ticker.get_earnings_dates`), matching the historical batch pipeline. That
endpoint turned out to be STALE in this environment -- empirically capped
around April/May 2025 for every ticker checked (AAPL, MSFT, NVDA, JPM),
over a year behind real "now," even though this project's OHLCV price data
is fully current. `earnings.ingestion.fetch_ticker_earnings_live` (a
union of the historical endpoint with the current-but-quarter-end-dated
`earnings_history` endpoint, plus `Ticker.calendar` for the next scheduled
date) is what this module uses instead -- see that function's docstring
for the full trade-off. The historical training/backtest pipeline
(earnings/sue.py, reports/run_pead_*.py) is UNCHANGED and unaffected by
this -- it only ever needed data through ~mid-2025, which the original
endpoint has completely.

Two real, working queries against real (now current) data:
  * `get_upcoming_earnings`  -- events strictly in the future, within the
    next `days_ahead` calendar days (eps_actual still unreported).
  * `get_recently_reported`  -- events in the past `days_back` calendar
    days that HAVE reported (eps_actual present) -- this is the trigger
    signal_pipeline.py needs, since a PEAD entry decision requires knowing
    the actual surprise, which only exists after the report lands.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from loguru import logger

from earnings.ingestion import fetch_ticker_earnings_live, fetch_upcoming_earnings_date

REPORTS_DIR = Path(__file__).parent.parent / "reports"


def load_validated_universe() -> list[str]:
    """The Phase 1 validated universe (top-75 liquid S&P 500 names) that the
    PEAD signal was built and backtested against -- reused as-is, not
    reselected, so the bot only ever watches names the strategy was
    actually validated on."""
    path = REPORTS_DIR / "universe_selection.txt"
    return path.read_text().strip().split("\n")[1].split(",")


@dataclass
class UpcomingEarnings:
    ticker: str
    earnings_date: pd.Timestamp
    days_until: int


@dataclass
class ReportedEarnings:
    ticker: str
    earnings_date: pd.Timestamp
    eps_estimate: float | None
    eps_actual: float | None
    surprise_pct: float | None
    days_since: int


class EarningsWatcher:
    def __init__(self, tickers: list[str] | None = None):
        self.tickers = tickers or load_validated_universe()

    def get_upcoming_earnings(self, days_ahead: int = 14, now: pd.Timestamp | None = None) -> list[UpcomingEarnings]:
        """Real query against real, current yfinance data (`Ticker.calendar`
        -- see module docstring for why this, not `get_earnings_dates`):
        which tickers in the validated universe have a scheduled earnings
        date in the next `days_ahead` days?"""
        now = (now or pd.Timestamp.now()).normalize()
        cutoff = now + pd.Timedelta(days=days_ahead)
        out: list[UpcomingEarnings] = []
        for ticker in self.tickers:
            date = fetch_upcoming_earnings_date(ticker)
            if date is None:
                continue
            date = date.normalize()
            if now <= date <= cutoff:
                out.append(UpcomingEarnings(ticker=ticker, earnings_date=date, days_until=(date - now).days))
        out.sort(key=lambda e: e.days_until)
        logger.info(f"earnings watcher: {len(out)} upcoming earnings events in the next {days_ahead}d "
                    f"across {len(self.tickers)} tickers")
        return out

    def get_recently_reported(self, days_back: int = 3, now: pd.Timestamp | None = None) -> list[ReportedEarnings]:
        """Real query: which tickers in the validated universe reported
        earnings (an actual EPS is present) within the last `days_back`
        days? This is the entry trigger for signal_pipeline.py -- PEAD
        needs the real surprise, which only exists post-report.

        Uses `fetch_ticker_earnings_live` (see module docstring) so this
        can actually see current quarters -- `earnings_date` for the
        current-quarter rows is a quarter-end APPROXIMATION, not the true
        announcement date (that function's docstring explains the
        trade-off), so `days_since` here is approximate for very recent
        events, not exact to the day.

        REAL BUG FIXED HERE (found 2026-08-19 by an adversarial review of
        the historical-replay harness, which flagged that this function's
        actual behavior diverges from the harness's pinned-data
        equivalent): the eligibility window used to compare `earnings_date`
        -- which carries a real time-of-day component (e.g. "16:30" for an
        after-close report) -- directly against `now`, which is always
        midnight-normalized. For a before-market-open (BMO) event reported
        e.g. at "08:00" on day D, `earnings_date (D 08:00) <= now (D 00:00)`
        is FALSE on day D itself -- so a same-day BMO report was never
        detected until day D+1, a full trading day late, even though BMO
        earnings are public and actionable the same day. Fixed by comparing
        `earnings_date` NORMALIZED (time-of-day dropped) against the
        already-normalized `floor`/`now`, so day-D events of either
        timing are visible starting day D -- matching the day-level
        granularity this whole system already operates at (see
        earnings/signal.py's `_effective_trading_date`, which makes the
        same "day-level, not intraday-precise" choice for the historical
        training data this live path is meant to mirror)."""
        now = (now or pd.Timestamp.now()).normalize()
        floor = now - pd.Timedelta(days=days_back)
        out: list[ReportedEarnings] = []
        for ticker in self.tickers:
            df = fetch_ticker_earnings_live(ticker)
            if df.empty:
                continue
            earnings_date_normalized = df["earnings_date"].dt.normalize()
            recent = df[(earnings_date_normalized >= floor) & (earnings_date_normalized <= now) & df["eps_actual"].notna()]
            for _, row in recent.iterrows():
                days_since = (now - row["earnings_date"].normalize()).days
                out.append(ReportedEarnings(
                    ticker=ticker, earnings_date=row["earnings_date"],
                    eps_estimate=row.get("eps_estimate"), eps_actual=row.get("eps_actual"),
                    surprise_pct=row.get("surprise_pct"), days_since=days_since,
                ))
        out.sort(key=lambda e: e.days_since)
        logger.info(f"earnings watcher: {len(out)} tickers reported earnings in the last {days_back}d "
                    f"across {len(self.tickers)} tickers")
        return out
