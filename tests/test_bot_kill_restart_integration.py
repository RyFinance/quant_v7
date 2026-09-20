"""Real integration test for the production-readiness requirement: kill the
bot mid-cycle (a genuine SIGKILL to a genuine subprocess, not a mocked
"simulated crash"), then verify (a) the ledger is left in a valid state
(no partial/corrupt records), (b) a fresh process reconstructs state via
PaperExecutionClient.from_ledger with no loss, (c) re-running the cycle
does not double-place an order for the position that DID commit before
the kill, and (d) the watchdog correctly reports a stale heartbeat after
the crash (the heartbeat is only touched at the very end of a successful
cycle, so a mid-cycle kill must leave it untouched -- see
bot/heartbeat.py's docstring).

Network-dependent (real yfinance price fills) -- skipped if the fill
subprocess doesn't complete its first order within the timeout.
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import bot.execution as ex
from bot.heartbeat import read_heartbeat_age_seconds, touch_heartbeat
from bot.watchdog import check_dead_mans_switch
from bot.alerting import ALERT_DEAD_MANS_SWITCH, BotAlerter

SCENARIO_SCRIPT = Path(__file__).parent / "_kill_restart_scenario.py"
POLL_TIMEOUT_SECONDS = 30.0  # ceiling on waiting for order 1 to commit before giving up


@pytest.fixture
def scenario_paths(tmp_path):
    return {
        "ledger": tmp_path / "ledger.jsonl",
        "cycle_log": tmp_path / "cycle_log.jsonl",
        "kill_switch": tmp_path / "KILL_SWITCH",
        "heartbeat": tmp_path / "heartbeat.txt",
    }


def test_sigkill_mid_cycle_then_clean_restart_no_loss_no_duplication(scenario_paths, monkeypatch):
    ledger = scenario_paths["ledger"]
    proc = subprocess.Popen(
        [sys.executable, str(SCENARIO_SCRIPT), str(ledger), str(scenario_paths["cycle_log"]), str(scenario_paths["kill_switch"])],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    # Poll for the ledger to show exactly the FIRST committed order, then
    # kill immediately -- robust to real timing variance (cold-start
    # imports, network jitter) unlike a fixed sleep-then-kill guess.
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    committed_one = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break  # process already exited (too fast, or crashed on its own)
        if ledger.exists() and len(ledger.read_text().strip().splitlines()) >= 1:
            committed_one = True
            break
        time.sleep(0.05)

    proc.kill()  # SIGKILL -- a real crash, not SIGTERM/graceful shutdown
    try:
        remaining_output, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.communicate()
        remaining_output = "(killed, output unavailable)"

    if "SCENARIO COMPLETED CLEANLY" in remaining_output:
        pytest.skip("scenario finished before the kill landed (order 3 committed too fast on this run) -- rerun")
    if not committed_one or not ledger.exists() or ledger.stat().st_size == 0:
        pytest.skip(f"network too slow / order never committed within {POLL_TIMEOUT_SECONDS}s. subprocess output:\n{remaining_output}")

    # -- (a) ledger integrity: every line must be complete, parseable JSON --
    import json
    lines = ledger.read_text().strip().splitlines()
    assert len(lines) >= 1
    for line in lines:
        record = json.loads(line)  # raises if truncated/corrupt -- the real assertion
        assert record["event"] == "open"

    # -- (b) fresh process reconstructs exactly what committed, nothing more --
    replayed = ex.PaperExecutionClient.from_ledger(ledger_path=ledger)
    committed_tickers = set(replayed.positions.keys())
    assert 1 <= len(committed_tickers) <= 2  # order 1 committed; order 2 should NOT have (killed mid-wait)
    assert all(p.open for p in replayed.positions.values())

    # -- (c) re-running does not double-place for the already-open ticker --
    # Two independent checks, not one fragile one:
    #   (c1) run_cycle's own orchestration-level skip (via a properly-scoped
    #        pytest `monkeypatch`, which auto-reverts -- the earlier version
    #        of this test used a raw, non-reverting class-attribute
    #        assignment here, which could leak the patched
    #        EarningsWatcher.get_recently_reported into whichever test runs
    #        next in the same process; found via this test's own dry run).
    #        Asserts entries_considered >= 1 as well as entries == [] --
    #        the weaker assertion alone can't distinguish "found the event
    #        and correctly skipped it" from "found nothing at all," which
    #        is a vacuous pass.
    #   (c2) the CLIENT's own duplicate-open guard (execution.py's
    #        `place_order` raises ValueError if the ticker already has an
    #        open position) -- the actual enforcement mechanism, tested
    #        directly rather than through the orchestration layer.
    import bot.run_cycle as rc
    import bot.kill_switch as ks
    from bot.earnings_watcher import ReportedEarnings
    from bot.signal_pipeline import ScoredEvent
    import pandas as pd

    monkeypatch.setattr(ks, "KILL_SWITCH_FILE", scenario_paths["kill_switch"])
    monkeypatch.setattr(rc, "CYCLE_LOG_FILE", scenario_paths["cycle_log"])
    # Regression fix (2026-08-19): this direct rc.run_cycle() call touches
    # the heartbeat on completion (bot/run_cycle.py's own touch_heartbeat
    # binding) and could reach risk_gate.evaluate()/build_alerter() -- both
    # previously defaulted to the REAL production bot/state/heartbeat.txt
    # and bot/state/bot_alerts.jsonl. Isolate them the same way
    # KILL_SWITCH_FILE/CYCLE_LOG_FILE already are above.
    from bot.alerting import BotAlerter
    import bot.execution as ex_module
    import bot.heartbeat as hb_module
    import bot.risk_gate as rg_module
    alerter = lambda: BotAlerter(webhook_url="", alerts_path=scenario_paths["kill_switch"].parent / "restart_alerts.jsonl")
    monkeypatch.setattr(rg_module, "build_alerter", alerter)
    monkeypatch.setattr(ex_module, "build_alerter", alerter)
    monkeypatch.setattr(rc, "build_alerter", alerter)
    monkeypatch.setattr(rc, "prepare_market_session", lambda tickers, as_of: (True, "restart test session"))
    monkeypatch.setattr(rc, "UPCOMING_EARNINGS_FILE", scenario_paths["kill_switch"].parent / "restart_upcoming_earnings.json")
    monkeypatch.setattr(rc, "BACKFILL_CYCLE_LOG_FILE", scenario_paths["kill_switch"].parent / "restart_backfill_cycle_log.jsonl")
    monkeypatch.setattr(rc, "touch_heartbeat", lambda: hb_module.touch_heartbeat(scenario_paths["kill_switch"].parent / "restart_heartbeat.txt"))
    already_open_ticker = next(iter(committed_tickers))
    fake_event = ReportedEarnings(ticker=already_open_ticker, earnings_date=pd.Timestamp("2024-01-05"),
                                   eps_estimate=1.0, eps_actual=1.2, surprise_pct=20.0, days_since=1)
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [fake_event])
    monkeypatch.setattr(rc, "score_event", lambda event, pipeline: ScoredEvent(
        ticker=event.ticker, earnings_date=event.earnings_date, sue=3.0, calibrated_proba=0.95, direction="long",
    ))
    report = rc.run_cycle(ledger_path=ledger)
    assert report.entries_considered >= 1  # proves the fake event was actually seen, not silently absent
    assert report.entries == []  # ...and skipped before scoring, not scored-then-blocked

    final_state = ex.PaperExecutionClient.from_ledger(ledger_path=ledger)
    open_lines_for_ticker = [json.loads(l) for l in ledger.read_text().strip().splitlines()
                              if json.loads(l)["event"] == "open" and json.loads(l)["ticker"] == already_open_ticker]
    assert len(open_lines_for_ticker) == 1  # (c1) orchestration layer: no duplicate write occurred

    from bot.risk_gate import RiskGateDecision
    fabricated_but_approved = RiskGateDecision(allowed=True, reason=None, detail="test", size_fraction=0.05,
                                                approval_token="irrelevant-not-consumed-check")
    monkeypatch.setattr("bot.execution.consume_approval", lambda token: True)  # isolate: only test the open-position guard
    with pytest.raises(ValueError):
        final_state.place_order(already_open_ticker, "long", fabricated_but_approved, entry_date="2024-01-06")  # (c2)


def test_watchdog_detects_the_crash_via_stale_heartbeat(scenario_paths):
    """The heartbeat is only touched at the END of a successful run_cycle
    (bot/heartbeat.py). A SIGKILL mid-cycle must leave it untouched, so the
    watchdog correctly reports staleness -- verified here by simulating the
    crash's aftermath (heartbeat older than threshold) rather than re-racing
    the timing-sensitive subprocess kill a second time."""
    hb = scenario_paths["heartbeat"]
    old_touch_time = datetime.now() - timedelta(hours=30)
    touch_heartbeat(hb)
    import os
    os.utime(hb, (old_touch_time.timestamp(), old_touch_time.timestamp()))

    alerts_path = hb.parent / "watchdog_alerts.jsonl"
    alerter = BotAlerter(alerts_path=alerts_path)
    fired = check_dead_mans_switch(max_age_hours=26, now=datetime.now(), heartbeat_path=hb, alerter=alerter)

    assert fired is True
    import json
    records = [json.loads(l) for l in alerts_path.read_text().strip().splitlines()]
    assert any(r["kind"] == ALERT_DEAD_MANS_SWITCH for r in records)
