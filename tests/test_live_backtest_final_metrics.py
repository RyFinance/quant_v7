"""Tests for live_backtest/compute_final_metrics.py."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from live_backtest.compute_final_metrics import compute_daily_returns_from_cycle_log, compute_win_rate, main
from live_backtest.monte_carlo import TradeRecord


def test_compute_daily_returns_matches_manual_calc(tmp_path):
    # SYNTHETIC: hand-built cycle log with known nav_before/nav_after
    cycle_log = tmp_path / "cycle_log.jsonl"
    records = [
        {"as_of_date": "2022-01-03", "nav_before": 100000.0, "nav_after": 101000.0},
        {"as_of_date": "2022-01-04", "nav_before": 101000.0, "nav_after": 99990.0},
    ]
    with open(cycle_log, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    returns = compute_daily_returns_from_cycle_log(cycle_log)
    assert len(returns) == 2
    assert returns.iloc[0] == pytest.approx(0.01)
    assert returns.iloc[1] == pytest.approx(-0.01)


def test_compute_win_rate():
    trades = [
        TradeRecord(ticker="A", entry_date="d", exit_date="d", notional=1, size_fraction=0.1, realized_pnl=10, nav_at_entry=10, pnl_contribution_pct=0.01),
        TradeRecord(ticker="B", entry_date="d", exit_date="d", notional=1, size_fraction=0.1, realized_pnl=-5, nav_at_entry=10, pnl_contribution_pct=-0.005),
        TradeRecord(ticker="C", entry_date="d", exit_date="d", notional=1, size_fraction=0.1, realized_pnl=3, nav_at_entry=10, pnl_contribution_pct=0.003),
    ]
    assert compute_win_rate(trades) == pytest.approx(2 / 3)


def test_compute_win_rate_empty():
    assert compute_win_rate([]) is None


def test_main_end_to_end_with_synthetic_ledger(tmp_path):
    """Regression test for a real bug found 2026-08-19: main() used to
    hardcode its output path to the REAL production report
    (reports/pead_live_backtest_metrics.json) with no override, so this
    very test -- passing a tiny synthetic 2-day/1-trade ledger -- silently
    clobbered the real, full 974-day/194-trade replay's report as a side
    effect of just running the test suite. Every subsequent `pytest tests/`
    run (e.g. by the dashboard-build workflow) reproduced the clobber.
    Fixed by adding an `out_path` param; this test must always pass its own
    tmp_path out_path and never touch the real reports/ file."""
    cycle_log = tmp_path / "cycle_log.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    out_path = tmp_path / "metrics.json"
    with open(cycle_log, "w") as f:
        for d, before, after in [("2022-01-03", 100000.0, 100500.0), ("2022-01-04", 100500.0, 100200.0)]:
            f.write(json.dumps({"as_of_date": d, "nav_before": before, "nav_after": after}) + "\n")
    with open(ledger, "w") as f:
        f.write(json.dumps({"event": "open", "entry_date": "2022-01-03", "ticker": "X", "direction": "long",
                             "fill_price": 10, "size_fraction": 0.05, "notional": 5000, "ts": 1, "mode": "paper"}) + "\n")
        f.write(json.dumps({"event": "close", "ticker": "X", "direction": "long", "entry_price": 10,
                             "exit_price": 11, "notional": 5000, "realized_pnl": 500, "reason": "x", "exit_date": "2022-01-04", "ts": 2}) + "\n")

    result = main(cycle_log_path=cycle_log, ledger_path=ledger, out_path=out_path)
    assert result["n_trades"] == 1
    assert result["win_rate"] == 1.0
    assert result["n_days_replayed"] == 2

    assert out_path.exists()
    real_prod_path = Path(__file__).parent.parent / "reports" / "pead_live_backtest_metrics.json"
    with open(real_prod_path) as f:
        prod_result = json.load(f)
    # the real production report must NOT have been touched by this test
    assert prod_result["n_trades"] != 1 or prod_result["start_date"] != "2022-01-03"
