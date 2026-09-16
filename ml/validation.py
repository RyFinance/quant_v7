"""Part D4 -- time-disjoint validation.

Reuses the exact train/validation/holdout_a/holdout_b/holdout_c chronological
split pattern from polymarket_arb's LightGBM regime diagnostic
(scripts/diagnose_lightgbm_macro_regimes.py::split_time_disjoint): 5 blocks
at fraction boundaries [0.50, 0.625, 0.75, 0.875], i.e. train=50%,
validation=12.5%, then three disjoint 12.5% holdouts spanning later and
later time windows. Majority-class baseline is fit on TRAIN ONLY and
applied unchanged to every partition (never a per-partition majority --
that would be a different, easier baseline for each holdout and defeats
the point of a fixed comparison point). Every partition's class balance is
checked explicitly -- this build's version of the "Holdout B had zero LOW
labels" guard the spec calls out by name.

Two adaptations vs. the original (documented, not silent):

1. PANEL DATA: our feature matrix is a (date x ticker) panel (75 tickers
   per date), not a single time series. Splitting by raw row-fraction
   like the original would risk cutting a date's 75 ticker-rows across two
   partitions. Instead we compute the fraction boundaries over the sorted
   UNIQUE DATES and assign every ticker-row for a given date to that
   date's partition -- no date ever has rows in two partitions.

2. PURGE GAP: each label's target is a forward return over the next
   HOLDING_PERIOD_DAYS trading days (signals/labeling.py). A signal dated
   right before a partition boundary has a forward window that reads
   price data from the *next* partition -- a real, if narrow, form of
   look-ahead leakage across the split. We purge (drop) the last
   `holding_period` trading dates of every partition except the final one,
   which is the standard "purged" chronological CV fix (López de Prado).
   The original polymarket_arb diagnostic didn't need this since its
   validation there wasn't cross-checked for this specific leakage path;
   we add it here since Part D4 explicitly cites avoiding the overfitting
   trap as the entire point of this validation methodology.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger

BOUNDARY_FRACTIONS = (0.50, 0.625, 0.75, 0.875)
PARTITION_NAMES = ("train", "validation", "holdout_a", "holdout_b", "holdout_c")
MIN_ROWS_PER_PARTITION = 200


class InsufficientHistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Partition:
    name: str
    start: str
    end: str
    n_dates: int
    n_rows: int


def split_time_disjoint_panel(
    df: pd.DataFrame,
    date_col: str = "date",
    holding_period: int = 5,
    min_rows_per_partition: int = MIN_ROWS_PER_PARTITION,
) -> tuple[dict[str, pd.DataFrame], list[Partition]]:
    dates = np.array(sorted(df[date_col].unique()))
    n = len(dates)
    if n < 50:
        raise InsufficientHistoryError(f"need a meaningful number of unique dates for 5 disjoint partitions; got {n}")

    boundary_idx = [int(n * f) for f in BOUNDARY_FRACTIONS]
    date_ranges = {
        "train": dates[: boundary_idx[0]],
        "validation": dates[boundary_idx[0]: boundary_idx[1]],
        "holdout_a": dates[boundary_idx[1]: boundary_idx[2]],
        "holdout_b": dates[boundary_idx[2]: boundary_idx[3]],
        "holdout_c": dates[boundary_idx[3]:],
    }

    # purge: drop the last `holding_period` dates of every partition except
    # the last, since their forward-return labels read into the next partition
    purged_ranges = {}
    names = list(date_ranges.keys())
    for i, name in enumerate(names):
        d = date_ranges[name]
        if i < len(names) - 1 and len(d) > holding_period:
            d = d[:-holding_period]
        purged_ranges[name] = d

    parts = {name: df[df[date_col].isin(d)].copy() for name, d in purged_ranges.items()}

    too_small = {name: len(p) for name, p in parts.items() if len(p) < min_rows_per_partition}
    if too_small:
        raise InsufficientHistoryError(f"partitions below {min_rows_per_partition} rows after purge: {too_small}")

    partitions = [
        Partition(
            name=name, start=str(pd.Timestamp(purged_ranges[name].min()).date()),
            end=str(pd.Timestamp(purged_ranges[name].max()).date()),
            n_dates=len(purged_ranges[name]), n_rows=len(parts[name]),
        )
        for name in names
    ]
    for p in partitions:
        logger.info(f"partition {p.name}: {p.start} -> {p.end} ({p.n_dates} dates, {p.n_rows} rows)")
    return parts, partitions


def check_class_completeness(parts: dict[str, pd.DataFrame], label_col: str) -> dict[str, dict]:
    """Per-partition: are both classes (0 and 1) present? Returns a report
    dict; does NOT raise, since the spec wants this reported/flagged, not
    silently worked around -- if a holdout is missing a class, the caller
    decides what to do (widen the window, drop that holdout, etc.) rather
    than this function guessing."""
    report = {}
    for name, part in parts.items():
        counts = part[label_col].value_counts().reindex([0, 1], fill_value=0)
        report[name] = {
            "n_class_0": int(counts.loc[0]), "n_class_1": int(counts.loc[1]),
            "both_classes_present": bool(counts.loc[0] > 0 and counts.loc[1] > 0),
            "positive_rate": float(part[label_col].mean()),
        }
        if not report[name]["both_classes_present"]:
            logger.warning(f"CLASS-COMPLETENESS FAILURE in partition {name!r} for label {label_col!r}: {report[name]}")
    return report


def majority_baseline_predictions(train_labels: pd.Series, n: int) -> np.ndarray:
    majority_class = int(train_labels.mode().iloc[0])
    return np.full(n, majority_class, dtype=int)
