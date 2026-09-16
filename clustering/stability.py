"""Cluster stability monitor (Task 11).

Tracks day-to-day changes in cluster count and membership across a
sequence of clustering snapshots, and writes a structured JSONL log --
same shape as quality/monitor.py's pattern (stable "kind" identifiers,
always-on local log, one record per event) so this can become a
circuit-breaker input later without a rewrite. Not wired to any action yet.

Membership stability is measured with the Adjusted Rand Index (ARI)
between consecutive days' cluster labels, restricted to the ticker
intersection of the two snapshots (the universe eligible for a given
correlation window can shift slightly day to day, e.g. a name dropping
below the `min_valid_fraction` coverage threshold). ARI = 1.0 means
identical partitions; ARI near 0 means the partition looks unrelated to
the previous day's; ARI can go negative for worse-than-random agreement.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from loguru import logger
from sklearn.metrics import adjusted_rand_score

from clustering.clustering import ClusterResult

STABILITY_LOG_FILE = Path(__file__).parent.parent / "reports" / "cluster_stability.jsonl"

CLUSTER_COUNT_CHANGED = "cluster_count_changed"
CLUSTER_MEMBERSHIP_SHIFT = "cluster_membership_shift"
COUNT_CHANGE_FLAG_THRESHOLD = 1  # any change in k is logged
ARI_FLAG_THRESHOLD = 0.5  # below this, membership looks materially different from the prior day


def _write_record(kind: str, path: Path, **fields):
    record = {"ts": time.time(), "kind": kind, **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


@dataclass
class StabilityPoint:
    date: pd.Timestamp
    k: int
    n_tickers: int
    ari_vs_prev: float | None  # None for the first snapshot (no prior day to compare)


def compute_stability_series(
    dated_results: list[tuple[pd.Timestamp, ClusterResult]],
    log_path: Path = STABILITY_LOG_FILE,
) -> list[StabilityPoint]:
    points: list[StabilityPoint] = []
    prev_date, prev_result = None, None

    for date, result in dated_results:
        ari = None
        if prev_result is not None:
            common = [t for t in result.tickers if t in set(prev_result.tickers)]
            if len(common) >= 2:
                prev_idx = {t: i for i, t in enumerate(prev_result.tickers)}
                cur_idx = {t: i for i, t in enumerate(result.tickers)}
                prev_labels = [prev_result.labels[prev_idx[t]] for t in common]
                cur_labels = [result.labels[cur_idx[t]] for t in common]
                ari = float(adjusted_rand_score(prev_labels, cur_labels))

            if result.k != prev_result.k:
                _write_record(CLUSTER_COUNT_CHANGED, log_path, date=str(date), prev_k=prev_result.k, k=result.k)
            if ari is not None and ari < ARI_FLAG_THRESHOLD:
                _write_record(CLUSTER_MEMBERSHIP_SHIFT, log_path, date=str(date), ari=ari, n_common_tickers=len(common))

        points.append(StabilityPoint(date=date, k=result.k, n_tickers=len(result.tickers), ari_vs_prev=ari))
        prev_date, prev_result = date, result

    logger.info(f"cluster stability: {len(points)} snapshots, "
                f"{sum(1 for p in points if p.ari_vs_prev is not None and p.ari_vs_prev < ARI_FLAG_THRESHOLD)} "
                f"flagged low-ARI transitions (log: {log_path})")
    return points


def stability_dataframe(points: list[StabilityPoint]) -> pd.DataFrame:
    return pd.DataFrame([{"date": p.date, "k": p.k, "n_tickers": p.n_tickers, "ari_vs_prev": p.ari_vs_prev} for p in points])
