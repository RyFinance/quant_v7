"""Tests for bot/run_cycle.py -- the orchestration entry point. The
"no candidate earnings" path runs against real data (real yfinance query,
just asserts the cycle completes cleanly with 0+ entries -- however many
real events actually reported recently). The kill-switch and entry-flow
tests inject a controlled ReportedEarnings event via monkeypatch (there is
no way to deterministically guarantee a specific real earnings event
exists on test-run day, so this is the one place a constructed event
object is used -- same rationale test_bot_risk_gate.py already applies by
passing breaker_tier="armed" directly rather than waiting for a real
market state).
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import bot.execution as ex
import bot.heartbeat as hb
import bot.kill_switch as ks
import bot.risk_gate as rg
import bot.run_cycle as rc
from bot.earnings_watcher import ReportedEarnings
from bot.signal_pipeline import ScoredEvent


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    cycle_log = tmp_path / "cycle_log.jsonl"
    sentinel = tmp_path / "KILL_SWITCH"
    monkeypatch.setattr(ks, "KILL_SWITCH_FILE", sentinel)
    monkeypatch.setattr(rc, "CYCLE_LOG_FILE", cycle_log)
    # Regression fix (2026-08-19): the real run_cycle() code path calls
    # into both risk_gate.evaluate() and PaperExecutionClient, each of
    # which defaults to build_alerter() -- previously writing real alerts
    # to the REAL production bot/state/bot_alerts.jsonl on every test run
    # in this file. Isolate both bindings the same way KILL_SWITCH_FILE
    # and CYCLE_LOG_FILE already are here.
    from bot.alerting import BotAlerter
    alerter = lambda: BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl")
    monkeypatch.setattr(rg, "build_alerter", alerter)
    monkeypatch.setattr(ex, "build_alerter", alerter)
    # Same class of bug for the heartbeat: run_cycle.py imports
    # touch_heartbeat directly (its own binding, separate from
    # bot.heartbeat's), and it defaults to the REAL production
    # bot/state/heartbeat.txt -- every successful run_cycle() call in this
    # file was refreshing the real bot's dead-man's-switch heartbeat,
    # which could mask a genuine staleness if the real process had died.
    heartbeat = tmp_path / "heartbeat.txt"
    monkeypatch.setattr(rc, "touch_heartbeat", lambda: hb.touch_heartbeat(heartbeat))
    return {"ledger": ledger, "cycle_log": cycle_log, "kill_switch": sentinel, "heartbeat": heartbeat}


def test_run_cycle_against_real_data_completes(isolated_state):
    """No mocking of the earnings/market data path -- real query, whatever
    it returns. Only asserts the cycle runs to completion and logs itself."""
    try:
        report = rc.run_cycle(ledger_path=isolated_state["ledger"])
    except Exception as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    assert report.as_of_date
    assert report.breaker_tier in ("armed", "halt_new_entries", "full_flatten")
    assert isolated_state["cycle_log"].exists()
    lines = isolated_state["cycle_log"].read_text().strip().splitlines()
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["as_of_date"] == report.as_of_date


def test_run_cycle_blocks_all_entries_when_kill_switch_engaged(isolated_state, monkeypatch):
    ks.engage_kill_switch("test")

    fake_event = ReportedEarnings(
        ticker="AAPL", earnings_date=pd.Timestamp("2024-01-02"),
        eps_estimate=1.0, eps_actual=1.1, surprise_pct=10.0, days_since=1,
    )
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [fake_event])
    monkeypatch.setattr(rc, "score_event", lambda event, pipeline: ScoredEvent(
        ticker="AAPL", earnings_date=event.earnings_date, sue=2.0, calibrated_proba=0.9, direction="long",
    ))

    report = rc.run_cycle(ledger_path=isolated_state["ledger"])
    assert report.kill_switch_engaged is True
    assert len(report.entries) == 1
    assert report.entries[0].allowed is False
    assert report.entries[0].reason == "risk_blocked"
    assert "AAPL" not in ex.PaperExecutionClient.from_ledger(ledger_path=isolated_state["ledger"]).positions


def test_run_cycle_places_order_for_high_conviction_event_when_armed(isolated_state, monkeypatch):
    fake_event = ReportedEarnings(
        ticker="AAPL", earnings_date=pd.Timestamp("2024-01-02"),
        eps_estimate=1.0, eps_actual=1.1, surprise_pct=10.0, days_since=1,
    )
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [fake_event])
    monkeypatch.setattr(rc, "score_event", lambda event, pipeline: ScoredEvent(
        ticker="AAPL", earnings_date=event.earnings_date, sue=2.0, calibrated_proba=0.9, direction="long",
    ))
    monkeypatch.setattr(rc, "current_breaker_tier", lambda: ("armed", {}))

    try:
        report = rc.run_cycle(ledger_path=isolated_state["ledger"])
    except Exception as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    assert len(report.entries) == 1
    assert report.entries[0].allowed is True
    replayed = ex.PaperExecutionClient.from_ledger(ledger_path=isolated_state["ledger"])
    assert "AAPL" in replayed.positions
    assert replayed.positions["AAPL"].open is True


def test_run_cycle_skips_ticker_with_already_open_position(isolated_state, monkeypatch):
    # pre-seed an open AAPL position directly on the ledger
    decision = rg.evaluate(
        ticker="AAPL", calibrated_proba=0.7, payoff_ratio_b=1.2,
        current_total_exposure_pct=0.0, current_daily_pnl_pct=0.0,
        paper_nav=100_000.0, paper_high_water_mark=100_000.0, breaker_tier="armed",
    )
    client = ex.PaperExecutionClient(ledger_path=isolated_state["ledger"])
    try:
        client.place_order("AAPL", "long", decision, entry_date="2024-01-02")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    fake_event = ReportedEarnings(
        ticker="AAPL", earnings_date=pd.Timestamp("2024-01-05"),
        eps_estimate=1.0, eps_actual=1.2, surprise_pct=20.0, days_since=1,
    )
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [fake_event])

    report = rc.run_cycle(ledger_path=isolated_state["ledger"])
    assert report.entries == []  # already-open AAPL is skipped before scoring, not re-evaluated
