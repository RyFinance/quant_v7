"""Residual return calculation (Task 7).

Strips the market factor out of each stock's daily return before any
correlation is computed. Without this, the correlation matrix's dominant
eigenvector is almost always just "the market" (everything moves together
on macro days), which drowns out the sector/pairs structure the clustering
step is actually supposed to find -- this is the standard justification in
the graph-clustering stat-arb literature the spec is based on.

Single-factor market model, rolling window:
    r_i,t = alpha_i,t + beta_i,t * r_mkt,t + epsilon_i,t
beta_i,t and alpha_i,t are recomputed on a trailing rolling window (same
default lookback as the correlation matrix, 60 days, kept configurable
separately here since residual computation and correlation windows are
conceptually independent choices). epsilon_i,t (the residual) is what feeds
the correlation matrix in clustering/correlation.py.

Market proxy: SPY. Not in the 75-name traded universe (avoids a name being
regressed against itself), fetched the same way as any other ticker via
data.ingestion so it goes through the same schema/quality path.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from data.ingestion import fetch_ticker_history, load_universe

MARKET_PROXY = "SPY"
DEFAULT_BETA_LOOKBACK = 60


def _to_close_panel(universe_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """dict[ticker -> OHLCV df] -> wide DataFrame of close prices, date-indexed."""
    closes = {}
    for ticker, df in universe_data.items():
        if df.empty:
            continue
        s = df.set_index(pd.to_datetime(df["timestamp"]))["close"]
        closes[ticker] = s
    panel = pd.DataFrame(closes).sort_index()
    return panel


def compute_simple_returns(close_panel: pd.DataFrame) -> pd.DataFrame:
    return close_panel.pct_change(fill_method=None).dropna(how="all")


def fetch_market_returns(start: str, end: str | None = None) -> pd.Series:
    df = fetch_ticker_history(MARKET_PROXY, start=start, end=end)
    if df.empty:
        raise RuntimeError(f"could not fetch market proxy {MARKET_PROXY!r} -- required for residual returns")
    s = df.set_index(pd.to_datetime(df["timestamp"]))["close"].sort_index()
    return s.pct_change(fill_method=None).dropna().rename(MARKET_PROXY)


def compute_residual_returns(
    returns: pd.DataFrame,
    market_returns: pd.Series,
    lookback: int = DEFAULT_BETA_LOOKBACK,
) -> pd.DataFrame:
    """Rolling single-factor residuals for every column of `returns`.

    Vectorized: rolling beta_t = rolling_cov(r_i, r_mkt) / rolling_var(r_mkt),
    rolling alpha_t = rolling_mean(r_i) - beta_t * rolling_mean(r_mkt).
    First `lookback` rows of each column are NaN (insufficient history) and
    are dropped from the output.
    """
    aligned = returns.join(market_returns, how="inner")
    mkt = aligned[market_returns.name]
    stock_cols = [c for c in aligned.columns if c != market_returns.name]

    rolling_var_mkt = mkt.rolling(lookback).var()
    residuals = {}
    for ticker in stock_cols:
        r = aligned[ticker]
        cov = r.rolling(lookback).cov(mkt)
        beta = cov / rolling_var_mkt
        alpha = r.rolling(lookback).mean() - beta * mkt.rolling(lookback).mean()
        resid = r - (alpha + beta * mkt)
        residuals[ticker] = resid

    out = pd.DataFrame(residuals).dropna(how="all")
    logger.info(f"computed residual returns for {len(stock_cols)} tickers "
                f"({lookback}-day rolling beta vs {market_returns.name}), "
                f"{len(out)} rows after warmup")
    return out


def build_residual_returns(
    universe_data: dict[str, pd.DataFrame],
    lookback: int = DEFAULT_BETA_LOOKBACK,
    start: str = "2015-01-01",
) -> pd.DataFrame:
    close_panel = _to_close_panel(universe_data)
    returns = compute_simple_returns(close_panel)
    market_returns = fetch_market_returns(start=start)
    return compute_residual_returns(returns, market_returns, lookback=lookback)
