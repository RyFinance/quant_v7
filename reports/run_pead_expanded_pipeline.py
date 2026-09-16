"""Steps 2-3: rebuild the PEAD data pipeline on the EXPANDED universe (full
503 current S&P 500 constituents instead of the original top-75-by-
liquidity subset) -- same 2015-2026 date range (ticker-count expansion,
~6.7x, gives far more new independent quarterly observations than
extending history depth a further few years would on the original 75
names; see reports/PEAD_REVALIDATION_REPORT.md for the reasoning).

No clustering step needed here (PEAD doesn't depend on cluster
assignments) -- just: load all 503 tickers' OHLCV -> residual returns
(market-beta-stripped, same SPY factor as before) -> real earnings/SUE
(already ingested for all 503) -> PEAD signal -> labeling -> features.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

from data.ingestion import load_universe
from clustering.residual_returns import build_residual_returns
from earnings.ingestion import load_universe_earnings
from earnings.sue import build_universe_sue
from earnings.signal import build_pead_signal
from earnings.labeling import build_labeled_pead_signals, HOLDING_PERIOD_DAYS, FIXED_THRESHOLD_RETURN
from earnings.features import build_pead_feature_matrix

DATA_DIR = Path(__file__).parent.parent / "data"
REPORTS_DIR = Path(__file__).parent


def main():
    with open(DATA_DIR / "expanded_universe_all_tickers.txt") as f:
        all_tickers = f.read().strip().split(",")
    logger.info(f"expanded universe: {len(all_tickers)} tickers")

    ohlcv = load_universe(all_tickers)
    logger.info(f"loaded OHLCV for {len(ohlcv)}/{len(all_tickers)} tickers")

    resid = build_residual_returns(ohlcv, lookback=60, start="2015-01-01")
    resid.to_parquet(DATA_DIR / "residual_returns_wide_expanded.parquet")
    logger.info(f"residual returns: {resid.shape[1]} tickers x {resid.shape[0]} dates")

    earnings = load_universe_earnings(all_tickers)
    logger.info(f"loaded earnings for {len(earnings)}/{len(all_tickers)} tickers")
    sue_df = build_universe_sue(earnings)
    sue_df = sue_df[(sue_df["earnings_date"] >= resid.index.min()) & (sue_df["earnings_date"] <= resid.index.max())]
    sue_df.to_parquet(DATA_DIR / "earnings_sue_expanded.parquet", index=False)

    sig = build_pead_signal(sue_df, resid)
    sig.to_parquet(DATA_DIR / "pead_signal_expanded.parquet", index=False)

    labeled = build_labeled_pead_signals(resid, sig, holding_period=HOLDING_PERIOD_DAYS,
                                          fixed_threshold=FIXED_THRESHOLD_RETURN, cost_bps=10.0)

    # liquidity ranking for the expanded universe, computed directly from the
    # already-ingested daily OHLCV (last 63 sessions, same window definition
    # as Phase 1's data/universe.py) -- avoids a redundant yfinance re-fetch.
    rows = []
    for ticker, df in ohlcv.items():
        recent = df.sort_values("timestamp").tail(63)
        if recent.empty:
            continue
        rows.append({"ticker": ticker, "avg_dollar_volume": (recent["close"] * recent["volume"]).mean()})
    ranking_df = pd.DataFrame(rows)
    ranking_df.to_csv(REPORTS_DIR / "expanded_universe_liquidity_ranking.csv", index=False)

    feats = build_pead_feature_matrix(labeled, resid, ranking_df)
    feats.to_parquet(DATA_DIR / "pead_labeled_features_expanded.parquet", index=False)

    logger.info(f"EXPANDED PIPELINE DONE: {len(feats)} labeled events "
                f"({feats['date'].min().date()} -> {feats['date'].max().date()}, "
                f"{feats['ticker'].nunique()} tickers) vs original 75-name sample's 2,723 events")
    return feats


if __name__ == "__main__":
    main()
