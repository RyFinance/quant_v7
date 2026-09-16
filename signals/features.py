"""Part C3 -- feature extraction for the ML signal-quality filter.

Graph features (from clustering/cluster_assignments.py, computed once
during the cluster-assignment pass so the correlation-matrix build isn't
repeated per phase):
  - vertex_degree     -- ticker's weighted degree in the full correlation graph
  - cluster_density    -- mean |correlation| among the ticker's cluster peers
  - cluster_size        -- number of members in the ticker's cluster that day

Conventional features:
  - deviation, z_score  -- already computed by signals/mean_reversion.py
  - recent_return_{1,5,20}d -- trailing (not forward -- no leakage) residual
    return momentum at three horizons

Cluster-instability feature (new for Phase 3, per the explicit ask to carry
Phase 2's finding forward): `market_ari_vs_prev` -- the *whole-market*
day-to-day cluster-membership Adjusted Rand Index (same definition as
clustering/stability.py, recomputed here directly from the cached
per-ticker assignment table rather than re-running the clustering pass).
This is a date-level value broadcast to every ticker active that date. Its
presence/removal is what Task 21 uses to test whether Phase 2's
low-ARI/high-membership-churn finding actually degrades the filter, or is
just noise the model correctly learns to ignore.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import adjusted_rand_score


def compute_market_stability_series(cluster_assignments: pd.DataFrame) -> pd.DataFrame:
    """Whole-market day-to-day ARI, recomputed from the cached assignment
    table (same method as clustering/stability.py: ARI over the ticker
    intersection between consecutive dates)."""
    dates = sorted(cluster_assignments["date"].unique())
    by_date = {d: g.set_index("ticker")["cluster_id"] for d, g in cluster_assignments.groupby("date")}

    rows = []
    prev_date = None
    for date in dates:
        ari = np.nan
        if prev_date is not None:
            cur, prev = by_date[date], by_date[prev_date]
            common = cur.index.intersection(prev.index)
            if len(common) >= 2:
                ari = adjusted_rand_score(prev.loc[common], cur.loc[common])
        rows.append({"date": date, "market_ari_vs_prev": ari})
        prev_date = date
    return pd.DataFrame(rows)


def compute_recent_returns(residual_returns: pd.DataFrame, windows: tuple[int, ...] = (1, 5, 20)) -> pd.DataFrame:
    frames = []
    for w in windows:
        trailing = residual_returns.rolling(w).sum()
        long = trailing.stack().rename(f"recent_return_{w}d").reset_index()
        long.columns = ["date", "ticker", f"recent_return_{w}d"]
        frames.append(long.set_index(["date", "ticker"]))
    out = pd.concat(frames, axis=1).reset_index()
    return out


def build_feature_matrix(
    labeled_signals: pd.DataFrame,
    residual_returns: pd.DataFrame,
    cluster_assignments: pd.DataFrame,
) -> pd.DataFrame:
    df = labeled_signals.merge(
        cluster_assignments[["date", "ticker", "vertex_degree", "cluster_density"]],
        on=["date", "ticker"], how="left",
    )

    recent_returns = compute_recent_returns(residual_returns)
    df = df.merge(recent_returns, on=["date", "ticker"], how="left")

    stability = compute_market_stability_series(cluster_assignments)
    df = df.merge(stability, on="date", how="left")

    df["abs_deviation"] = df["deviation"].abs()
    df["abs_z_score"] = df["z_score"].abs()

    feature_cols = [
        "z_score", "deviation", "abs_deviation", "abs_z_score",
        "cluster_size", "vertex_degree", "cluster_density",
        "recent_return_1d", "recent_return_5d", "recent_return_20d",
        "market_ari_vs_prev",
    ]
    before = len(df)
    df = df.dropna(subset=feature_cols + ["label_cost_adjusted", "label_fixed_threshold"])
    logger.info(f"built feature matrix: {len(df)} rows ({before - len(df)} dropped for missing features/warmup), "
                f"{len(feature_cols)} feature columns")
    return df


FEATURE_COLUMNS = [
    "z_score", "deviation", "abs_deviation", "abs_z_score",
    "cluster_size", "vertex_degree", "cluster_density",
    "recent_return_1d", "recent_return_5d", "recent_return_20d",
]
FEATURE_COLUMNS_WITH_STABILITY = FEATURE_COLUMNS + ["market_ari_vs_prev"]
