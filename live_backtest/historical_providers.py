"""Pinned-historical drop-in replacements for every LIVE data call
bot/run_cycle.py's real code makes, used ONLY by
live_backtest/run_historical_replay.py to backtest the actual live code
path (scheduling/ledger/risk-gate/heartbeat) against real historical data
-- never imported by, or reachable from, bot/ itself. Production code is
completely unmodified; these are monkeypatched IN by the replay harness at
call time, exactly the same technique this project's own tests already
use (tests/test_bot_run_cycle.py monkeypatches EarningsWatcher methods for
controlled testing) -- this just extends it to a full historical run
instead of one synthetic event.

CAUSALITY IS THE ENTIRE POINT of this module -- every lookup here takes an
explicit `as_of_date` and must never read a row dated after it. Each
function's docstring states its exact cutoff rule. This is exactly the
class of bug (lookahead/leakage) this project has hit for real before
(Part B1 residual returns, Part C2 labeling, earnings/sue.py's
shift(1)-before-rolling trailing std) -- so every function here is
written to match, not reinvent, those same established patterns, and the
whole module gets an independent adversarial verification pass (see
reports/live_backtest_lookahead_verification.json) before its output is
trusted.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from bot.earnings_watcher import ReportedEarnings

DATA_DIR = Path(__file__).parent.parent / "data"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
RAW_DIR = DATA_DIR / "raw"

MOMENTUM_LOOKBACK_CALENDAR_DAYS = 30  # matches bot/signal_pipeline.py's MOMENTUM_LOOKBACK_DAYS exactly

_price_cache: dict[str, pd.DataFrame] = {}
_sue_history_df: pd.DataFrame | None = None
_signal_df: pd.DataFrame | None = None
_breaker_df: pd.DataFrame | None = None


def _load_price_panel(ticker: str) -> pd.DataFrame:
    if ticker not in _price_cache:
        path = RAW_DIR / f"{ticker}.parquet"
        if not path.exists():
            _price_cache[ticker] = pd.DataFrame()
        else:
            df = pd.read_parquet(path)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            _price_cache[ticker] = df.sort_values("timestamp").reset_index(drop=True)
    return _price_cache[ticker]


def historical_close_price(ticker: str, as_of_date: pd.Timestamp) -> float:
    """Real close price for `ticker` on the latest cached trading day
    <= as_of_date (inclusive -- as_of_date's own close IS usable, since a
    paper fill "today" naturally happens at/after today's own price is
    known; never a date AFTER as_of_date). Raises RuntimeError if none
    exists, mirroring bot/execution.py's get_current_price contract:
    never fabricate a fill price."""
    as_of_date = pd.Timestamp(as_of_date).normalize()
    panel = _load_price_panel(ticker)
    eligible = panel[panel["timestamp"] <= as_of_date]
    if eligible.empty:
        raise RuntimeError(f"no cached historical price for {ticker!r} on or before {as_of_date.date()}")
    return float(eligible.iloc[-1]["close"])


def historical_trailing_return(ticker: str, window_days: int, as_of: pd.Timestamp) -> float | None:
    """Exact semantic match to bot/signal_pipeline.py's `_trailing_return`:
    real trailing return over the `window_days` TRADING days immediately
    before `as_of` (the event's own announcement/effective date, NOT
    necessarily "today" -- this is the same parameter the real function
    receives), using a `MOMENTUM_LOOKBACK_CALENDAR_DAYS`-calendar-day
    window of cached history ending BEFORE `as_of`. Returns None if
    insufficient history, same as the original (never guesses).

    REAL BUG FIXED HERE (found 2026-08-19 by adversarial verification,
    reports/live_backtest_lookahead_verification -- see the workflow
    result for the full writeup): an earlier version of this function
    used an INCLUSIVE `<= as_of` upper bound, on the mistaken assumption
    that it matched the real function's `fetch_ticker_history(...,
    end=as_of)` call. It does not: yfinance's `end` parameter is
    EXCLUSIVE (empirically confirmed --
    `fetch_ticker_history('AAPL', start=..., end='2024-01-09')`'s last
    returned row is 2024-01-08, never the 9th itself), so production's
    real trailing-return window always ends STRICTLY BEFORE `as_of`. The
    inclusive version leaked same-day, post-earnings-reaction closes into
    the "pre-earnings momentum" feature for every before-market-open (BMO)
    event -- confirmed to be ~59% of all events in the pinned dataset
    (11,065/18,844 rows in data/pead_signal_expanded.parquet have
    `date == earnings_date_raw.normalize()`), i.e. a majority-of-events
    lookahead leak, not an edge case. Fixed by making the upper bound
    strictly exclusive (`< as_of`), matching yfinance's real behavior."""
    as_of = pd.Timestamp(as_of).normalize()
    start = as_of - pd.Timedelta(days=MOMENTUM_LOOKBACK_CALENDAR_DAYS)
    panel = _load_price_panel(ticker)
    hist = panel[(panel["timestamp"] >= start) & (panel["timestamp"] < as_of)]
    if hist.empty or len(hist) <= window_days:
        return None
    closes = hist.sort_values("timestamp")["close"]
    window = closes.iloc[-(window_days + 1):]
    if window.isna().any():
        return None
    return float(window.iloc[-1] / window.iloc[0] - 1.0)


def _sue_history() -> pd.DataFrame:
    global _sue_history_df
    if _sue_history_df is None:
        df = pd.read_parquet(DATA_DIR / "earnings_sue_expanded.parquet")
        df["earnings_date"] = pd.to_datetime(df["earnings_date"])
        _sue_history_df = df[["ticker", "earnings_date", "eps_estimate", "eps_actual", "surprise_pct"]].sort_values("earnings_date")
    return _sue_history_df


def historical_earnings_history_for_sue(ticker: str, as_of_date: pd.Timestamp) -> pd.DataFrame:
    """Drop-in replacement for earnings.ingestion.fetch_ticker_earnings_live:
    same output schema (ticker, earnings_date, eps_estimate, eps_actual,
    surprise_pct), sourced from the pinned data/earnings_sue_expanded.parquet
    instead of a live yfinance call. Cutoff: earnings_date (normalized,
    time-of-day dropped) <= as_of_date -- includes an event announced
    EARLIER TODAY (needed so build_feature_row's own
    `sue_df[sue_df["earnings_date"] == event.earnings_date]` lookup finds
    a row for the event actually being scored), but never a future one.
    Causality for the trailing-std SUE calculation itself is enforced
    independently and identically to training by earnings/sue.py's
    `compute_sue` (shift(1) before rolling) -- this function only filters
    the raw event list, it doesn't recompute or relax that guarantee."""
    as_of_date = pd.Timestamp(as_of_date).normalize()
    df = _sue_history()
    eligible = df[(df["ticker"] == ticker) & (df["earnings_date"].dt.normalize() <= as_of_date)]
    return eligible.reset_index(drop=True)


def _signal_history() -> pd.DataFrame:
    global _signal_df
    if _signal_df is None:
        sig = pd.read_parquet(DATA_DIR / "pead_signal_expanded.parquet")
        sig["date"] = pd.to_datetime(sig["date"])
        sig["earnings_date_raw"] = pd.to_datetime(sig["earnings_date_raw"])
        sue = _sue_history()[["ticker", "earnings_date", "eps_estimate", "eps_actual"]]  # surprise_pct already in `sig`, dropped here to avoid a merge-suffix collision
        merged = sig.merge(
            sue.rename(columns={"earnings_date": "earnings_date_raw"}),
            on=["ticker", "earnings_date_raw"], how="left",
        )
        _signal_df = merged
    return _signal_df


def historical_recently_reported(tickers: list[str], as_of_date: pd.Timestamp, days_back: int = 3) -> list[ReportedEarnings]:
    """Drop-in replacement for EarningsWatcher.get_recently_reported.
    Sources from data/pead_signal_expanded.parquet's `date` column, which
    is the REAL, already-computed EFFECTIVE TRADING DATE (BMO/AMC-aligned
    by earnings/signal.py at training time -- an after-market-close
    announcement is shifted to the next TRADING session, not just the next
    calendar day). Eligibility window: as_of_date - days_back <= date <=
    as_of_date, restricted to the given `tickers`.

    DOCUMENTED DIVERGENCE (corrected 2026-08-19, previously overclaimed
    "identical" -- found by adversarial review): this is NOT byte-identical
    to bot/earnings_watcher.py's real get_recently_reported. That function
    compares calendar-day-normalized dates (both BMO and AMC events become
    visible starting their own CALENDAR day), while this pinned-data
    version uses the next TRADING day for AMC events specifically (a
    Friday-afternoon AMC report becomes eligible Monday here, vs. Saturday
    -- a non-trading day -- in the live function's simpler calendar-day
    comparison, which in practice makes no observable difference since
    nothing runs on a Saturday anyway; the two views only differ when a
    holiday sits between the calendar-next-day and the true next trading
    day). This replay therefore validates the IDEALIZED, trading-day-aware
    timing the training data (earnings/signal.py) was built on, not a
    line-for-line replay of the live watcher's simpler heuristic -- an
    intentional choice (the training data's timing is the more correct
    one), not a silent gap. Both BMO and AMC are visible starting their own
    earnings_date_raw.normalize() or later, so lookahead is still
    impossible either way -- this divergence is about entry-detection
    TIMING fidelity, not about future-information leakage."""
    as_of_date = pd.Timestamp(as_of_date).normalize()
    floor = as_of_date - pd.Timedelta(days=days_back)
    df = _signal_history()
    eligible = df[(df["date"] >= floor) & (df["date"] <= as_of_date) & (df["ticker"].isin(tickers))]
    out = []
    for _, row in eligible.iterrows():
        out.append(ReportedEarnings(
            ticker=row["ticker"], earnings_date=row["earnings_date_raw"],
            eps_estimate=row.get("eps_estimate"), eps_actual=row.get("eps_actual"),
            surprise_pct=row["surprise_pct"], days_since=(as_of_date - row["date"]).days,
        ))
    out.sort(key=lambda e: e.days_since)
    return out


def _breaker_history() -> pd.DataFrame:
    global _breaker_df
    if _breaker_df is None:
        df = pd.read_csv(REPORTS_DIR / "circuit_breaker_daily_production.csv", parse_dates=["date"])
        _breaker_df = df.sort_values("date").reset_index(drop=True)
    return _breaker_df


def historical_breaker_tier(as_of_date: pd.Timestamp) -> tuple[str, dict]:
    """Drop-in replacement for risk_gate.current_breaker_tier: looks up
    the REAL, already-computed (Phase 5) tier for the latest cached date
    <= as_of_date -- same "fails closed" philosophy as the original (no
    eligible row -> halt_new_entries, never a silent ARMED default)."""
    as_of_date = pd.Timestamp(as_of_date).normalize()
    df = _breaker_history()
    eligible = df[df["date"] <= as_of_date]
    if eligible.empty:
        return "halt_new_entries", {"reason": "no cached breaker history at or before this date"}
    row = eligible.iloc[-1]
    fired = row["fired_categories"]
    fired = "" if pd.isna(fired) else fired  # empty CSV cell reads back as NaN, not the original empty string
    return row["tier"], {"as_of": str(row["date"]), "fired_categories": fired}
