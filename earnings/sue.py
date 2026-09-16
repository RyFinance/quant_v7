"""Standardized Unexpected Earnings (SUE) -- Part C1-equivalent for PEAD.

Analyst-estimate-based SUE (not the older seasonal-random-walk variant --
we have real analyst estimates via yfinance, so there's no reason to use
the weaker proxy): for each earnings event,

    SUE_t = surprise_pct_t / trailing_std(surprise_pct)_t

`trailing_std` is computed CAUSALLY per ticker -- a rolling standard
deviation over the PRIOR `window` earnings events only (never including
the current one), so no future information leaks into the standardization
of a given quarter's surprise. Using surprise_pct (not the raw EPS
difference) makes the measure comparable across tickers with very
different absolute EPS levels (a $0.01 surprise means something very
different for a $0.05-EPS stock than a $5-EPS stock).

window=8 (roughly 2 years of quarterly reports) is a standard SUE
look-back in the literature; falls back to whatever history is available
(min_periods=4, two years -> half a year) rather than dropping recent-IPO
names entirely.

SMALL-DENOMINATOR PROBLEM (real data issue found and fixed during this
build): surprise_pct = (actual - estimate) / |estimate| blows up when the
EPS estimate is near zero -- e.g. XOM's real 2020-05-01 surprise_pct was
+135,997% because analysts' consensus estimate for that COVID-crushed
quarter was a few tenths of a cent. 95 of 2,759 real events (3.4%) had
|surprise_pct| > 100%, several in the thousands or tens of thousands of
percent. These are genuine numbers, not a bug, but they're not
economically meaningful as "how surprised was the market" and would
massively distort both the rolling-std standardization and any downstream
ML feature. Winsorized to +-100% before standardizing -- a standard,
well-known fix for this exact problem in the earnings-surprise literature,
applied uniformly (not tuned to the eventual backtest result).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

SUE_WINDOW = 8
SUE_MIN_PERIODS = 4
SURPRISE_PCT_WINSOR_LIMIT = 100.0


def compute_sue(earnings_df: pd.DataFrame, window: int = SUE_WINDOW, min_periods: int = SUE_MIN_PERIODS,
                 winsor_limit: float = SURPRISE_PCT_WINSOR_LIMIT) -> pd.DataFrame:
    """`earnings_df`: one ticker's real earnings history (ticker, earnings_date,
    eps_estimate, eps_actual, surprise_pct), sorted or not -- sorted internally."""
    df = earnings_df.sort_values("earnings_date").copy()
    df["surprise_pct_winsorized"] = np.clip(df["surprise_pct"], -winsor_limit, winsor_limit)
    # shift(1) before rolling: trailing std uses only STRICTLY PRIOR events
    trailing_std = df["surprise_pct_winsorized"].shift(1).rolling(window, min_periods=min_periods).std()
    # a handful of tickers have `window` trailing surprises that are all
    # identical after winsorization (e.g. repeatedly clipped to exactly the
    # +100% cap) -> std=0 -> division by zero -> inf. Treat as "no usable
    # standardization signal" (NaN, dropped downstream) rather than an
    # infinite SUE, which would otherwise silently become the single most
    # extreme "signal" in the whole dataset.
    trailing_std = trailing_std.replace(0, np.nan)
    df["sue"] = df["surprise_pct_winsorized"] / trailing_std
    return df


def build_universe_sue(universe_earnings: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for ticker, df in universe_earnings.items():
        if df.empty or df["surprise_pct"].notna().sum() < SUE_MIN_PERIODS + 1:
            continue
        frames.append(compute_sue(df))
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["sue"])
    logger.info(f"computed SUE for {out['ticker'].nunique()} tickers, {len(out)} earnings events "
                f"({out['earnings_date'].min().date()} -> {out['earnings_date'].max().date()})")
    return out
