"""Tests for live_backtest/compute_final_metrics.py."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.metrics import compute_metrics
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


def _write(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


_LEDGER = [
    {"event": "open", "entry_date": "2025-03-03", "ticker": "X", "direction": "long",
     "fill_price": 10.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 1, "mode": "paper"},
    {"event": "close", "ticker": "X", "direction": "long", "entry_price": 10.0, "exit_price": 10.5,
     "notional": 5000.0, "realized_pnl": 245.0, "reason": "x", "exit_date": "2025-03-07", "ts": 2},
]
_DAYS = ["2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07"]


def test_main_measures_the_recorded_marked_nav_in_excess_of_tbills(tmp_path):
    """A position held for days: cash-basis NAV is flat until the exit, the
    recorded marked NAV is not. Sharpe must come from the marked series, over
    the daily T-bill rate -- not from nav_after with a zero rate."""
    from bot.performance import daily_returns, daily_risk_free
    marked = [100_000.0, 100_300.0, 99_900.0, 100_400.0, 100_245.0]
    cash = [100_000.0] * 4 + [100_245.0]
    _write(tmp_path / "cycle_log.jsonl", [
        {"as_of_date": d, "nav_before": (cash[i - 1] if i else 100_000.0), "nav_after": cash[i],
         "marked_nav": marked[i], "unmarked": [], "session_open": True} for i, d in enumerate(_DAYS)
    ])
    _write(tmp_path / "ledger.jsonl", _LEDGER)

    result = main(cycle_log_path=tmp_path / "cycle_log.jsonl", ledger_path=tmp_path / "ledger.jsonl",
                  out_path=tmp_path / "metrics.json")
    returns = daily_returns(pd.Series(marked, index=pd.to_datetime(_DAYS)), 100_000.0)
    rf = daily_risk_free(returns.index)
    expected = (returns - rf).mean() * 252 / (returns.std(ddof=1) * 252 ** 0.5)
    assert result["sharpe_ratio"] == pytest.approx(expected, abs=1e-3)
    assert result["annualized_std"] == pytest.approx(returns.std(ddof=1) * 252 ** 0.5, abs=1e-5)
    assert result["nav"]["source"] == "recorded by run_cycle"
    assert result["nav"]["final_marked_nav"] == result["nav"]["final_cash_basis_nav"] == 100_245.0
    assert result["risk_free"]["annualized_mean"] > 0.03  # March 2025 T-bills: over 4% a year
    assert result["sharpe_ratio"] < compute_metrics(returns, 1).sharpe_ratio  # the rate is charged
    # The old definition is kept only as a labelled reference.
    assert result["cash_basis_reference"]["annualized_std"] < result["annualized_std"]
    assert json.loads((tmp_path / "metrics.json").read_text())["sharpe_ratio"] == result["sharpe_ratio"]


def test_a_replay_without_recorded_marks_is_rebuilt_from_its_ledger(tmp_path):
    from live_backtest.compute_final_metrics import compute_marked_nav
    _write(tmp_path / "cycle_log.jsonl", [{"as_of_date": d, "nav_before": 1.0, "nav_after": 1.0} for d in _DAYS])
    _write(tmp_path / "ledger.jsonl", _LEDGER)
    pd.DataFrame({"timestamp": pd.to_datetime(_DAYS), "close": [10.0, 10.6, 9.8, 10.8, 10.5]}) \
        .to_parquet(tmp_path / "X.parquet", index=False)

    frame, source = compute_marked_nav(tmp_path / "cycle_log.jsonl", tmp_path / "ledger.jsonl", price_dir=tmp_path)
    assert source == "rebuilt from the ledger at cached closes"
    assert list(frame["marked_nav"]) == pytest.approx([100_000.0, 100_300.0, 99_900.0, 100_400.0, 100_245.0])
    assert list(frame["cash_basis_nav"]) == pytest.approx([100_000.0] * 4 + [100_245.0])
    assert frame["stale_marks"].sum() == 0
