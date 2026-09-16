"""Rolling correlation matrix builder (Task 8).

Operates on residual returns (clustering/residual_returns.py), not raw
returns -- the whole point of stripping market beta first is so this
correlation matrix reflects idiosyncratic co-movement (sector/pairs
structure) rather than "everything is correlated with the market."

Produces a correlation matrix as of each rebalance date using a trailing
lookback window (default 60 trading days, configurable). Rebalance
frequency defaults to daily (one matrix per available date once enough
history has accumulated) but can be thinned via `step` for faster
iteration over long histories.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger

DEFAULT_LOOKBACK = 60


@dataclass
class CorrelationSnapshot:
    date: pd.Timestamp
    tickers: list[str]
    matrix: np.ndarray  # symmetric, tickers x tickers, values in [-1, 1]


def rolling_correlation_matrices(
    residual_returns: pd.DataFrame,
    lookback: int = DEFAULT_LOOKBACK,
    step: int = 1,
    min_valid_fraction: float = 0.8,
) -> list[CorrelationSnapshot]:
    """One correlation snapshot per eligible date, using the trailing `lookback` window.

    A ticker is dropped from a given snapshot if it has fewer than
    `min_valid_fraction * lookback` non-NaN residuals in that window (avoids
    a late-IPO name like APP/HOOD corrupting the matrix with a near-empty
    window early in the sample).
    """
    dates = residual_returns.index
    snapshots = []
    for i in range(lookback, len(dates), step):
        window = residual_returns.iloc[i - lookback:i]
        valid_cols = window.columns[window.notna().sum() >= min_valid_fraction * lookback]
        if len(valid_cols) < 2:
            continue
        corr = window[valid_cols].corr(method="pearson")
        snapshots.append(CorrelationSnapshot(
            date=dates[i], tickers=list(valid_cols), matrix=corr.to_numpy(),
        ))

    logger.info(f"built {len(snapshots)} rolling correlation snapshots "
                f"(lookback={lookback}, step={step}) from {len(dates)} available dates")
    return snapshots


def latest_correlation_matrix(residual_returns: pd.DataFrame, lookback: int = DEFAULT_LOOKBACK,
                               min_valid_fraction: float = 0.8) -> CorrelationSnapshot:
    if len(residual_returns) < lookback:
        raise RuntimeError(f"not enough history ({len(residual_returns)} rows) for a {lookback}-day correlation window")
    window = residual_returns.iloc[-lookback:]
    valid_cols = window.columns[window.notna().sum() >= min_valid_fraction * lookback]
    corr = window[valid_cols].corr(method="pearson")
    return CorrelationSnapshot(date=residual_returns.index[-1], tickers=list(valid_cols), matrix=corr.to_numpy())
