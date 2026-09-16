"""Part C1 -- cluster mean-reversion raw signal.

For each (date, ticker) with a cluster assignment, compute how far that
ticker's residual return deviated from its own cluster's cross-sectional
mean residual return that day. Positive deviation = ticker outperformed
its cluster peers (mean-reversion says: expect it to underperform next,
so this is a bearish/short signal); negative deviation = underperformed
peers (bullish/long signal). `signal` is defined as -z_score so a higher
`signal` value always means "more bullish."

z-scoring (dividing by the cluster's same-day cross-sectional std of
residual returns) rather than using raw deviation directly, because
clusters vary widely in typical dispersion (a cluster of volatile
semiconductor names moves a lot more day to day than a cluster of
utilities) -- raw deviation would make the signal incomparable across
clusters, which matters once we're ranking/sizing across the whole
universe rather than trading one cluster in isolation.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

MIN_CLUSTER_SIZE_FOR_SIGNAL = 3  # a "cluster" of 1-2 has no meaningful mean-reversion peer group


def compute_deviation_signal(
    residual_returns: pd.DataFrame,
    cluster_assignments: pd.DataFrame,
) -> pd.DataFrame:
    """Returns long-form DataFrame: date, ticker, cluster_id, cluster_size,
    residual_return, cluster_mean_return, deviation, z_score, signal.
    """
    long_returns = residual_returns.stack().rename("residual_return").reset_index()
    long_returns.columns = ["date", "ticker", "residual_return"]

    merged = cluster_assignments.merge(long_returns, on=["date", "ticker"], how="inner")

    grp = merged.groupby(["date", "cluster_id"])["residual_return"]
    merged["cluster_size"] = grp.transform("count")
    merged["cluster_mean_return"] = grp.transform("mean")
    merged["cluster_std_return"] = grp.transform("std")

    merged = merged[merged["cluster_size"] >= MIN_CLUSTER_SIZE_FOR_SIGNAL].copy()
    merged["deviation"] = merged["residual_return"] - merged["cluster_mean_return"]
    safe_std = merged["cluster_std_return"].replace(0, pd.NA)
    merged["z_score"] = merged["deviation"] / safe_std
    merged = merged.dropna(subset=["z_score"])
    merged["signal"] = -merged["z_score"]

    out = merged[["date", "ticker", "cluster_id", "cluster_size", "residual_return",
                  "cluster_mean_return", "cluster_std_return", "deviation", "z_score", "signal"]].reset_index(drop=True)
    logger.info(f"computed mean-reversion signal for {len(out)} (date, ticker) observations "
                f"across {out['date'].nunique()} dates (dropped clusters < {MIN_CLUSTER_SIZE_FOR_SIGNAL} members)")
    return out
