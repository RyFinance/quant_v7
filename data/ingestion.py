"""Historical OHLCV ingestion for quant_v7.

Source: yfinance (free, no API key — same choice the quant_v6 roadmap made).
Deviation from quant_v6 roadmap: that roadmap's `MarketTick` schema doesn't
have a `source` field; ours does (see schemas/market_data.py), so every bar
here is stamped `DataSource.YFINANCE` explicitly rather than left implicit.

Multi-year daily history, one ticker at a time with a small delay between
requests (quant_v6 roadmap's documented informal-rate-limit workaround),
written to local parquet files under `quant_v7/data/raw/` so downstream
phases (residual returns, correlation, clustering) don't need network access.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

from schemas.market_data import AssetClass, DataSource, OHLCVBar

RAW_DATA_DIR = Path(__file__).parent / "raw"
DEFAULT_START = "2015-01-01"  # ~10y history: covers 2015-16 oil selloff, 2018 Q4,
                                # 2020 COVID crash, 2022 rate-hike bear market —
                                # multiple distinct regimes, useful for later phases
INTER_REQUEST_SLEEP_S = 0.5


def fetch_ticker_history(ticker: str, start: str = DEFAULT_START, end: str | None = None) -> pd.DataFrame:
    df = yf.download(ticker, start=start, end=end, interval="1d", auto_adjust=True, progress=False)
    if df.empty:
        logger.warning(f"{ticker}: no data returned from yfinance")
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    df.index.name = "timestamp"
    return df.reset_index()


def to_bars(ticker: str, df: pd.DataFrame, asset_class: AssetClass = AssetClass.EQUITY) -> list[OHLCVBar]:
    bars = []
    for _, row in df.iterrows():
        try:
            bars.append(OHLCVBar(
                ticker=ticker, timestamp=row["timestamp"],
                open=row["open"], high=row["high"], low=row["low"], close=row["close"],
                volume=row["volume"], asset_class=asset_class, source=DataSource.YFINANCE,
            ))
        except Exception as e:
            logger.warning(f"{ticker} @ {row.get('timestamp')}: skipped bad bar ({e!r})")
    return bars


def ingest_universe(
    tickers: list[str],
    start: str = DEFAULT_START,
    end: str | None = None,
    out_dir: Path = RAW_DATA_DIR,
) -> dict[str, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        df = fetch_ticker_history(ticker, start=start, end=end)
        if df.empty:
            continue
        bars = to_bars(ticker, df)
        if not bars:
            continue
        clean = pd.DataFrame([b.model_dump() for b in bars])
        clean.to_parquet(out_dir / f"{ticker}.parquet", index=False)
        results[ticker] = clean
        logger.info(f"[{i+1}/{len(tickers)}] {ticker}: {len(clean)} bars "
                    f"({clean['timestamp'].min().date()} -> {clean['timestamp'].max().date()})")
        time.sleep(INTER_REQUEST_SLEEP_S)

    logger.info(f"ingestion complete: {len(results)}/{len(tickers)} tickers succeeded")
    return results


def load_universe(tickers: list[str], data_dir: Path = RAW_DATA_DIR) -> dict[str, pd.DataFrame]:
    out = {}
    for ticker in tickers:
        path = data_dir / f"{ticker}.parquet"
        if path.exists():
            out[ticker] = pd.read_parquet(path)
    return out
