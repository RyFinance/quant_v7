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


def compute_metrics(daily_returns: pd.Series, n_trades: int, avg_position_size: float = 0.0) -> BacktestMetrics:
    n = len(daily_returns)
    if n == 0:
        return BacktestMetrics(0, n_trades, 0, 0, 0, 0, 0, 0, 0, 0)

    total_return = float((1 + daily_returns).prod() - 1)
    ann_return = float((1 + daily_returns).prod() ** (TRADING_DAYS_PER_YEAR / n) - 1) if n > 0 else 0.0
    ann_std = float(daily_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if n > 1 else 0.0
    sharpe = float(ann_return / ann_std) if ann_std > 0 else 0.0

    downside = daily_returns[daily_returns < 0]
    downside_std = float(downside.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if len(downside) > 1 else 0.0
    sortino = float(ann_return / downside_std) if downside_std > 0 else 0.0

    nav = (1 + daily_returns).cumprod()
    running_max = nav.cummax()
    drawdown = (nav - running_max) / running_max
    max_dd = float(drawdown.min())

    calmar = float(ann_return / abs(max_dd)) if max_dd < 0 else 0.0
    turnover_annualized = float(n_trades * avg_position_size * (TRADING_DAYS_PER_YEAR / n)) if n > 0 else 0.0

    return BacktestMetrics(
        n_days=n, n_trades=n_trades, annualized_return=round(ann_return, 6), annualized_std=round(ann_std, 6),
        sharpe_ratio=round(sharpe, 4), sortino_ratio=round(sortino, 4), max_drawdown=round(max_dd, 6),
        calmar_ratio=round(calmar, 4), turnover_annualized=round(turnover_annualized, 4), total_return=round(total_return, 6),
    )
