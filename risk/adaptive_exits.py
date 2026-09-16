"""Part E3 -- adaptive TP/SL functions. Time-varying, scaled by signal
strength -- deliberately not fixed percentages, per spec.

Take-profit is scaled by how large the entry deviation was: the
mean-reversion thesis is "this deviation should partially revert," so a
bigger entry deviation implies a bigger reasonable target. TP is set at
`reversion_fraction` (default 50%) of the entry deviation magnitude --
not 100%, since assuming the full deviation reverts is the overreach that
turns a real edge into an overfit backtest number.

Stop-loss is scaled by the cluster's own recent volatility
(`cluster_std_return`, already computed per (date, cluster) in
signals/mean_reversion.py) rather than a flat percentage, so a stop in a
volatile semiconductor cluster isn't the same absolute width as a stop in
a sleepy utilities cluster.

Both thresholds TIGHTEN as the holding period elapses (time-varying): the
mean-reversion thesis has a shelf life -- Part C2's 5-day holding period
was chosen because the effect decays quickly -- so a position that hasn't
worked by day 3 of 5 shouldn't need to travel as far to trigger an exit as
it did on day 0. Linear tightening from 100% of the initial threshold at
entry down to `min_tighten` (default 50%) by the final holding day.
"""
from __future__ import annotations

from dataclasses import dataclass

REVERSION_FRACTION = 0.50
STOP_LOSS_VOL_MULTIPLE = 2.0
MIN_TIGHTEN = 0.50


@dataclass(frozen=True)
class ExitThresholds:
    take_profit_return: float
    stop_loss_return: float
    day_in_holding: int
    tighten_factor: float


def _tighten_factor(day_in_holding: int, holding_period: int, min_tighten: float = MIN_TIGHTEN) -> float:
    progress = min(max(day_in_holding, 0), holding_period) / holding_period
    return 1.0 - (1.0 - min_tighten) * progress


def adaptive_exit_thresholds(
    entry_deviation: float,
    cluster_std_return: float,
    day_in_holding: int,
    holding_period: int,
    reversion_fraction: float = REVERSION_FRACTION,
    stop_loss_vol_multiple: float = STOP_LOSS_VOL_MULTIPLE,
    min_tighten: float = MIN_TIGHTEN,
) -> ExitThresholds:
    tighten = _tighten_factor(day_in_holding, holding_period, min_tighten)
    base_tp = reversion_fraction * abs(entry_deviation)
    base_sl = stop_loss_vol_multiple * abs(cluster_std_return)
    return ExitThresholds(
        take_profit_return=base_tp * tighten,
        stop_loss_return=base_sl * tighten,
        day_in_holding=day_in_holding,
        tighten_factor=tighten,
    )


def check_exit(cumulative_return_since_entry: float, thresholds: ExitThresholds) -> str | None:
    """Signed cumulative return in the POSITION's direction (i.e. already
    sign-adjusted for long/short, same convention as `position_return` in
    signals/labeling.py). Returns 'take_profit', 'stop_loss', or None."""
    if cumulative_return_since_entry >= thresholds.take_profit_return:
        return "take_profit"
    if cumulative_return_since_entry <= -thresholds.stop_loss_return:
        return "stop_loss"
    return None
