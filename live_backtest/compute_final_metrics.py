"""Item 4's final deliverable: Sharpe/Sortino/max-drawdown/win-rate for the
REAL live-code-path historical replay, using the exact same
backtest/metrics.py::compute_metrics function every other backtest in this
project reports through (regime tests, holdouts, walk-forward, cost
sensitivity) -- so this number is directly comparable to all of them, not
computed by a bespoke one-off formula.

Daily returns come from the replay's MARK-TO-MARKET NAV -- cash plus every
open position at that day's close (bot/performance.py) -- and Sharpe and
Sortino are taken in excess of the daily 1-month T-bill rate (Ken French daily
RF). Before 2026-09-18 this used the cycle log's cash-basis nav_before /
nav_after (open positions at cost) with a zero risk-free rate, which roughly
doubled the Sharpe (reports/pead_audit/REPORT.md); that figure is still
written, under cash_basis_reference, for comparison only.

The marked NAV is the one run_cycle recorded each session (marked_nav in the
cycle log). A replay run before marking existed has none, so its NAV is
rebuilt from its ledger at the closes its fills were taken from: the data/raw
bar cache that live_backtest/historical_providers.historical_close_price reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from backtest.metrics import compute_metrics
from bot.performance import cached_closes, daily_marked_nav, excess_metrics, read_jsonl, risk_free_last_published
from bot.run_cycle import STARTING_CAPITAL
from data.ingestion import RAW_DATA_DIR
from live_backtest.monte_carlo import extract_trades_from_ledger

REPLAY_STATE_DIR = Path(__file__).parent / "state"
REPORTS_DIR = Path(__file__).parent.parent / "reports"


def compute_daily_returns_from_cycle_log(cycle_log_path: Path) -> pd.Series:
    """CASH-BASIS daily returns (nav_after / nav_before per cycle row). Kept
    for the cash_basis_reference comparison; main() reports marked returns."""
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


def compute_marked_nav(cycle_log_path: Path, ledger_path: Path, price_dir: Path = RAW_DATA_DIR,
                       starting_capital: float = STARTING_CAPITAL) -> tuple[pd.DataFrame, str]:
    """Daily marked NAV for a replay, one row per session day (the last cycle
    of a day wins), with columns marked_nav, cash_basis_nav and stale_marks.
    Returns (frame, source) where source says whether the NAV was recorded by
    run_cycle or rebuilt from the ledger."""
    by_day: dict[str, dict] = {}
    for record in read_jsonl(cycle_log_path):
        if record.get("session_open") is not False:
            by_day[record["as_of_date"]] = record
    days = sorted(by_day)
    if days and all(by_day[d].get("marked_nav") is not None for d in days):
        frame = pd.DataFrame({
            "marked_nav": [float(by_day[d]["marked_nav"]) for d in days],
            "cash_basis_nav": [float(by_day[d]["nav_after"]) for d in days],
            "stale_marks": [len(by_day[d].get("unmarked") or []) for d in days],
        }, index=pd.to_datetime(days))
        return frame, "recorded by run_cycle"
    ledger = read_jsonl(ledger_path)
    tickers = {r["ticker"] for r in ledger if r.get("event") == "open"}
    frame = daily_marked_nav(ledger, cached_closes(tickers, price_dir), pd.to_datetime(days), starting_capital)
    return frame, "rebuilt from the ledger at cached closes"


def _lag1_autocorr(returns: pd.Series) -> float | None:
    with np.errstate(invalid="ignore", divide="ignore"):  # a constant series has no autocorrelation
        value = returns.autocorr(1) if len(returns) > 2 else float("nan")
    return round(float(value), 4) if pd.notna(value) else None


def compute_win_rate(trades) -> float | None:
    if not trades:
        return None
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    return wins / len(trades)


def main(cycle_log_path: Path = None, ledger_path: Path = None, out_path: Path = None) -> dict:
    cycle_log_path = cycle_log_path or (REPLAY_STATE_DIR / "replay_cycle_log.jsonl")
    ledger_path = ledger_path or (REPLAY_STATE_DIR / "replay_ledger.jsonl")

    frame, nav_source = compute_marked_nav(cycle_log_path, ledger_path)
    trades = extract_trades_from_ledger(ledger_path)
    n_trades = len(trades)

    avg_size = sum(t.size_fraction for t in trades) / n_trades if n_trades else 0.0
    metrics, daily_returns, rf = excess_metrics(frame["marked_nav"], STARTING_CAPITAL, n_trades, avg_size)

    cash_returns = compute_daily_returns_from_cycle_log(cycle_log_path)
    cash_metrics = compute_metrics(cash_returns, n_trades, avg_position_size=avg_size)

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
        "stale_marks": int(frame["stale_marks"].sum()),
        "nav": {
            "basis": "marked to market daily (cash + open positions at each day's close)",
            "source": nav_source,
            "final_marked_nav": round(float(frame["marked_nav"].iloc[-1]), 2) if len(frame) else None,
            "final_cash_basis_nav": round(float(frame["cash_basis_nav"].iloc[-1]), 2) if len(frame) else None,
            "lag1_autocorr": _lag1_autocorr(daily_returns),
        },
        "risk_free": {
            "source": "Ken French daily RF (1-month T-bill), reports/higher_sharpe/inputs/french_daily.zip",
            "annualized_mean": round(float(rf.mean() * 252), 6) if len(rf) else None,
            "last_published": str(risk_free_last_published().date()),
        },
        "cash_basis_reference": {
            "note": "cash-basis NAV (open positions at cost), risk-free 0 -- the definition this report used "
                    "before 2026-09-18; overstates Sharpe, kept for comparison only",
            "sharpe_ratio": cash_metrics.sharpe_ratio,
            "annualized_std": cash_metrics.annualized_std,
            "lag1_autocorr": _lag1_autocorr(cash_returns),
        },
        "methodology": "Sharpe and Sortino in excess of the daily 1-month T-bill rate (Ken French daily RF; the "
                        "last published rate carried forward), via backtest/metrics.py::compute_metrics on the "
                        "daily MARK-TO-MARKET NAV (cash plus open positions at each day's close, bot/performance.py; "
                        "idle cash earns nothing, as in the paper account) of the REAL live-code-path "
                        "(bot/run_cycle.py, unmodified) historical replay (live_backtest/run_historical_replay.py), "
                        "out-of-sample window per the cached model's own train/validation split -- see "
                        "live_backtest/run_historical_replay.py's docstring.",
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
