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

Before any of that, `prepare_market_session` refreshes the cached daily
bars the circuit breaker reads and decides whether `as_of` is a completed
regular session. Exits and entries only happen on one: on a weekend,
holiday, or a run before the 4pm ET close (e.g. launchd's RunAtLoad firing
at night), a paper fill would use a stale or pre-announcement price.
Earnings events already evaluated in an earlier cycle are not re-scored, so
an event rejected on its effective day cannot slip in days later.

Every cycle's outcome (exits, entries considered, entries placed, entries
blocked and why) is appended to bot/state/cycle_log.jsonl so a history of
runs is inspectable without replaying the trade ledger by hand.

NAV in the cycle log: nav_before / nav_after are the cash-basis NAV
(PaperExecutionClient.nav(), open positions at cost) -- the value that sizes
and gates trades, unchanged. On a completed session the cycle also records
marked_nav: cash plus every open position at that day's close, taken AFTER all
exits and entries, so marking cannot influence a decision. marks holds the
price used per open position and unmarked any position that could not be
priced (carried at cost, and reported in errors). Performance -- Sharpe,
volatility, drawdown -- is computed from marked_nav (bot/performance.py).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger
from zoneinfo import ZoneInfo

from bot.alerting import ALERT_EARNINGS_FEED_STALE, build_alerter
from bot.earnings_watcher import (
    EARNINGS_FEED_STALE_DAYS, EarningsWatcher, ReportedEarnings, ScheduledEarnings, load_breaker_universe,
)
from bot.execution import LEDGER_FILE, PaperExecutionClient
from bot.heartbeat import touch_heartbeat
from bot.kill_switch import is_kill_switch_engaged, read_kill_switch_status
from bot.position_manager import PositionManager
from bot.risk_gate import current_breaker_tier, evaluate
from bot.signal_pipeline import ScoredEvent, fit_or_load, score_event
from data.ingestion import refresh_cached_history
from risk.limits import RiskLimits

STATE_DIR = Path(__file__).parent / "state"
CYCLE_LOG_FILE = STATE_DIR / "cycle_log.jsonl"
UPCOMING_EARNINGS_FILE = STATE_DIR / "upcoming_earnings.json"
# Decisions replayed by live_backtest/backfill_missed_season.py for the season
# the bot missed; read alongside CYCLE_LOG_FILE so none is ever re-decided live.
BACKFILL_CYCLE_LOG_FILE = STATE_DIR / "backfill_cycle_log.jsonl"
STARTING_CAPITAL = 100_000.0
EARNINGS_LOOKBACK_DAYS = 3
UPCOMING_HORIZON_DAYS = 60
MARKET_TZ = ZoneInfo("America/New_York")
# Per-position and gross-exposure caps for the bot specifically (risk/limits.py
# keeps its generic 10%/60% defaults for research callers).
#
# Chosen from live_backtest/compare_configurations.py, which replays this exact
# code path over the model's holdout window under each candidate setting:
#   75 names, 10% / 60%   (the original)   5.24% net/yr, Sharpe 1.07, -8.4% DD
#   503 names, 2.5% / 60%                  5.24% net/yr, Sharpe 1.54, -5.4% DD
#   503 names, 3.5% / 85%                  7.17% net/yr, Sharpe 1.53, -7.9% DD
#   503 names, 5.0% / 100%  (this one)     8.30% net/yr, Sharpe 1.44, -10.6% DD
# (Those Sharpes are cash-basis with a zero risk-free rate. Marked daily and in
# excess of T-bills, the 5.0%/100% configuration is about 0.70 if idle cash
# earns the T-bill rate (reports/pead_audit/REPORT.md), and about 0.49 as the
# paper account actually runs, idle cash earning nothing -- the basis the
# dashboard and live_backtest/compute_final_metrics.py now report.)
# Deliberate, operator-chosen trade: the highest net return of the set, bought
# with risk rather than edge -- its Sharpe is the LOWEST of the three wide
# configurations and its drawdown the deepest, exceeding the original's. Gross
# exposure stops at 100% of NAV, so the bot never borrows. The 20% drawdown
# kill switch (bot/kill_switch.py) is unchanged and still sits well below the
# -10.6% this configuration drew down historically.
BOT_RISK_LIMITS = RiskLimits(max_position_pct=0.05, max_total_exposure_pct=1.00)
SESSION_SETTLED_AFTER = (16, 15)  # ET; daily bars and last prices reflect the close by then


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
    earnings_date: str = ""


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
    session_open: bool = True
    session_detail: str = ""
    # Marked to market at the session's close, after exits and entries; None
    # when the session was not open (no close to mark at).
    marked_nav: float | None = None
    unrealized_pnl: float | None = None
    marks: dict[str, float] = field(default_factory=dict)
    unmarked: list[str] = field(default_factory=list)


def _append_cycle_log(report: CycleReport) -> None:
    CYCLE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), **asdict(report)}
    with open(CYCLE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def prepare_market_session(tickers: list[str], as_of: str) -> tuple[bool, str]:
    """Refresh the cached daily bars for `tickers` and report whether `as_of`
    is a completed regular session: most of the universe has a bar dated
    `as_of`, and, when `as_of` is today, the ET clock is past the close."""
    latest = refresh_cached_history(tickers)
    dates = [pd.Timestamp(d).normalize() for d in latest.values() if d is not None]
    target = pd.Timestamp(as_of).normalize()
    if not dates:
        return False, "no cached price data could be refreshed"
    with_bar = sum(d == target for d in dates)
    if with_bar < 0.5 * len(dates):
        return False, f"no regular session on {as_of} ({with_bar}/{len(dates)} tickers have a bar; latest {max(dates).date()})"
    now_et = pd.Timestamp.now(tz=MARKET_TZ)
    if target == now_et.tz_localize(None).normalize() and (now_et.hour, now_et.minute) < SESSION_SETTLED_AFTER:
        return False, f"session on {as_of} has not closed yet (now {now_et:%H:%M} ET)"
    return True, f"session closed; {with_bar}/{len(dates)} tickers have a {as_of} bar"


def _previously_evaluated_events(path: Path) -> set[tuple[str, str]]:
    """(ticker, earnings_date) pairs already scored and gated in an earlier cycle."""
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            for entry in record.get("entries") or []:
                if entry.get("earnings_date"):
                    keys.add(_event_key(entry.get("ticker"), entry["earnings_date"]))
    return keys


def _event_key(ticker: str, earnings_date) -> tuple[str, str]:
    """One decision per announcement DAY: the same report can reach the bot with two
    timestamps (a schedule-log date stamped at the close during a feed outage, then
    the real time once the feed recovers), and must not be scored twice."""
    return ticker, pd.Timestamp(earnings_date).date().isoformat()


def _write_upcoming_earnings(events: list[ScheduledEarnings], as_of: str) -> None:
    """Snapshot of the universe's scheduled reports for the dashboard."""
    UPCOMING_EARNINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": time.time(), "as_of_date": as_of, "horizon_days": UPCOMING_HORIZON_DAYS,
        "events": [{**asdict(e), "earnings_date": e.earnings_date.isoformat()} for e in events],
    }
    tmp = UPCOMING_EARNINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, default=str))
    os.replace(tmp, UPCOMING_EARNINGS_FILE)


def run_cycle(as_of_date: str | None = None, ledger_path: Path = LEDGER_FILE) -> CycleReport:
    as_of = as_of_date or pd.Timestamp.now(tz=MARKET_TZ).strftime("%Y-%m-%d")
    logger.info(f"=== paper-trading cycle, as_of={as_of} ===")
    errors: list[str] = []

    if int(yf.__version__.split(".")[0]) < 1:
        errors.append(f"yfinance {yf.__version__} serves stale earnings dates; run the bot with quant_v7/.venv")

    watcher = EarningsWatcher()
    # The breaker basket (not the traded universe) defines a trading session and
    # feeds the circuit breaker -- see earnings_watcher.load_breaker_universe.
    session_open, session_detail = prepare_market_session(load_breaker_universe(), as_of)
    logger.info(f"market session: {'open' if session_open else 'closed'} ({session_detail})")

    kill_status = read_kill_switch_status()
    if kill_status.engaged:
        logger.warning(f"kill switch engaged (reason={kill_status.reason!r}) -- cycle will process exits only, "
                        f"no new entries can be approved")

    client = PaperExecutionClient.from_ledger(starting_capital=STARTING_CAPITAL, ledger_path=ledger_path)
    nav_before = client.nav()

    # -- 1. exits first, always, never breaker-gated ------------------------
    position_manager = PositionManager()
    exit_results = position_manager.process_exits(client, as_of_date=as_of) if session_open else []
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
    reported = watcher.get_recently_reported(days_back=EARNINGS_LOOKBACK_DAYS, now=pd.Timestamp(as_of))
    if watcher.dated_feed_down():
        message = (f"announcement-date feed down: answered for {watcher.dated_feed_answered}/{watcher.dated_feed_asked} "
                   f"tickers; recent reports are being dated from the bot's schedule log "
                   f"({watcher.schedule_dated_reports} in the window this cycle)")
        errors.append(message)
        build_alerter().alert(ALERT_EARNINGS_FEED_STALE, message)
    if watcher.feed_looks_stale(now=pd.Timestamp(as_of)):
        newest = watcher.newest_report.date() if watcher.newest_report is not None else "never"
        message = f"earnings feed looks stale: newest report in the universe is {newest} (> {EARNINGS_FEED_STALE_DAYS}d)"
        errors.append(message)
        build_alerter().alert(ALERT_EARNINGS_FEED_STALE, message)
    try:
        _write_upcoming_earnings(watcher.scheduled_from_last_fetch(UPCOMING_HORIZON_DAYS, now=pd.Timestamp(as_of)), as_of)
    except Exception as e:
        errors.append(f"upcoming earnings snapshot failed: {e!r}")

    pipeline = fit_or_load()
    entries: list[EntryOutcome] = []
    evaluated = _previously_evaluated_events(CYCLE_LOG_FILE) | _previously_evaluated_events(BACKFILL_CYCLE_LOG_FILE)

    # Score every candidate first, then gate them HIGHEST CONVICTION FIRST.
    # With ~480 events a quarter the 60% gross-exposure cap binds most days, and
    # the order it binds in decides what gets traded: report order made that an
    # accident of the earnings calendar, so the strongest signal could be turned
    # away for a marginal one that merely reported earlier.
    candidates: list[tuple[ReportedEarnings, ScoredEvent, str]] = []
    for event in reported if session_open else []:
        if event.ticker in client.positions and client.positions[event.ticker].open:
            continue  # already holding this name -- position_manager owns its exit, not a new entry
        event_key = _event_key(event.ticker, event.earnings_date)
        if event_key in evaluated:
            continue  # decided in an earlier cycle; one decision per announcement

        try:
            scored = score_event(event, pipeline)
        except Exception as e:
            errors.append(f"{event.ticker}: scoring failed: {e!r}")
            continue
        if scored is None:
            continue
        candidates.append((event, scored, pd.Timestamp(event.earnings_date).isoformat()))

    candidates.sort(key=lambda c: c[1].calibrated_proba, reverse=True)

    for event, scored, earnings_date_key in candidates:
        decision = evaluate(
            ticker=scored.ticker, calibrated_proba=scored.calibrated_proba, payoff_ratio_b=pipeline.payoff.b,
            current_total_exposure_pct=client.current_total_exposure_pct(), current_daily_pnl_pct=daily_pnl_pct,
            paper_nav=client.nav(), paper_high_water_mark=client.high_water_mark,
            limits=BOT_RISK_LIMITS, breaker_tier=tier,
        )
        outcome = EntryOutcome(
            ticker=scored.ticker, sue=scored.sue, calibrated_proba=scored.calibrated_proba,
            direction=scored.direction, allowed=decision.allowed,
            reason=decision.reason.value if decision.reason else None, detail=decision.detail,
            size_fraction=decision.size_fraction, earnings_date=earnings_date_key,
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

    # -- 4. mark to market: read-only, after every decision of this cycle ----
    marked = client.marked_nav() if session_open else None
    if marked is not None and marked.unmarked:
        errors.append(f"no price to mark {', '.join(marked.unmarked)}: carried at cost in marked_nav")

    report = CycleReport(
        as_of_date=as_of, kill_switch_engaged=is_kill_switch_engaged(), breaker_tier=tier,
        nav_before=nav_before, nav_after=client.nav(),
        exits=[asdict(e) for e in exit_results], entries_considered=len(reported),
        entries=entries, errors=errors, session_open=session_open, session_detail=session_detail,
        marked_nav=marked.nav if marked else None, unrealized_pnl=marked.unrealized_pnl if marked else None,
        marks=marked.marks if marked else {}, unmarked=marked.unmarked if marked else [],
    )
    _append_cycle_log(report)
    # Touched LAST, only once everything above has genuinely completed --
    # see bot/heartbeat.py's docstring for why a mid-cycle crash must NOT
    # refresh this (that's precisely the failure the watchdog exists to catch).
    touch_heartbeat()
    logger.info(f"cycle complete: {len(exit_results)} exits, {len(entries)} entries considered "
                f"({sum(1 for e in entries if e.allowed)} placed), nav {nav_before:.2f} -> {client.nav():.2f}"
                + (f", marked {marked.nav:.2f}" if marked else ""))
    return report


if __name__ == "__main__":
    run_cycle()
