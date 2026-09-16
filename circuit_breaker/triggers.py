"""Parts F1-F4 -- circuit breaker triggers.

Deliberately independent of risk/ and ml/ -- this module only looks at
market data and the data-quality/clustering diagnostics already computed
in Phases 1-2, never at the ML filter's probability, Kelly sizing, or any
signal-engine state. That's the whole point of Part F being a separate
module per the user's original architecture instruction: its rare, blunt
logic must not be reachable by the normal risk-tuning process.

F1 Magnitude: single-asset OR index (universe-average) move >= threshold,
   same trading day.
F2 Speed: move >= threshold within a short intraday window (flash-crash
   signature). NOTE -- see circuit_breaker/calibration.py for why this is
   tested against real RECENT intraday data but not real historical
   flash-crash intraday data (that history isn't available via this
   build's free data sources; documented as an accepted limitation).
F3 Structural: (a) cluster-count collapse, reusing Phase 2's
   clustering/stability.py definition, or (b) mean pairwise |correlation|
   across the universe spiking toward 1.0 (the well-documented
   "everything sells off together" signature).
F4 Infrastructure: reuses Phase 1's quality/monitor.py stale-feed
   detection -- this is *exactly* the "feeds directly into the circuit
   breaker's data-anomaly trigger" hook Part A8 said Phase 1 was building
   toward.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class TriggerCategory(str, Enum):
    MAGNITUDE = "magnitude"
    SPEED = "speed"
    STRUCTURAL = "structural"
    INFRASTRUCTURE = "infrastructure"


@dataclass(frozen=True)
class TriggerEvent:
    category: TriggerCategory
    fired: bool
    detail: str
    value: float
    threshold: float


# ---------------------------------------------------------------------------
# F1 -- magnitude
# ---------------------------------------------------------------------------
def check_magnitude_trigger(
    daily_returns: pd.Series,  # ticker -> that day's simple return
    index_return: float,
    single_asset_threshold: float,
    index_threshold: float,
) -> TriggerEvent:
    worst_single = daily_returns.abs().max() if len(daily_returns) else 0.0
    worst_ticker = daily_returns.abs().idxmax() if len(daily_returns) else None
    single_fired = worst_single >= single_asset_threshold
    index_fired = abs(index_return) >= index_threshold
    fired = bool(single_fired or index_fired)
    detail = (f"single-asset {worst_ticker}={worst_single:.2%} (thr {single_asset_threshold:.2%}), "
              f"index={index_return:.2%} (thr {index_threshold:.2%})")
    return TriggerEvent(TriggerCategory.MAGNITUDE, fired, detail, value=max(worst_single, abs(index_return)),
                         threshold=min(single_asset_threshold, index_threshold))


# ---------------------------------------------------------------------------
# F2 -- speed
# ---------------------------------------------------------------------------
def check_speed_trigger(
    intraday_prices: pd.Series,  # timestamp-indexed prices, minute-granularity
    window_minutes: int,
    move_threshold: float,
) -> TriggerEvent:
    if len(intraday_prices) < 2:
        return TriggerEvent(TriggerCategory.SPEED, False, "insufficient intraday data", 0.0, move_threshold)
    window = pd.Timedelta(minutes=window_minutes)
    rolling_max = intraday_prices.rolling(window).max()
    rolling_min = intraday_prices.rolling(window).min()
    down_move = (rolling_min - rolling_max) / rolling_max  # most negative = biggest drop within window
    worst_drop = down_move.min()
    up_move = (rolling_max - rolling_min) / rolling_min
    worst_rise = up_move.max()
    worst = max(abs(worst_drop), abs(worst_rise))
    fired = bool(worst >= move_threshold)
    return TriggerEvent(TriggerCategory.SPEED, fired,
                         f"max {window_minutes}-min move={worst:.2%} (thr {move_threshold:.2%})",
                         value=float(worst), threshold=move_threshold)


# ---------------------------------------------------------------------------
# F3 -- structural
# ---------------------------------------------------------------------------
def check_cluster_collapse_trigger(
    k_ev_today: int, k_ev_trailing_median: float, collapse_fraction: float,
) -> TriggerEvent:
    if k_ev_trailing_median <= 0:
        return TriggerEvent(TriggerCategory.STRUCTURAL, False, "no trailing median available", 0.0, collapse_fraction)
    drop = 1.0 - (k_ev_today / k_ev_trailing_median)
    fired = bool(drop >= collapse_fraction)
    return TriggerEvent(TriggerCategory.STRUCTURAL, fired,
                         f"k_ev={k_ev_today} vs trailing median={k_ev_trailing_median:.1f} (drop={drop:.1%}, thr {collapse_fraction:.1%})",
                         value=float(drop), threshold=collapse_fraction)


def mean_pairwise_abs_correlation(corr_matrix: np.ndarray) -> float:
    n = corr_matrix.shape[0]
    if n < 2:
        return 0.0
    abs_corr = np.abs(corr_matrix)
    off_diag_sum = abs_corr.sum() - np.trace(abs_corr)
    return float(off_diag_sum / (n * (n - 1)))


def check_correlation_spike_trigger(mean_abs_corr_today: float, spike_threshold: float) -> TriggerEvent:
    fired = bool(mean_abs_corr_today >= spike_threshold)
    return TriggerEvent(TriggerCategory.STRUCTURAL, fired,
                         f"mean |pairwise correlation|={mean_abs_corr_today:.2f} (thr {spike_threshold:.2f})",
                         value=mean_abs_corr_today, threshold=spike_threshold)


# ---------------------------------------------------------------------------
# F4 -- infrastructure
# ---------------------------------------------------------------------------
def check_infrastructure_trigger(n_stale_tickers: int, n_total_tickers: int, stale_fraction_threshold: float) -> TriggerEvent:
    frac = n_stale_tickers / n_total_tickers if n_total_tickers else 0.0
    fired = bool(frac >= stale_fraction_threshold)
    return TriggerEvent(TriggerCategory.INFRASTRUCTURE, fired,
                         f"{n_stale_tickers}/{n_total_tickers} tickers stale ({frac:.1%}, thr {stale_fraction_threshold:.1%})",
                         value=frac, threshold=stale_fraction_threshold)
