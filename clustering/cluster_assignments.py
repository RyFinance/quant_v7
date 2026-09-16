"""Daily cluster-assignment history (new in Phase 3).

Phase 2's `reports/run_pipeline.py` computed cluster labels internally for
the stability report but discarded them once each day's ARI was computed
-- fine for a one-off report, not reusable. Phase 3 (signal generation),
Phase 4 (risk sizing needs to know an asset's cluster), and Phase 6
(backtest simulation) all need per-ticker cluster membership on every date,
so this module persists it once to `data/cluster_assignments.parquet` and
everything downstream reads from disk instead of recomputing.

Uses the same default method Phase 2 settled on as its default: 60-day
rolling residual-return correlation -> explained-variance(90%) cluster
count -> spectral clustering (fast, and Phase 2's SPONGE-sym comparison
showed it disagrees substantially with spectral on the *same* data, not
that one is more "correct" -- spectral stays the production default here
since spec B3 says "implement spectral first...then SPONGE if time allows",
not "replace spectral with SPONGE").
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from clustering.correlation import DEFAULT_LOOKBACK, rolling_correlation_matrices
from clustering.cluster_count import explained_variance_k
from clustering.clustering import spectral_cluster

CACHE_PATH = Path(__file__).parent.parent / "data" / "cluster_assignments.parquet"


def build_cluster_assignment_history(
    residual_returns: pd.DataFrame,
    lookback: int = DEFAULT_LOOKBACK,
    step: int = 1,
    ev_threshold: float = 0.90,
) -> pd.DataFrame:
    """Cluster labels PLUS two graph features (Part C3), computed in the same
    pass over each day's correlation matrix so the ~2800-snapshot correlation
    build only happens once rather than once per phase that needs it:

      - vertex_degree: sum of |correlation| from this ticker to every other
        ticker in that day's snapshot (weighted degree in the full
        correlation graph, not just within its own cluster) -- how
        "connected"/central the name is in the whole network that day.
      - cluster_density: mean |correlation| between all *other* pairs of
        members within this ticker's own cluster that day (excludes the
        ticker's own edges, so it reflects how tight the peer group is
        independent of this one name's connectivity to it).
    """
    snaps = rolling_correlation_matrices(residual_returns, lookback=lookback, step=step)
    rows = []
    for snap in snaps:
        k, _ = explained_variance_k(snap.matrix, threshold=ev_threshold)
        k = max(2, min(k, len(snap.tickers) - 1))
        cr = spectral_cluster(snap.matrix, snap.tickers, k=k)

        abs_corr = np.abs(snap.matrix)
        np.fill_diagonal(abs_corr, 0.0)
        vertex_degree = abs_corr.sum(axis=1)

        labels = np.asarray(cr.labels)
        cluster_density = np.zeros(len(cr.tickers))
        for cluster_id in np.unique(labels):
            idx = np.where(labels == cluster_id)[0]
            if len(idx) < 2:
                continue
            sub = abs_corr[np.ix_(idx, idx)]
            density = sub.sum() / (len(idx) * (len(idx) - 1))  # mean off-diagonal |corr|
            cluster_density[idx] = density

        for i, (ticker, label) in enumerate(zip(cr.tickers, cr.labels)):
            rows.append({
                "date": snap.date, "ticker": ticker, "cluster_id": int(label), "k": k,
                "vertex_degree": float(vertex_degree[i]), "cluster_density": float(cluster_density[i]),
            })
    df = pd.DataFrame(rows)
    logger.info(f"built cluster assignment history: {len(snaps)} dates x up to {len(residual_returns.columns)} tickers "
                f"({len(df)} (date, ticker) rows, incl. vertex_degree/cluster_density graph features)")
    return df


def load_or_build_cluster_assignments(
    residual_returns: pd.DataFrame,
    cache_path: Path = CACHE_PATH,
    lookback: int = DEFAULT_LOOKBACK,
    step: int = 1,
    force_rebuild: bool = False,
) -> pd.DataFrame:
    if cache_path.exists() and not force_rebuild:
        df = pd.read_parquet(cache_path)
        logger.info(f"loaded cached cluster assignments: {len(df)} rows from {cache_path}")
        return df
    df = build_cluster_assignment_history(residual_returns, lookback=lookback, step=step)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path, index=False)
    logger.info(f"cached cluster assignments to {cache_path}")
    return df
