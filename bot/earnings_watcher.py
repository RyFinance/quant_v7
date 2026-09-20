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

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from loguru import logger

from earnings.ingestion import fetch_ticker_earnings_live, fetch_upcoming_earnings_date
from earnings.signal import MARKET_CLOSE_HOUR

REPORTS_DIR = Path(__file__).parent.parent / "reports"
DATA_DIR = Path(__file__).parent.parent / "data"

# If no ticker in the universe has reported within this many days, the
# earnings feed itself has almost certainly gone stale (a normal quarter
# never leaves a 75-name universe silent that long).
EARNINGS_FEED_STALE_DAYS = 100
# Below this share of tickers answering, the announcement-dated endpoint is treated
# as down (it answers for nearly every name when it works).
DATED_FEED_MIN_COVERAGE = 0.5

# Earnings history is fetched per ticker over the network, which at 503 names
# takes ~10 minutes sequentially -- longer than the gap between a report and the
# close the bot trades at. The fetches are independent I/O, so they run on a
# small thread pool; kept deliberately low so the bot stays a polite client of a
# free endpoint rather than hammering it.
MAX_FETCH_WORKERS = 6


def effective_trading_date(earnings_timestamp: pd.Timestamp) -> pd.Timestamp:
    """Business day on which an announcement becomes tradable at the close:
    the same day for a report before the close, the next business day for
    one at/after the close. Mirrors earnings/signal.py's
    `_effective_trading_date` with a business-day calendar in place of the
    cached price index (same holiday simplification as position_manager.py)."""
    target = earnings_timestamp.normalize()
    if earnings_timestamp.hour >= MARKET_CLOSE_HOUR:
        target = target + pd.Timedelta(days=1)
    return target if target.dayofweek < 5 else target + pd.offsets.BDay(1)


def report_timing(earnings_timestamp: pd.Timestamp) -> str:
    """'before_open', 'during_session', 'after_close', or 'unknown' when no
    time of day is known (ET wall-clock, as yfinance reports it)."""
    if earnings_timestamp == earnings_timestamp.normalize():
        return "unknown"
    if earnings_timestamp.hour >= MARKET_CLOSE_HOUR:
        return "after_close"
    if (earnings_timestamp.hour, earnings_timestamp.minute) < (9, 30):
        return "before_open"
    return "during_session"


def load_validated_universe() -> list[str]:
    """The traded universe: the full 503-name S&P 500 set the production model
    was fit and statistically validated on (18,678 labeled events; see
    reports/PEAD_REVALIDATION_REPORT.md and signal_pipeline.fit_or_load).

    WIDENED 2026-09-17 (75 -> 503). The bot previously traded only the Phase-1
    top-75 liquid names while scoring them with a model fit on all 503 -- the
    narrowest slice of the validated sample, worth ~72 earnings events a
    quarter against ~480 across the full set. The revalidation's liquidity-tier
    check found no clean edge difference across liquidity tertiles, so the
    restriction was costing event count without buying a stronger edge. Risk is
    unchanged in aggregate: bot/run_cycle.py cuts the per-position cap so the
    same exposure budget spreads over more names."""
    path = DATA_DIR / "expanded_universe_all_tickers.txt"
    return [t.strip() for t in path.read_text().replace("\n", ",").split(",") if t.strip()]


def load_breaker_universe() -> list[str]:
    """The Phase-1 top-75 liquid names, kept as the market-wide risk gauge for
    the circuit breaker and the trading-session check. The breaker's thresholds
    were calibrated against exactly this basket
    (reports/circuit_breaker_daily_production.csv), so feeding it a different
    universe would silently invalidate that calibration."""
    path = REPORTS_DIR / "universe_selection.txt"
    return path.read_text().strip().split("\n")[1].split(",")


@dataclass
class UpcomingEarnings:
    ticker: str
    earnings_date: pd.Timestamp
    days_until: int


@dataclass
class ScheduledEarnings:
    ticker: str
    earnings_date: pd.Timestamp
    timing: str
    eps_estimate: float | None
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
        # Per-ticker histories from the latest get_recently_reported() call,
        # reused for the upcoming schedule so a cycle fetches each ticker once.
        self.last_fetched: dict[str, pd.DataFrame] = {}
        self.newest_report: pd.Timestamp | None = None
        # How many fetched tickers the announcement-dated endpoint answered for,
        # and how many recent reports had to be dated from the schedule log.
        self.dated_feed_answered = 0
        self.dated_feed_asked = 0
        self.schedule_dated_reports = 0

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

        Eligibility is keyed on `effective_trading_date` (see module
        docstring): a report before the close is eligible from its own day,
        one at/after the close from the next business day, so the bot never
        enters at a close that predates the announcement.

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
        self.last_fetched = {}
        self.newest_report = None
        self.dated_feed_answered = self.dated_feed_asked = self.schedule_dated_reports = 0

        def fetch(ticker: str):
            try:
                return ticker, fetch_ticker_earnings_live(ticker)
            except Exception as e:  # a single bad ticker must not sink the cycle
                logger.warning(f"{ticker}: earnings history fetch failed ({e!r})")
                return ticker, pd.DataFrame()

        if len(self.tickers) > 1:
            with ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS) as pool:
                fetched = dict(pool.map(fetch, self.tickers))
        else:
            fetched = dict(fetch(t) for t in self.tickers)

        # Ordered by ticker, not by whichever fetch finished first, so a cycle's
        # candidate list does not depend on network timing.
        for ticker in self.tickers:
            df = fetched.get(ticker)
            if df is None:
                continue
            if "primary_ok" in df.attrs:
                self.dated_feed_asked += 1
                self.dated_feed_answered += bool(df.attrs["primary_ok"])
            if df.empty:
                continue
            self.last_fetched[ticker] = df
            reported = df[df["eps_actual"].notna() & (df["earnings_date"].dt.normalize() <= now)]
            # A quarter-end date is only a placeholder for an unknown announcement date,
            # so it never counts as evidence that the feed is current.
            trusted = reported[reported["date_source"] != "quarter_end"] if "date_source" in reported else reported
            if not trusted.empty:
                latest = trusted["earnings_date"].max()
                self.newest_report = latest if self.newest_report is None else max(self.newest_report, latest)
            effective = reported["earnings_date"].apply(effective_trading_date)
            recent = reported[(effective >= floor) & (effective <= now)]
            if "date_source" in recent:
                self.schedule_dated_reports += int((recent["date_source"] == "scheduled").sum())
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

    def dated_feed_down(self, min_coverage: float = DATED_FEED_MIN_COVERAGE) -> bool:
        """True when the announcement-dated endpoint answered for too few tickers
        in the last get_recently_reported() call."""
        return self.dated_feed_asked > 0 and self.dated_feed_answered < min_coverage * self.dated_feed_asked

    def feed_looks_stale(self, now: pd.Timestamp | None = None) -> bool:
        """True when the last get_recently_reported() call saw no report
        anywhere in the universe for EARNINGS_FEED_STALE_DAYS."""
        now = (now or pd.Timestamp.now()).normalize()
        if self.newest_report is None:
            return True
        return (now - self.newest_report.normalize()).days > EARNINGS_FEED_STALE_DAYS

    def scheduled_from_last_fetch(self, days_ahead: int = 60, now: pd.Timestamp | None = None) -> list[ScheduledEarnings]:
        """Upcoming, not-yet-reported announcements within `days_ahead`,
        read from the histories the last get_recently_reported() call
        already fetched (no extra requests)."""
        now = (now or pd.Timestamp.now()).normalize()
        cutoff = now + pd.Timedelta(days=days_ahead)
        out: list[ScheduledEarnings] = []
        for ticker, df in self.last_fetched.items():
            dates = df["earnings_date"]
            upcoming = df[df["eps_actual"].isna() & (dates.dt.normalize() >= now) & (dates.dt.normalize() <= cutoff)]
            if upcoming.empty:
                continue
            row = upcoming.sort_values("earnings_date").iloc[0]
            estimate = row.get("eps_estimate")
            out.append(ScheduledEarnings(
                ticker=ticker, earnings_date=row["earnings_date"], timing=report_timing(row["earnings_date"]),
                eps_estimate=None if pd.isna(estimate) else float(estimate),
                days_until=(row["earnings_date"].normalize() - now).days,
            ))
        out.sort(key=lambda e: (e.earnings_date, e.ticker))
        return out
