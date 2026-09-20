"""Section 4.3 -- metrics required for every backtest. Same function used
everywhere (regime tests, holdouts, walk-forward, cost sensitivity) so
numbers are comparable across every report this build produces.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestMetrics:
    n_days: int
    n_trades: int
    annualized_return: float
    annualized_std: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    turnover_annualized: float
    total_return: float


def compute_metrics(daily_returns: pd.Series, n_trades: int, avg_position_size: float = 0.0,
                    annual_risk_free_rate: float = 0.0, daily_risk_free: pd.Series | None = None) -> BacktestMetrics:
    """Daily simple-return metrics. Sharpe uses arithmetic excess returns;
    Sortino uses downside RMS over ALL days. Zero risk-free is an explicit
    default, not a claim that historical cash yielded zero. Existing saved
    reports must be regenerated to use these corrected definitions.

    `daily_risk_free` is a per-day simple T-bill return aligned to
    `daily_returns`' index (e.g. bot.performance.daily_risk_free); it replaces
    the constant annual rate and must cover every return date.
    """
    daily_returns = pd.Series(daily_returns, dtype=float)
    if not np.isfinite(daily_returns.to_numpy()).all() or (daily_returns < -1).any():
        raise ValueError("daily returns must be finite and >= -1")
    if not np.isfinite(annual_risk_free_rate) or annual_risk_free_rate <= -1:
        raise ValueError("annual risk-free rate must be finite and > -1")
    if daily_risk_free is not None:
        if annual_risk_free_rate != 0.0:
            raise ValueError("pass either annual_risk_free_rate or daily_risk_free, not both")
        rf = pd.Series(daily_risk_free, dtype=float).reindex(daily_returns.index)
        if not np.isfinite(rf.to_numpy()).all():
            raise ValueError("daily risk-free rate must be finite on every return date")
    else:
        rf = (1 + annual_risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    n = len(daily_returns)
    if n == 0:
        return BacktestMetrics(0, n_trades, 0, 0, 0, 0, 0, 0, 0, 0)

    total_return = float((1 + daily_returns).prod() - 1)
    ann_return = float((1 + daily_returns).prod() ** (TRADING_DAYS_PER_YEAR / n) - 1) if n > 0 else 0.0
    ann_std = float(daily_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if n > 1 else 0.0
    excess = daily_returns - rf
    mean_excess_annual = float(excess.mean() * TRADING_DAYS_PER_YEAR)
    sharpe = float(mean_excess_annual / ann_std) if ann_std > 0 else 0.0

    downside_std = float(np.sqrt(np.mean(np.minimum(excess, 0.0) ** 2) * TRADING_DAYS_PER_YEAR))
    sortino = float(mean_excess_annual / downside_std) if downside_std > 0 else 0.0

    nav = (1 + daily_returns).cumprod()
    running_max = nav.cummax().clip(lower=1.0)  # include initial capital before the first loss
    drawdown = (nav - running_max) / running_max
    max_dd = float(drawdown.min())

    calmar = float(ann_return / abs(max_dd)) if max_dd < 0 else 0.0
    turnover_annualized = float(n_trades * avg_position_size * (TRADING_DAYS_PER_YEAR / n)) if n > 0 else 0.0

    return BacktestMetrics(
        n_days=n, n_trades=n_trades, annualized_return=round(ann_return, 6), annualized_std=round(ann_std, 6),
        sharpe_ratio=round(sharpe, 4), sortino_ratio=round(sortino, 4), max_drawdown=round(max_dd, 6),
        calmar_ratio=round(calmar, 4), turnover_annualized=round(turnover_annualized, 4), total_return=round(total_return, 6),
    )
