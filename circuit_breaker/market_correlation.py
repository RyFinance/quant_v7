"""Structural trigger's own correlation pipeline -- deliberately NOT
clustering/correlation.py.

Empirical finding from calibration (see reports/circuit_breaker_calibration.py):
mean pairwise |correlation| computed on RESIDUAL returns (market beta
already stripped, Part B1) barely moved during the real 2020 COVID crash
(0.152 -> 0.184 mean, 2019-calm-year max 0.174 vs COVID peak 0.209 -- only
~20% relative increase) because Part B1's whole purpose is to remove the
market-wide co-movement that a crash produces. The SAME metric computed on
RAW (non-residualized) returns spiked from a 2019 calm-year max of 0.542 to
a COVID peak of 0.777 -- a dramatic, clean signal.

This is a concrete, empirical instance of why the spec's original
instruction to keep the circuit breaker independent of the signal engine
matters beyond just code organization: the signal engine's residual
returns are ENGINEERED to remove the exact systemic co-movement signal the
circuit breaker needs to detect. Reusing clustering/correlation.py here
would silently cripple F3. So this module recomputes correlation from raw
prices independently.
"""
from __future__ import annotations

import pandas as pd


def rolling_raw_correlation_mean_abs(
    close_panel: pd.DataFrame, lookback: int = 60, min_valid_fraction: float = 0.8,
) -> pd.Series:
    from circuit_breaker.triggers import mean_pairwise_abs_correlation

    raw_returns = close_panel.pct_change(fill_method=None)
    dates = raw_returns.index
    rows = {}
    for i in range(lookback, len(dates)):
        window = raw_returns.iloc[i - lookback:i]
        valid = window.columns[window.notna().sum() >= min_valid_fraction * lookback]
        if len(valid) < 2:
            continue
        corr = window[valid].corr().to_numpy()
        rows[dates[i]] = mean_pairwise_abs_correlation(corr)
    return pd.Series(rows, name="mean_abs_corr_raw")
