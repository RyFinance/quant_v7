"""Part E1 -- Kelly-fraction position sizer.

Binary-outcome Kelly: f* = p - (1-p)/b, where p is the ML filter's
CALIBRATED probability (Part D3 -- using the raw/uncalibrated ensemble
output here would systematically mis-size positions, which is the entire
reason D3 exists) that the trade clears the cost-adjusted profitability
bar, and b is the win/loss payoff ratio: average winning position_return
magnitude divided by average losing position_return magnitude, estimated
from TRAINING data only (never from validation/holdout -- b is a model
parameter like any other and must not see evaluation data).

Negative Kelly is clipped to 0 (spec: no live trading here anyway, but the
sizing logic itself should never imply "bet negative," i.e. bet the
opposite direction at a different size -- if the filter doesn't like a
trade, the position is 0, not inverted).

Default fraction = 0.25 (quarter-Kelly), per spec E1 ("start conservative,
e.g. quarter-Kelly"). Full Kelly is known to be extremely volatile even
when the edge estimate is exactly correct, and our Phase 3 numbers show
the edge estimate is small and noisy (holdout AUC ~0.50-0.52) -- betting
full Kelly against a marginal, uncertain edge is a well-documented way to
blow up. Quarter-Kelly trades some growth-optimality for a much smaller
risk of ruin under edge misestimation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_KELLY_FRACTION = 0.25
# Guards only the genuinely-degenerate case (zero/near-zero losing trades in
# the training sample -- division by ~0). Must be well below real position-
# return magnitudes (our training data's actual avg |loss| is ~2.5%) or it
# silently overrides a legitimate estimate instead of only catching the
# degenerate case -- exactly the bug an earlier version of this file had
# (a 0.05 floor was clamping a real 0.0254 estimate up to 0.05, cutting the
# estimated payoff ratio in half). 1 bp is far below any realistic average
# loss but still prevents a divide-by-zero.
MIN_PAYOFF_RATIO = 0.0001


@dataclass
class PayoffRatio:
    b: float
    avg_win: float
    avg_loss_abs: float
    n_wins: int
    n_losses: int


def estimate_payoff_ratio(train_df: pd.DataFrame, label_col: str, return_col: str = "position_return") -> PayoffRatio:
    wins = train_df.loc[train_df[label_col] == 1, return_col]
    losses = train_df.loc[train_df[label_col] == 0, return_col]
    avg_win = float(wins[wins > 0].mean()) if (wins > 0).any() else 0.0
    avg_loss_abs = float(losses[losses < 0].abs().mean()) if (losses < 0).any() else MIN_PAYOFF_RATIO
    avg_loss_abs = max(avg_loss_abs, MIN_PAYOFF_RATIO)
    b = avg_win / avg_loss_abs
    return PayoffRatio(b=b, avg_win=avg_win, avg_loss_abs=avg_loss_abs, n_wins=int((wins > 0).sum()), n_losses=int((losses < 0).sum()))


def kelly_fraction(p: np.ndarray | float, b: float) -> np.ndarray | float:
    p = np.asarray(p, dtype=float)
    f = p - (1 - p) / b
    return np.clip(f, 0.0, 1.0)


def fractional_kelly_size(
    p: np.ndarray | float,
    b: float,
    kelly_fraction_mult: float = DEFAULT_KELLY_FRACTION,
    max_position_fraction: float = 0.10,
) -> np.ndarray | float:
    """Final position size as a fraction of capital, after applying the
    fractional-Kelly multiplier AND a hard ceiling (Part E2's max-position
    limit is applied here too since a sizer that can recommend an unbounded
    fraction isn't safe to call "conservative" regardless of the multiplier)."""
    raw = kelly_fraction(p, b)
    sized = kelly_fraction_mult * raw
    return np.clip(sized, 0.0, max_position_fraction)
