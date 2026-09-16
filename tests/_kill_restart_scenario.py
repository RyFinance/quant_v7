"""Not a pytest module (underscore-prefixed, not collected). Standalone
subprocess target for tests/test_bot_kill_restart_integration.py: forces
THREE fake reported-earnings events through a real run_cycle(), with a
deliberate pause injected between each order placement so an external
process has a reliable window to SIGKILL this one mid-cycle -- simulating
a real crash between the 1st and 2nd/3rd orders, not a clean shutdown.

Usage: python3 tests/_kill_restart_scenario.py <ledger_path> <cycle_log_path> <kill_switch_path>
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import bot.execution as ex
import bot.heartbeat as hb
import bot.kill_switch as ks
import bot.risk_gate as rg
import bot.run_cycle as rc
from bot.alerting import BotAlerter
from bot.earnings_watcher import ReportedEarnings
from bot.signal_pipeline import ScoredEvent

ledger_path = Path(sys.argv[1])
cycle_log_path = Path(sys.argv[2])
kill_switch_path = Path(sys.argv[3])

ks.KILL_SWITCH_FILE = kill_switch_path
rc.CYCLE_LOG_FILE = cycle_log_path
# Regression fix (2026-08-19): this scenario's real run_cycle() call goes
# through risk_gate.evaluate() and PaperExecutionClient, both of which
# default to build_alerter() -- previously writing real alerts to the REAL
# production bot/state/bot_alerts.jsonl every time this scenario ran.
# Isolate it next to the sibling KILL_SWITCH_FILE/CYCLE_LOG_FILE files.
_isolated_alerts_path = kill_switch_path.parent / "scenario_alerts.jsonl"
rg.build_alerter = lambda: BotAlerter(webhook_url="", alerts_path=_isolated_alerts_path)
ex.build_alerter = lambda: BotAlerter(webhook_url="", alerts_path=_isolated_alerts_path)
# Same class of bug for the heartbeat -- run_cycle.py's own touch_heartbeat
# binding previously defaulted to the REAL production bot/state/heartbeat.txt,
# so every run of this scenario refreshed the real bot's dead-man's-switch.
_isolated_heartbeat_path = kill_switch_path.parent / "scenario_heartbeat.txt"
rc.touch_heartbeat = lambda: hb.touch_heartbeat(_isolated_heartbeat_path)

FAKE_TICKERS = ["AAPL", "MSFT", "NVDA"]
fake_events = [
    ReportedEarnings(ticker=t, earnings_date=pd.Timestamp("2024-01-02"),
                      eps_estimate=1.0, eps_actual=1.1, surprise_pct=10.0, days_since=1)
    for t in FAKE_TICKERS
]
rc.EarningsWatcher.get_recently_reported = lambda self, **kw: fake_events


def slow_score_event(event, pipeline):
    # Real pause between each candidate so an external kill -9 has a
    # reliable, wide window between order 1 and order 2/3.
    time.sleep(2.5)
    return ScoredEvent(
        ticker=event.ticker, earnings_date=event.earnings_date, sue=2.0,
        calibrated_proba=0.9, direction="long",
    )


rc.score_event = slow_score_event

report = rc.run_cycle(ledger_path=ledger_path)
print(f"SCENARIO COMPLETED CLEANLY: {len(report.entries)} entries")
