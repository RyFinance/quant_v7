"""PEAD data foundation -- real earnings-surprise history.

Data source check (per this task's explicit instruction): the spec's
Section 3.2 assumed a "Perplexity Finance connector" would be available
in-session (`finance_ohlcv_histories`, earnings surprise, company peers).
Checked via the connector registry at build time: NOT installed, NOT found
in the registry for this account. That connector is not actually
available here -- documented, not silently worked around.

What IS available and confirmed working: yfinance's
`Ticker.get_earnings_dates(limit=N)`, which returns real historical
(EPS Estimate, Reported EPS, Surprise(%)) rows per earnings date.
Empirically confirmed against AAPL: goes back to 1999 with `limit=100`,
zero missing Surprise(%) values in the modern era. This is sufficient for
our universe's 2015-2026 window with wide margin (quarterly reporters,
~44 quarters in 11 years, well under limit=100).

This IS the real, analyst-estimate-based earnings surprise -- not a
seasonal-random-walk proxy -- so the SUE computed from it in
earnings/sue.py is the standard, defensible construction.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

RAW_DIR = Path(__file__).parent.parent / "data" / "earnings_raw"
# Announcement dates the live bot has seen BEFORE they happened (from the dated
# endpoint's future rows, or Ticker.calendar). Append-only; lets an outage of the
# dated endpoint still date the actuals that arrive (see fetch_ticker_earnings_live).
SCHEDULE_LOG_FILE = Path(__file__).parent.parent / "bot" / "state" / "earnings_schedule_log.jsonl"
_schedule_lock = threading.Lock()
# An actual dated from the schedule log carries no time of day, so it is stamped at
# the close: an unknown-time report becomes tradable the NEXT session, never at a
# close that may predate an after-close announcement.
SCHEDULED_REPORT_HOUR = 16
INTER_REQUEST_SLEEP_S = 0.5
FETCH_LIMIT = 100  # comfortably covers 2015-2026 (~44 quarters) with margin


def fetch_ticker_earnings(ticker: str, limit: int = FETCH_LIMIT) -> pd.DataFrame:
    t = yf.Ticker(ticker)
    try:
        df = t.get_earnings_dates(limit=limit)
    except Exception as e:
        logger.warning(f"{ticker}: earnings fetch failed ({e!r})")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"EPS Estimate": "eps_estimate", "Reported EPS": "eps_actual", "Surprise(%)": "surprise_pct"})
    missing = {"eps_estimate", "eps_actual", "surprise_pct"} - set(df.columns)
    if missing:
        # Some symbols come back without a surprise column at all. Without a
        # real surprise there is no SUE and nothing downstream can use the row,
        # so this is "no data", not an exception to raise on every caller.
        logger.warning(f"{ticker}: earnings rows missing {sorted(missing)}; treating as no data")
        return pd.DataFrame()
    df.index.name = "earnings_date"
    df = df.reset_index()
    df["earnings_date"] = pd.to_datetime(df["earnings_date"]).dt.tz_localize(None)
    df["ticker"] = ticker
    return df[["ticker", "earnings_date", "eps_estimate", "eps_actual", "surprise_pct"]]


def fetch_recent_earnings_actuals(ticker: str) -> pd.DataFrame:
    """Real, CURRENT quarterly actuals via `Ticker.earnings_history` --
    added after discovering (2026-08-18, live-bot dry run) that
    `get_earnings_dates()` / the `earnings_dates` property is STALE in this
    environment: empirically confirmed capped at ~April/May 2025 for every
    ticker checked (AAPL, MSFT, NVDA, JPM), over a year behind "now," even
    though the OHLCV price endpoints used elsewhere in this project are
    fully current through the same date. `earnings_history` is a different
    Yahoo endpoint and IS current (confirmed returning real quarters
    through 2026-06-30 for the same tickers).

    Trade-off, documented: `earnings_history`'s index is the fiscal
    QUARTER-END date, not the actual announcement date `get_earnings_dates`
    provides. Real announcements typically land 2-5 weeks after quarter-end
    for large caps. This function returns the quarter-end as `earnings_date`
    -- an approximation, not the true announcement date -- which is
    acceptable for `fetch_ticker_earnings_live`'s use (detecting THAT a new
    quarter has posted, and its SUE) but should not be trusted for
    intraday-precision announcement timing. `surprisePercent` from this
    endpoint is a decimal fraction (0.0452 == 4.52%); rescaled to the
    percentage-point convention `earnings/sue.py` expects everywhere else.
    """
    t = yf.Ticker(ticker)
    try:
        df = t.earnings_history
    except Exception as e:
        logger.warning(f"{ticker}: earnings_history fetch failed ({e!r})")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index().rename(columns={
        "quarter": "earnings_date", "epsActual": "eps_actual",
        "epsEstimate": "eps_estimate", "surprisePercent": "surprise_pct",
    })
    missing = {"earnings_date", "eps_estimate", "eps_actual", "surprise_pct"} - set(df.columns)
    if missing:
        # See fetch_ticker_earnings: a row with no real surprise is unusable
        # downstream, so report no data rather than raising per caller.
        logger.warning(f"{ticker}: earnings_history missing {sorted(missing)}; treating as no data")
        return pd.DataFrame()
    df["earnings_date"] = pd.to_datetime(df["earnings_date"]).dt.tz_localize(None)
    df["surprise_pct"] = df["surprise_pct"] * 100.0
    df["ticker"] = ticker
    return df[["ticker", "earnings_date", "eps_estimate", "eps_actual", "surprise_pct"]]


def fetch_upcoming_earnings_date(ticker: str) -> pd.Timestamp | None:
    """Real, current next-scheduled-earnings date via `Ticker.calendar`
    (confirmed current, unlike `get_earnings_dates` -- see
    `fetch_recent_earnings_actuals`'s docstring). Returns None if no
    scheduled date is published yet."""
    t = yf.Ticker(ticker)
    try:
        cal = t.calendar
    except Exception as e:
        logger.warning(f"{ticker}: calendar fetch failed ({e!r})")
        return None
    dates = (cal or {}).get("Earnings Date")
    if not dates:
        return None
    return pd.Timestamp(dates[0])


QUARTER_COVERAGE_WINDOW = pd.Timedelta(days=120)


def record_scheduled_dates(ticker: str, dates, source: str, log_file: Path | None = None) -> int:
    """Append not-yet-seen (ticker, announcement date) pairs to the schedule log."""
    log_file = log_file or SCHEDULE_LOG_FILE
    wanted = {pd.Timestamp(d).normalize() for d in dates if d is not None and not pd.isna(d)}
    if not wanted:
        return 0
    with _schedule_lock:
        seen = set(scheduled_dates_seen(ticker, log_file))
        new = sorted(wanted - seen)
        if new:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                for d in new:
                    f.write(json.dumps({"ticker": ticker, "date": d.date().isoformat(), "source": source,
                                        "seen_at": time.time()}) + "\n")
    return len(new)


def scheduled_dates_seen(ticker: str, log_file: Path | None = None) -> list[pd.Timestamp]:
    log_file = log_file or SCHEDULE_LOG_FILE
    if not log_file.exists():
        return []
    out = set()
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ticker") == ticker and rec.get("date"):
                out.add(pd.Timestamp(rec["date"]))
    return sorted(out)


def load_cached_earnings(ticker: str) -> pd.DataFrame:
    """The announcement-dated history the training pipeline cached (data/earnings_raw)."""
    path = RAW_DIR / f"{ticker}.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    return df[["ticker", "earnings_date", "eps_estimate", "eps_actual", "surprise_pct"]]


def _covered(quarter_ends: pd.Series, announced: pd.Series) -> pd.Series:
    return quarter_ends.apply(
        lambda q: bool(((announced > q) & (announced <= q + QUARTER_COVERAGE_WINDOW)).any()))


def fetch_ticker_earnings_live(ticker: str, limit: int = FETCH_LIMIT, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Earnings history for live components (bot/earnings_watcher.py,
    bot/signal_pipeline.py), dated by the REAL announcement timestamp.

    REAL BUG FIXED HERE (2026-09-17 -- the live bot never detected a single
    report): this used to union `fetch_ticker_earnings` with every row of
    `fetch_recent_earnings_actuals`, whose rows are dated at fiscal
    QUARTER-END. A quarter's actual EPS only appears 2-6 weeks after
    quarter-end, so by the time a current-quarter row existed its date was
    already far outside the watcher's few-day "recently reported" window.
    All 72 universe reports between 2026-07-14 and 2026-09-10 were missed.

    The staleness that motivated `fetch_recent_earnings_actuals` was specific
    to yfinance 0.2.x; yfinance >= 1.0 serves current announcement dates from
    `get_earnings_dates` again (the bot's .venv pins 1.7.0). That endpoint is
    therefore the primary source, and an `earnings_history` quarter is only
    added when no announcement landed within QUARTER_COVERAGE_WINDOW after
    its quarter-end. That keeps one quarter from appearing twice under two
    different dates, which would also corrupt SUE's trailing std. The
    historical batch pipeline (earnings/sue.py's training-data build,
    reports/run_pead_*.py) is unchanged.

    OUTAGE FALLBACK (2026-09-18: `get_earnings_dates` returned nothing for every
    ticker, so every new actual came back dated at quarter-end, outside the
    watcher's window -- the bot would have silently stopped detecting reports).
    While the dated endpoint answers, its future rows are appended to
    SCHEDULE_LOG_FILE. When it returns nothing:
      * the announcement-dated history cached by the training pipeline stands in
        for it, so SUE still has its trailing surprises;
      * each new `earnings_history` quarter is dated by the first announcement
        date the bot saw scheduled for it (Ticker.calendar is still queried and
        logged), stamped at the close (tradable the next session); a quarter with
        no logged date keeps its quarter-end date and so never triggers an entry;
      * the next scheduled date is returned as an upcoming row.
    `date_source` says which of "announced", "scheduled" or "quarter_end" dated
    each row, and `df.attrs["primary_ok"]` whether the dated endpoint answered."""
    today = (now or pd.Timestamp.now()).normalize()
    historical = fetch_ticker_earnings(ticker, limit=limit)
    recent = fetch_recent_earnings_actuals(ticker)
    primary_ok = not historical.empty
    if primary_ok:
        record_scheduled_dates(ticker, historical.loc[historical["eps_actual"].isna(), "earnings_date"],
                               source="get_earnings_dates")
        announced = historical.assign(date_source="announced")
    else:
        announced = load_cached_earnings(ticker).assign(date_source="announced")
        upcoming = fetch_upcoming_earnings_date(ticker)
        if upcoming is not None:
            record_scheduled_dates(ticker, [upcoming], source="calendar")

    parts = [announced] if not announced.empty else []
    if not recent.empty:
        rest = recent[~_covered(recent["earnings_date"], announced["earnings_date"])] if not announced.empty else recent
        rest = rest.assign(date_source="quarter_end")
        if not primary_ok and not rest.empty:
            seen = [d for d in scheduled_dates_seen(ticker) if d <= today]
            for i, quarter_end in rest["earnings_date"].items():
                match = [d for d in seen if quarter_end < d <= quarter_end + QUARTER_COVERAGE_WINDOW]
                if match:
                    rest.loc[i, "earnings_date"] = match[0] + pd.Timedelta(hours=SCHEDULED_REPORT_HOUR)
                    rest.loc[i, "date_source"] = "scheduled"
        parts.append(rest)
    if not primary_ok:
        future = [d for d in scheduled_dates_seen(ticker) if d > today]
        if future:
            parts.append(pd.DataFrame([{"ticker": ticker, "earnings_date": future[0], "eps_estimate": float("nan"),
                                        "eps_actual": float("nan"), "surprise_pct": float("nan"),
                                        "date_source": "scheduled"}]))
    if not parts:
        out = pd.DataFrame()
    else:
        out = pd.concat(parts, ignore_index=True)
        out = out.drop_duplicates(subset=["earnings_date"], keep="first").sort_values("earnings_date").reset_index(drop=True)
    out.attrs["primary_ok"] = primary_ok
    return out


def ingest_universe_earnings(tickers: list[str], out_dir: Path = RAW_DIR) -> dict[str, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for i, ticker in enumerate(tickers):
        df = fetch_ticker_earnings(ticker)
        if df.empty:
            logger.warning(f"[{i+1}/{len(tickers)}] {ticker}: no earnings data")
            continue
        df.to_parquet(out_dir / f"{ticker}.parquet", index=False)
        results[ticker] = df
        n_with_surprise = df["surprise_pct"].notna().sum()
        logger.info(f"[{i+1}/{len(tickers)}] {ticker}: {len(df)} earnings events "
                    f"({df['earnings_date'].min().date()} -> {df['earnings_date'].max().date()}), "
                    f"{n_with_surprise} with a real surprise% value")
        time.sleep(INTER_REQUEST_SLEEP_S)
    logger.info(f"earnings ingestion complete: {len(results)}/{len(tickers)} tickers succeeded")
    return results


def load_universe_earnings(tickers: list[str], data_dir: Path = RAW_DIR) -> dict[str, pd.DataFrame]:
    out = {}
    for ticker in tickers:
        path = data_dir / f"{ticker}.parquet"
        if path.exists():
            out[ticker] = pd.read_parquet(path)
    return out
