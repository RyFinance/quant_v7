"""The orchestration entry point: one full paper-trading cycle.

Wires together, in this order, every module bot/ already has (nothing new
is reimplemented here -- this is glue, not logic):

  1. kill_switch / execution.from_ledger  -- reconstruct paper account state.
     Each cycle is a FRESH process (cron re-invokes this script; there is
     no long-lived in-memory bot). State survives only via the JSONL
     ledger, replayed on every start -- see execution.py's from_ledger
     docstring for why that's correct, not a workaround.
  2. position_manager.process_exits        -- close anything that has hit
     its fixed 20-trading-day holding period. Exits are ALWAYS processed
     before new entries are considered, and exits are never gated by the
     circuit breaker (an open position closing on schedule is not a "new
     entry" -- see risk_gate.py's own comment on this).
  3. earnings_watcher.get_recently_reported -- real trigger: what in the
     validated 75-name universe reported earnings in the last few days.
  4. signal_pipeline.score_event            -- real SUE -> calibrated
     probability, using the model fit on the EXPANDED, statistically-
     validated dataset (see signal_pipeline.py's fit_or_load docstring).
  5. risk_gate.evaluate                     -- the sole path to an approval
     token. Kill switch, drawdown cap, circuit breaker, Kelly size, E2
     limits -- exactly as built, nothing loosened.
  6. execution.place_order                  -- paper fill at a real price,
     JSONL ledger write, only if step 5 approved.

Every cycle's outcome (exits, entries considered, entries placed, entries
blocked and why) is appended to bot/state/cycle_log.jsonl so a history of
runs is inspectable without replaying the trade ledger by hand.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
from loguru import logger

from bot.earnings_watcher import EarningsWatcher, ReportedEarnings
from bot.execution import LEDGER_FILE, PaperExecutionClient
from bot.heartbeat import touch_heartbeat
from bot.kill_switch import is_kill_switch_engaged, read_kill_switch_status
from bot.position_manager import PositionManager
from bot.risk_gate import current_breaker_tier, evaluate
from bot.signal_pipeline import ScoredEvent, fit_or_load, score_event
from risk.limits import RiskLimits

STATE_DIR = Path(__file__).parent / "state"
CYCLE_LOG_FILE = STATE_DIR / "cycle_log.jsonl"
STARTING_CAPITAL = 100_000.0
EARNINGS_LOOKBACK_DAYS = 3


@dataclass
class EntryOutcome:
    ticker: str
    sue: float
    calibrated_proba: float
    direction: str
    allowed: bool
    reason: str | None
    detail: str
    size_fraction: float = 0.0


@dataclass
class CycleReport:
    as_of_date: str
    kill_switch_engaged: bool
    breaker_tier: str
    nav_before: float
    nav_after: float
    exits: list[dict] = field(default_factory=list)
    entries_considered: int = 0
    entries: list[EntryOutcome] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _append_cycle_log(report: CycleReport) -> None:
    CYCLE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), **asdict(report)}
    with open(CYCLE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def run_cycle(as_of_date: str | None = None, ledger_path: Path = LEDGER_FILE) -> CycleReport:
    as_of = as_of_date or pd.Timestamp.now().strftime("%Y-%m-%d")
    logger.info(f"=== paper-trading cycle, as_of={as_of} ===")

    kill_status = read_kill_switch_status()
    if kill_status.engaged:
        logger.warning(f"kill switch engaged (reason={kill_status.reason!r}) -- cycle will process exits only, "
                        f"no new entries can be approved")

    client = PaperExecutionClient.from_ledger(starting_capital=STARTING_CAPITAL, ledger_path=ledger_path)
    nav_before = client.nav()

    # -- 1. exits first, always, never breaker-gated ------------------------
    position_manager = PositionManager()
    exit_results = position_manager.process_exits(client, as_of_date=as_of)
    for e in exit_results:
        logger.info(f"EXIT {e.ticker}: held {e.days_held}d, pnl={e.realized_pnl:.2f}")

    daily_pnl_dollars = sum(e.realized_pnl for e in exit_results)
    nav_after_exits = client.nav()
    daily_pnl_pct = daily_pnl_dollars / nav_after_exits if nav_after_exits > 0 else 0.0

    # -- 2. compute the breaker tier ONCE for this cycle (all entry checks
    #    this cycle share the same as-of-today read, not re-derived per order)
    tier, tier_detail = current_breaker_tier()
    logger.info(f"circuit breaker tier: {tier} ({tier_detail})")

    # -- 3. candidate entries -------------------------------------------------
    watcher = EarningsWatcher()
    reported = watcher.get_recently_reported(days_back=EARNINGS_LOOKBACK_DAYS)

    pipeline = fit_or_load()
    entries: list[EntryOutcome] = []
    errors: list[str] = []

    for event in reported:
        if event.ticker in client.positions and client.positions[event.ticker].open:
            continue  # already holding this name -- position_manager owns its exit, not a new entry

        try:
            scored = score_event(event, pipeline)
        except Exception as e:
            errors.append(f"{event.ticker}: scoring failed: {e!r}")
            continue
        if scored is None:
            continue

        decision = evaluate(
            ticker=scored.ticker, calibrated_proba=scored.calibrated_proba, payoff_ratio_b=pipeline.payoff.b,
            current_total_exposure_pct=client.current_total_exposure_pct(), current_daily_pnl_pct=daily_pnl_pct,
            paper_nav=client.nav(), paper_high_water_mark=client.high_water_mark,
            limits=RiskLimits(), breaker_tier=tier,
        )
        outcome = EntryOutcome(
            ticker=scored.ticker, sue=scored.sue, calibrated_proba=scored.calibrated_proba,
            direction=scored.direction, allowed=decision.allowed,
            reason=decision.reason.value if decision.reason else None, detail=decision.detail,
            size_fraction=decision.size_fraction,
        )
        entries.append(outcome)

        if decision.allowed:
            try:
                client.place_order(scored.ticker, scored.direction, decision, entry_date=as_of)
                logger.info(f"ENTRY {scored.ticker} {scored.direction} size={decision.size_fraction:.3%} "
                            f"proba={scored.calibrated_proba:.3f}")
            except Exception as e:
                errors.append(f"{scored.ticker}: place_order failed: {e!r}")
        else:
            logger.info(f"SKIP {scored.ticker}: {outcome.reason} -- {outcome.detail}")

    report = CycleReport(
        as_of_date=as_of, kill_switch_engaged=is_kill_switch_engaged(), breaker_tier=tier,
        nav_before=nav_before, nav_after=client.nav(),
        exits=[asdict(e) for e in exit_results], entries_considered=len(reported),
        entries=entries, errors=errors,
    )
    _append_cycle_log(report)
    # Touched LAST, only once everything above has genuinely completed --
    # see bot/heartbeat.py's docstring for why a mid-cycle crash must NOT
    # refresh this (that's precisely the failure the watchdog exists to catch).
    touch_heartbeat()
    logger.info(f"cycle complete: {len(exit_results)} exits, {len(entries)} entries considered "
                f"({sum(1 for e in entries if e.allowed)} placed), nav {nav_before:.2f} -> {client.nav():.2f}")
    return report


if __name__ == "__main__":
    run_cycle()
