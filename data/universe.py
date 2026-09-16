"""Asset universe definition for quant_v7.

Selection rule (documented, deterministic, reproducible):
  1. Pull current S&P 500 constituents (via `survivorship.fetch_current_constituents`).
  2. Rank by 3-month average dollar volume (price * volume) using recent daily bars.
  3. Take the top N (default 75) — liquid enough for realistic paper-fill
     assumptions and tight correlation estimates, small enough to keep the
     graph-clustering step (Phase 2) fast to iterate on.

This mirrors the spec's recommendation of "a liquid subset of S&P 500
constituents, ~50-100 names" — the graph-clustering research this system is
based on was validated on a similarly sized universe. Liquidity ranking uses
a short lookback window (`LIQUIDITY_LOOKBACK_DAYS`) fetched directly via
yfinance rather than the full multi-year ingestion, so universe selection
doesn't have to wait on the full historical pull.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import yfinance as yf
from loguru import logger

from data.survivorship import fetch_current_constituents

DEFAULT_UNIVERSE_SIZE = 75
LIQUIDITY_LOOKBACK_DAYS = 63  # ~3 trading months


@dataclass
class UniverseSelection:
    tickers: list[str]
    selection_rule: str
    ranked: pd.DataFrame  # full ranking table, for audit


def select_liquid_universe(
    size: int = DEFAULT_UNIVERSE_SIZE,
    lookback_days: int = LIQUIDITY_LOOKBACK_DAYS,
) -> UniverseSelection:
    constituents = fetch_current_constituents()
    tickers = constituents["ticker"].tolist()

    logger.info(f"ranking {len(tickers)} S&P 500 constituents by {lookback_days}-day avg dollar volume")
    raw = yf.download(
        tickers, period=f"{lookback_days}d", interval="1d",
        auto_adjust=True, group_by="ticker", threads=True, progress=False,
    )

    rows = []
    for t in tickers:
        try:
            sub = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        sub = sub.dropna(subset=["Close", "Volume"])
        if sub.empty:
            continue
        dollar_vol = (sub["Close"] * sub["Volume"]).mean()
        rows.append({"ticker": t, "avg_dollar_volume": dollar_vol, "n_bars": len(sub)})

    ranked = pd.DataFrame(rows).sort_values("avg_dollar_volume", ascending=False).reset_index(drop=True)
    selected = ranked.head(size)["ticker"].tolist()

    rule = (
        f"Top {size} S&P 500 constituents (as of current Wikipedia constituent list) "
        f"by {lookback_days}-trading-day average dollar volume (close * volume), "
        f"computed {pd.Timestamp.utcnow().date()}."
    )
    logger.info(f"selected {len(selected)}/{len(tickers)} tickers ({rule})")
    return UniverseSelection(tickers=selected, selection_rule=rule, ranked=ranked)
