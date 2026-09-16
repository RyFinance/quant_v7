"""Part C1-equivalent for PEAD: align each earnings event to the correct
TRADING day the market could actually react on, then hand off to the
existing signals/labeling.py machinery (same forward-cumulative-abnormal-
return + threshold/cost-adjusted labeling used for the mean-reversion
signal in Phases 1-3 -- no need to reinvent that part).

Timing alignment matters for avoiding look-ahead: yfinance's earnings
timestamps are real reported times. An after-market announcement (>= 16:00,
US market close) can't be reacted to until the NEXT trading session; a
before-market announcement reacts THE SAME session. Getting this wrong in
either direction either bakes in a day of hindsight or throws away a day
of real drift.

PEAD's "abnormal return" is measured on the RESIDUAL (market-beta-
stripped) return series already built in clustering/residual_returns.py --
this is not a re-use of convenience, it's the textbook-correct
construction: academic PEAD is defined as cumulative ABNORMAL return,
i.e. exactly a residual return.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

MARKET_CLOSE_HOUR = 16  # ET, NYSE close


def _effective_trading_date(earnings_timestamp: pd.Timestamp, trading_dates: pd.DatetimeIndex) -> pd.Timestamp | None:
    target_date = earnings_timestamp.normalize()
    if earnings_timestamp.hour >= MARKET_CLOSE_HOUR:
        target_date = target_date + pd.Timedelta(days=1)
    candidates = trading_dates[trading_dates >= target_date]
    return candidates.min() if len(candidates) else None


def build_pead_signal(sue_df: pd.DataFrame, residual_returns: pd.DataFrame) -> pd.DataFrame:
    trading_dates = residual_returns.index
    rows = []
    for _, row in sue_df.iterrows():
        eff_date = _effective_trading_date(row["earnings_date"], trading_dates)
        if eff_date is None or row["ticker"] not in residual_returns.columns:
            continue
        rows.append({
            "date": eff_date, "ticker": row["ticker"], "signal": row["sue"],
            "surprise_pct": row["surprise_pct"], "earnings_date_raw": row["earnings_date"],
        })
    out = pd.DataFrame(rows)
    logger.info(f"built PEAD signal: {len(out)} earnings events aligned to real trading days "
                f"({out['date'].min().date() if len(out) else 'n/a'} -> {out['date'].max().date() if len(out) else 'n/a'})")
    return out
