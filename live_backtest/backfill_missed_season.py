"""Backfill the 2026-07/09 earnings season the live bot missed into the REAL
paper account.

bot/run_cycle.py was blind to every earnings report until 2026-09-17 (see
earnings.ingestion.fetch_ticker_earnings_live's docstring). This replays
each business day of the season through the unmodified run_cycle() code
path -- the same watcher, scoring, risk gate, execution client and holding-
period exits -- and writes the outcome into bot/state/paper_ledger.jsonl, so
the paper account reflects what the fixed bot would have done. Every ledger
line and alert written here carries "backfill": true, and each simulated
cycle's decisions go to bot/state/backfill_cycle_log.jsonl (never the live
cycle log). `--undo` removes exactly those records.

Point-in-time inputs for each simulated day D, patched in the same way
live_backtest/run_historical_replay.py patches its pinned-data replay:
  * fills: D's official close from yfinance (split-adjusted, not dividend-
    adjusted) -- the price a 15:42 PT live cycle records as the last price;
  * earnings: today's announcement history, which run_cycle filters to
    reports effective on or before D (SUE only uses earlier quarters);
  * circuit breaker: the real trigger code over cached bars truncated at D;
  * session: D trades only if the cached bars include a D bar (holidays don't);
  * timestamps: ledger, alert and cycle records are stamped with D at the
    live 15:42 PT schedule, so the dashboard orders them correctly.
Positions still open after the last day stay open; the live bot exits them
on schedule with live prices.

Run (with the bot's venv, never concurrently with a live cycle):
    PYTHONPATH=. .venv/bin/python -m live_backtest.backfill_missed_season
    PYTHONPATH=. .venv/bin/python -m live_backtest.backfill_missed_season --undo
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from loguru import logger

import bot.alerting as alerting_module
import bot.earnings_watcher as earnings_watcher_module
import bot.execution as execution_module
import bot.risk_gate as risk_gate_module
import bot.run_cycle as run_cycle_module
import bot.signal_pipeline as signal_pipeline_module
from bot.alerting import ALERTS_LOG_FILE, BotAlerter
from bot.execution import LEDGER_FILE, PaperExecutionClient
from bot.kill_switch import is_kill_switch_engaged

SEASON_START = "2026-07-01"
SEASON_END = "2026-09-16"
LIVE_SCHEDULE_TZ = ZoneInfo("America/Los_Angeles")
LIVE_SCHEDULE_TIME = (15, 42)
BACKFILL_CYCLE_LOG = run_cycle_module.BACKFILL_CYCLE_LOG_FILE
SCRATCH_DIR = Path(__file__).parent / "state" / "backfill"


class SimulatedClock:
    """Stands in for the `time` module inside bot/ so every record carries
    the simulated cycle's timestamp instead of the wall clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now


class BackfillAlerter(BotAlerter):
    def _write_record(self, kind: str, message: str, fields: dict):
        super()._write_record(kind, message, {**fields, "backfill": True})


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _cycle_timestamp(day: pd.Timestamp) -> float:
    hour, minute = LIVE_SCHEDULE_TIME
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LIVE_SCHEDULE_TZ).timestamp()


def install_point_in_time_patches(day_holder: dict, closes: pd.DataFrame) -> SimulatedClock:
    clock = SimulatedClock()
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    def close_on_day(ticker: str) -> float:
        price = closes[ticker].get(day_holder["day"], float("nan")) if ticker in closes.columns else float("nan")
        if pd.isna(price) or price <= 0:
            raise RuntimeError(f"no close for {ticker} on {day_holder['day'].date()}")
        return float(price)

    real_load_universe = risk_gate_module.load_universe
    universe_cache: dict[tuple, dict] = {}

    def load_universe_as_of(tickers: list[str]) -> dict[str, pd.DataFrame]:
        key = tuple(tickers)
        if key not in universe_cache:
            universe_cache[key] = {t: df.assign(timestamp=pd.to_datetime(df["timestamp"])) for t, df in real_load_universe(tickers).items()}
        return {t: df[df["timestamp"] <= day_holder["day"]] for t, df in universe_cache[key].items()}

    real_quality_checks = risk_gate_module.run_quality_checks

    def session_as_of(tickers: list[str], as_of: str) -> tuple[bool, str]:
        target = pd.Timestamp(as_of).normalize()
        data = load_universe_as_of(tickers)
        with_bar = sum(1 for df in data.values() if not df.empty and df["timestamp"].iloc[-1].normalize() == target)
        if with_bar < 0.5 * max(len(data), 1):
            return False, f"no regular session on {as_of} ({with_bar}/{len(data)} tickers have a bar)"
        return True, f"backfill: session closed; {with_bar}/{len(data)} tickers have a {as_of} bar"

    history = lru_cache(maxsize=None)(earnings_watcher_module.fetch_ticker_earnings_live)
    pipeline = signal_pipeline_module.fit_or_load()
    original_append = PaperExecutionClient._append_ledger

    def append_backfill(self, record: dict) -> None:
        original_append(self, {**record, "backfill": True})

    def build_backfill_alerter() -> BotAlerter:
        return BackfillAlerter(webhook_url="", alerts_path=ALERTS_LOG_FILE)

    execution_module.get_current_price = close_on_day
    PaperExecutionClient._append_ledger = append_backfill
    risk_gate_module.load_universe = load_universe_as_of
    risk_gate_module.run_quality_checks = lambda data: real_quality_checks(data, log_path=SCRATCH_DIR / "data_quality.jsonl")
    earnings_watcher_module.fetch_ticker_earnings_live = history
    signal_pipeline_module.fetch_ticker_earnings_live = history
    run_cycle_module.prepare_market_session = session_as_of
    run_cycle_module.fit_or_load = lambda force_refit=False: pipeline
    run_cycle_module.CYCLE_LOG_FILE = BACKFILL_CYCLE_LOG
    run_cycle_module.UPCOMING_EARNINGS_FILE = SCRATCH_DIR / "upcoming_earnings.json"
    run_cycle_module.touch_heartbeat = lambda: None
    for module in (alerting_module, risk_gate_module, execution_module, run_cycle_module):
        module.build_alerter = build_backfill_alerter
    for module in (run_cycle_module, execution_module, alerting_module):
        module.time = clock
    return clock


def run_backfill(start: str = SEASON_START, end: str = SEASON_END) -> list:
    ledger = _read_jsonl(LEDGER_FILE)
    if any(r.get("backfill") for r in ledger):
        raise SystemExit("backfill records already exist in the paper ledger; run with --undo first")
    if ledger:
        raise SystemExit("the paper ledger already has live trades; backfilling underneath them would rewrite history")
    if BACKFILL_CYCLE_LOG.exists():
        raise SystemExit(f"{BACKFILL_CYCLE_LOG} already exists; run with --undo first")
    if is_kill_switch_engaged():
        raise SystemExit("kill switch is engaged; clear it before backfilling")

    tickers = earnings_watcher_module.load_validated_universe()
    closes = yf.download(tickers, start=start, end=(pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                         auto_adjust=False, progress=False)["Close"]
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()

    days = pd.bdate_range(start, end)
    day_holder = {"day": days[0]}
    clock = install_point_in_time_patches(day_holder, closes)
    logger.info(f"backfilling {len(days)} business days {start} -> {end} into {LEDGER_FILE}")

    reports = []
    for day in days:
        day_holder["day"] = day
        clock.now = _cycle_timestamp(day)
        report = run_cycle_module.run_cycle(as_of_date=day.strftime("%Y-%m-%d"), ledger_path=LEDGER_FILE)
        reports.append(report)

    client = PaperExecutionClient.from_ledger(ledger_path=LEDGER_FILE)
    opened = sum(1 for r in _read_jsonl(LEDGER_FILE) if r["event"] == "open")
    still_open = [p.ticker for p in client.positions.values() if p.open]
    logger.info(f"backfill complete: {opened} trades, {opened - len(still_open)} closed, "
                f"realized P&L {client.realized_pnl:+.2f}, still open: {', '.join(still_open) or 'none'}")
    return reports


def undo_backfill() -> None:
    ledger = _read_jsonl(LEDGER_FILE)
    first_backfill = next((i for i, r in enumerate(ledger) if r.get("backfill")), None)
    if first_backfill is None:
        logger.info("no backfill records in the paper ledger")
    else:
        live_after = [r for r in ledger[first_backfill:] if not r.get("backfill")]
        if live_after:
            raise SystemExit(f"{len(live_after)} live ledger records were written after the backfill "
                             f"(e.g. live exits of backfilled positions); undo would orphan them -- resolve by hand")
    for path in (LEDGER_FILE, ALERTS_LOG_FILE):
        if not path.exists():
            continue
        lines = path.read_text().splitlines(keepends=True)
        kept = [line for line in lines if not (line.strip() and json.loads(line).get("backfill"))]
        path.write_text("".join(kept))
        logger.info(f"{path}: removed {len(lines) - len(kept)} backfill records")
    BACKFILL_CYCLE_LOG.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", default=SEASON_START)
    parser.add_argument("--end", default=SEASON_END)
    parser.add_argument("--undo", action="store_true", help="remove every backfill record")
    args = parser.parse_args()
    if args.undo:
        undo_backfill()
    else:
        run_backfill(args.start, args.end)


if __name__ == "__main__":
    main()
