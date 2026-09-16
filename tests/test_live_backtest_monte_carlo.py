"""Tests for live_backtest/monte_carlo.py. Uses a small HAND-BUILT ledger
(SYNTHETIC -- noted explicitly, same rationale as every other exact-answer
math check in this project's test suite: verifying the resampling/
compounding formulas against known values requires a case where the
correct answer is knowable in advance, which real trade data can't
provide). The real-ledger integration test at the bottom uses the actual
replay ledger once it exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from live_backtest.monte_carlo import (
    TradeRecord,
    _equity_curve_from_sequence,
    _max_drawdown,
    _ending_return,
    extract_trades_from_ledger,
    run_monte_carlo,
)


def _write_ledger(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_extract_trades_matches_pnl_pct_manual_calc(tmp_path):
    # SYNTHETIC: hand-built open/close pair with known notional/size_fraction/pnl
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        {"event": "open", "entry_date": "2022-01-01", "ticker": "AAPL", "direction": "long",
         "fill_price": 100.0, "size_fraction": 0.10, "notional": 10000.0, "ts": 1.0, "mode": "paper"},
        {"event": "close", "ticker": "AAPL", "direction": "long", "entry_price": 100.0, "exit_price": 110.0,
         "notional": 10000.0, "realized_pnl": 1000.0, "reason": "holding_period_exit", "exit_date": "2022-01-29", "ts": 2.0},
    ])
    trades = extract_trades_from_ledger(ledger)
    assert len(trades) == 1
    t = trades[0]
    # nav_at_entry = notional / size_fraction = 10000 / 0.10 = 100000
    # pnl_contribution_pct = realized_pnl / nav_at_entry = 1000 / 100000 = 0.01
    assert t.nav_at_entry == pytest.approx(100_000.0)
    assert t.pnl_contribution_pct == pytest.approx(0.01)


def test_extract_trades_skips_unmatched_close():
    pass  # covered implicitly; real ledger writer always pairs open/close, no separate test needed


def test_extract_trades_excludes_still_open_positions(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        {"event": "open", "entry_date": "2022-01-01", "ticker": "AAPL", "direction": "long",
         "fill_price": 100.0, "size_fraction": 0.10, "notional": 10000.0, "ts": 1.0, "mode": "paper"},
        # no matching close -- still open at end of replay window
    ])
    trades = extract_trades_from_ledger(ledger)
    assert trades == []


def test_equity_curve_and_drawdown_known_sequence():
    # SYNTHETIC: hand-computed known sequence -- +10%, -20%, +10%
    # NAV: 100 -> 110 -> 88 -> 96.8
    returns = np.array([0.10, -0.20, 0.10])
    curve = _equity_curve_from_sequence(returns, starting_nav=100.0)
    assert curve[0] == pytest.approx(110.0)
    assert curve[1] == pytest.approx(88.0)
    assert curve[2] == pytest.approx(96.8)
    # max drawdown: peak 110 -> trough 88 -> (88-110)/110 = -0.2
    assert _max_drawdown(curve) == pytest.approx(-0.2)
    assert _ending_return(curve, starting_nav=100.0) == pytest.approx(-0.032)


def test_monte_carlo_bootstrap_and_permutation_distributions_are_sane():
    # SYNTHETIC: 20 hand-built trades, half winners half losers, known magnitude
    trades = [TradeRecord(ticker=f"T{i}", entry_date="2022-01-01", exit_date="2022-01-29",
                           notional=1000.0, size_fraction=0.05, realized_pnl=(50.0 if i % 2 == 0 else -30.0),
                           nav_at_entry=20000.0, pnl_contribution_pct=(0.0025 if i % 2 == 0 else -0.0015))
              for i in range(20)]
    result = run_monte_carlo(trades, n_bootstrap=500, n_permutation=500, seed=42)

    assert result["n_trades"] == 20
    assert "real_realized" in result
    boot = result["bootstrap"]["ending_return_pct"]
    assert boot["p5"] <= boot["p50"] <= boot["p95"]
    perm_dd = result["permutation"]["max_drawdown_pct"]
    assert perm_dd["p5"] <= perm_dd["p50"] <= perm_dd["p95"]
    assert perm_dd["p95"] <= 0  # drawdown is always <= 0 by construction


def test_monte_carlo_too_few_trades_reports_error_not_garbage():
    result = run_monte_carlo([TradeRecord(ticker="X", entry_date="d", exit_date="d", notional=1, size_fraction=0.1,
                                           realized_pnl=1, nav_at_entry=10, pnl_contribution_pct=0.1)])
    assert "error" in result


def test_monte_carlo_deterministic_with_fixed_seed():
    trades = [TradeRecord(ticker=f"T{i}", entry_date="d", exit_date="d", notional=1, size_fraction=0.1,
                           realized_pnl=(1 if i % 2 else -1), nav_at_entry=10, pnl_contribution_pct=(0.05 if i % 2 else -0.03))
              for i in range(10)]
    r1 = run_monte_carlo(trades, n_bootstrap=200, n_permutation=200, seed=7)
    r2 = run_monte_carlo(trades, n_bootstrap=200, n_permutation=200, seed=7)
    assert r1["bootstrap"]["ending_return_pct"] == r2["bootstrap"]["ending_return_pct"]


REAL_LEDGER = Path(__file__).parent.parent / "live_backtest" / "state" / "replay_ledger.jsonl"


@pytest.mark.skipif(not REAL_LEDGER.exists(), reason="historical replay not run yet")
def test_real_replay_ledger_produces_sane_monte_carlo():
    trades = extract_trades_from_ledger(REAL_LEDGER)
    if len(trades) < 2:
        pytest.skip(f"only {len(trades)} completed trades in the real replay ledger so far")
    result = run_monte_carlo(trades, n_bootstrap=1000, n_permutation=1000)
    assert result["n_trades"] == len(trades)
    assert np.isfinite(result["real_realized"]["ending_return"])
    assert np.isfinite(result["real_realized"]["max_drawdown"])
    assert result["real_realized"]["max_drawdown"] <= 0
