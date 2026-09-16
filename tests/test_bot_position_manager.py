"""Tests for bot/position_manager.py -- fixed HOLDING_PERIOD_DAYS exit,
matching reports/run_pead_backtest.py's approach (no adaptive TP/SL).
"""
from __future__ import annotations

import pytest

import bot.execution as ex
import bot.kill_switch as ks
import bot.position_manager as pm
from earnings.labeling import HOLDING_PERIOD_DAYS


@pytest.fixture
def isolated_kill_switch(tmp_path, monkeypatch):
    sentinel = tmp_path / "KILL_SWITCH"
    monkeypatch.setattr(ks, "KILL_SWITCH_FILE", sentinel)
    # Regression fix (2026-08-19): PaperExecutionClient() defaults to
    # build_alerter(), which previously wrote real alerts (e.g.
    # "position_closed" from test_process_exits_closes_position_via_real_price)
    # to the REAL production bot/state/bot_alerts.jsonl on every test run in
    # this file. Isolate it the same way KILL_SWITCH_FILE already is here.
    from bot.alerting import BotAlerter
    monkeypatch.setattr(ex, "build_alerter", lambda: BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl"))
    return sentinel


def _client_with_open_position(tmp_path, entry_date="2024-01-02"):
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=tmp_path / "ledger.jsonl")
    client.positions["AAPL"] = ex.PaperPosition(
        ticker="AAPL", direction="long", entry_price=100.0, entry_date=entry_date,
        size_fraction=0.05, notional=5_000.0,
    )
    return client


def test_holding_period_matches_pead_labeling_constant():
    manager = pm.PositionManager()
    assert manager.holding_period_days == HOLDING_PERIOD_DAYS == 20


def test_trading_days_elapsed_same_day_is_zero():
    assert pm.trading_days_elapsed("2024-01-02", "2024-01-02") == 0


def test_trading_days_elapsed_counts_business_days():
    # 2024-01-02 (Tue) -> 2024-01-09 (Tue): Wed,Thu,Fri,Mon,Tue = 5 business days
    assert pm.trading_days_elapsed("2024-01-02", "2024-01-09") == 5


def test_due_for_exit_false_before_holding_period(isolated_kill_switch, tmp_path):
    client = _client_with_open_position(tmp_path)
    manager = pm.PositionManager()
    assert manager.due_for_exit(client, "2024-01-10") == []  # only ~6 trading days elapsed


def test_due_for_exit_true_after_holding_period(isolated_kill_switch, tmp_path):
    client = _client_with_open_position(tmp_path)
    manager = pm.PositionManager()
    assert manager.due_for_exit(client, "2024-02-05") == ["AAPL"]  # >20 trading days elapsed


def test_due_for_exit_ignores_already_closed_positions(isolated_kill_switch, tmp_path):
    client = _client_with_open_position(tmp_path)
    client.positions["AAPL"].open = False
    manager = pm.PositionManager()
    assert manager.due_for_exit(client, "2024-02-05") == []


def test_process_exits_closes_position_via_real_price(isolated_kill_switch, tmp_path):
    client = _client_with_open_position(tmp_path)
    manager = pm.PositionManager()
    try:
        results = manager.process_exits(client, "2024-02-05")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    assert len(results) == 1
    assert results[0].ticker == "AAPL"
    assert results[0].days_held >= HOLDING_PERIOD_DAYS
    assert client.positions["AAPL"].open is False


def test_process_exits_no_op_when_nothing_due(isolated_kill_switch, tmp_path):
    client = _client_with_open_position(tmp_path)
    manager = pm.PositionManager()
    results = manager.process_exits(client, "2024-01-05")  # well before 20 trading days
    assert results == []
    assert client.positions["AAPL"].open is True
