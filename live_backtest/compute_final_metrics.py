"""Item 4's final deliverable: Sharpe/Sortino/max-drawdown/win-rate for the
REAL live-code-path historical replay, using the exact same
backtest/metrics.py::compute_metrics function every other backtest in this
project reports through (regime tests, holdouts, walk-forward, cost
sensitivity) -- so this number is directly comparable to all of them, not
computed by a bespoke one-off formula.

Daily returns are read straight from the replay's own cycle log
(nav_before/nav_after per real simulated trading day, written by the REAL
bot/run_cycle.py code on every call) -- not re-derived from the trade
ledger, since the cycle log already has the exact right granularity
(one row per real trading day the live code path actually processed).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from loguru import logger

from backtest.metrics import compute_metrics
from live_backtest.monte_carlo import extract_trades_from_ledger

REPLAY_STATE_DIR = Path(__file__).parent / "state"
REPORTS_DIR = Path(__file__).parent.parent / "reports"


def compute_daily_returns_from_cycle_log(cycle_log_path: Path) -> pd.Series:
    records = []
    with open(cycle_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    df = pd.DataFrame(records)
    df["daily_return"] = df["nav_after"] / df["nav_before"] - 1.0
    return pd.Series(df["daily_return"].values, index=pd.to_datetime(df["as_of_date"]))


def compute_win_rate(trades) -> float | None:
    if not trades:
        return None
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    return wins / len(trades)


def main(cycle_log_path: Path = None, ledger_path: Path = None, out_path: Path = None) -> dict:
    cycle_log_path = cycle_log_path or (REPLAY_STATE_DIR / "replay_cycle_log.jsonl")
    ledger_path = ledger_path or (REPLAY_STATE_DIR / "replay_ledger.jsonl")

    daily_returns = compute_daily_returns_from_cycle_log(cycle_log_path)
    trades = extract_trades_from_ledger(ledger_path)
    n_trades = len(trades)

    avg_size = sum(t.size_fraction for t in trades) / n_trades if n_trades else 0.0
    metrics = compute_metrics(daily_returns, n_trades, avg_position_size=avg_size)

    win_rate = compute_win_rate(trades)
    result = {
        "start_date": str(daily_returns.index.min().date()) if len(daily_returns) else None,
        "end_date": str(daily_returns.index.max().date()) if len(daily_returns) else None,
        "n_days_replayed": len(daily_returns),
        "n_trades": metrics.n_trades,
        "win_rate": win_rate,
        "annualized_return": metrics.annualized_return,
        "annualized_std": metrics.annualized_std,
        "sharpe_ratio": metrics.sharpe_ratio,
        "sortino_ratio": metrics.sortino_ratio,
        "max_drawdown": metrics.max_drawdown,
        "calmar_ratio": metrics.calmar_ratio,
        "turnover_annualized": metrics.turnover_annualized,
        "total_return": metrics.total_return,
        "methodology": "computed via backtest/metrics.py::compute_metrics on the REAL live-code-path "
                        "(bot/run_cycle.py, unmodified) historical replay's daily NAV changes "
                        "(live_backtest/run_historical_replay.py), out-of-sample window per the cached model's "
                        "own train/validation split -- see live_backtest/run_historical_replay.py's docstring.",
    }

    # `out_path` always defaults to the real production report -- this was
    # NOT previously overridable, which let a 2026-08-19 dashboard-testing
    # run that passed a custom cycle_log_path/ledger_path (a small smoke-test
    # replay) silently clobber the real report anyway. Callers doing anything
    # other than a full production replay MUST pass an explicit out_path.
    out_path = out_path or (REPORTS_DIR / "pead_live_backtest_metrics.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info(f"wrote {out_path}: {result}")
    return result


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, indent=2, default=str))
