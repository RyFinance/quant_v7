"""Part C2 -- signal labeling for ML filter training data.

Per spec: "mark historical signals as profitable or not under two
conditions (return above threshold T, or return above transaction cost)."
Implemented as two separate label columns (not OR'd into one), because
they answer different questions and the ML filter's validation should be
checked against both:

  - `label_fixed_threshold`: was the trade *clearly* profitable, by a
    margin comfortably above cost/noise? (backtest-facing target: "is this
    a genuinely good trade")
  - `label_cost_adjusted`: did the trade merely clear the actual
    transaction cost this build charges? (economically minimal bar: "is
    this trade not a loser after costs")

Both labels are evaluated on the FORWARD RESIDUAL return (market-beta
already stripped in Part B1), not the raw price return, in the direction
implied by the signal (`sign(signal) * forward_cumulative_residual_return`).
This is deliberate: the whole point of building a market-neutral,
cluster-relative signal was so its P&L reflects whether the deviation
reverted, not whether the market went up that week. A raw-price-return
label would silently reward "got lucky with market beta" trades that have
nothing to do with the clustering signal actually working.

Threshold calibration (empirical, computed against this build's real
2015-2026 universe before picking a number -- not an arbitrary round
figure):
  - 5-day forward position-return distribution: mean +2.3 bps, std ~4.5%
    (idiosyncratic noise dominates the mean edge by ~2 orders of
    magnitude -- expected for a mean-reversion signal, and consistent
    with the spec's own warning that the reference paper's base strategy
    only cleared ~1.1% annualized net of costs).
  - T = 50 bps gives a 42.8% positive rate (well-balanced for
    classification, comfortably above the ~10 bps round-trip cost so it
    is not just "beats costs by a hair").
  - Cost-adjusted (10 bps round trip, see risk/transaction_costs.py) gives
    a 48.6% positive rate.

HOLDING_PERIOD_DAYS = 5 (one trading week): short enough that the
mean-reversion effect (which decays quickly -- these are idiosyncratic
deviations, not slow-moving factors) hasn't fully dissipated, long enough
to net out single-day noise. Configurable; not re-optimized against the
label distribution (that would be leaking the target into the feature
design).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from risk.transaction_costs import cost_as_return

HOLDING_PERIOD_DAYS = 5
FIXED_THRESHOLD_RETURN = 0.005  # 50 bps, see calibration note above


def compute_forward_position_return(
    residual_returns: pd.DataFrame,
    signal_df: pd.DataFrame,
    holding_period: int = HOLDING_PERIOD_DAYS,
) -> pd.DataFrame:
    """Attach the realized forward position return to each signal row.

    forward_return(t, ticker) = sum of residual returns over (t, t+H] --
    simple (additive) cumulation, not log-compounded; an acceptable
    approximation at H=5 trading days and daily-return magnitudes this
    small (a documented simplification, not treated as exact).
    position_return = sign(signal) * forward_return -- P&L if we took the
    signal's implied long/short direction and held for H days.
    """
    fwd_cum = residual_returns.rolling(holding_period).sum().shift(-holding_period)
    fwd_long = fwd_cum.stack().rename("forward_return").reset_index()
    fwd_long.columns = ["date", "ticker", "forward_return"]

    merged = signal_df.merge(fwd_long, on=["date", "ticker"], how="inner")
    merged = merged.dropna(subset=["forward_return"])
    merged["position_return"] = np.sign(merged["signal"]) * merged["forward_return"]
    return merged


def add_labels(
    df: pd.DataFrame,
    fixed_threshold: float = FIXED_THRESHOLD_RETURN,
    cost_bps: float = 10.0,
) -> pd.DataFrame:
    df = df.copy()
    df["label_fixed_threshold"] = (df["position_return"] > fixed_threshold).astype(int)
    df["label_cost_adjusted"] = (df["position_return"] > cost_as_return(cost_bps)).astype(int)
    return df


def build_labeled_signals(
    residual_returns: pd.DataFrame,
    signal_df: pd.DataFrame,
    holding_period: int = HOLDING_PERIOD_DAYS,
    fixed_threshold: float = FIXED_THRESHOLD_RETURN,
    cost_bps: float = 10.0,
) -> pd.DataFrame:
    with_returns = compute_forward_position_return(residual_returns, signal_df, holding_period=holding_period)
    labeled = add_labels(with_returns, fixed_threshold=fixed_threshold, cost_bps=cost_bps)

    n = len(labeled)
    pos_fixed = labeled["label_fixed_threshold"].mean()
    pos_cost = labeled["label_cost_adjusted"].mean()
    logger.info(f"labeled {n} signal observations: "
                f"fixed-threshold({fixed_threshold:.1%}) positive rate={pos_fixed:.1%}, "
                f"cost-adjusted({cost_bps}bps) positive rate={pos_cost:.1%}")
    return labeled
