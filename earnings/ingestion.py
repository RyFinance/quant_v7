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

import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

RAW_DIR = Path(__file__).parent.parent / "data" / "earnings_raw"
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


def fetch_ticker_earnings_live(ticker: str, limit: int = FETCH_LIMIT) -> pd.DataFrame:
    """The union of the (reliable-for-history) `fetch_ticker_earnings` and
    the (reliable-for-current) `fetch_recent_earnings_actuals`, deduplicated
    by earnings_date. This is what live components (bot/earnings_watcher.py,
    bot/signal_pipeline.py) should call instead of `fetch_ticker_earnings`
    alone -- the historical batch pipeline (earnings/sue.py's training-data
    build, reports/run_pead_*.py) deliberately keeps using the older-only
    `fetch_ticker_earnings`/`ingest_universe_earnings` path unchanged, since
    that data was already real and complete for the < 2025-05 window the
    validated backtest actually trained and tested on."""
    historical = fetch_ticker_earnings(ticker, limit=limit)
    recent = fetch_recent_earnings_actuals(ticker)
    if historical.empty:
        return recent
    if recent.empty:
        return historical
    combined = pd.concat([historical, recent], ignore_index=True)
    combined = combined.drop_duplicates(subset=["earnings_date"], keep="last").sort_values("earnings_date")
    return combined.reset_index(drop=True)


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
