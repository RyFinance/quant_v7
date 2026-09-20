"""Local monitoring + control dashboard backend for the PEAD paper-trading
bot (bot/run_cycle.py). Serves live data pulled fresh (no caching) from the
REAL production state files under bot/state/ and reports/.

THIS APP IS READ-ONLY WITH RESPECT TO BOT STATE AND TRADING, WITH ONE
DELIBERATE, NARROW EXCEPTION: two POST endpoints, /api/control/start and
/api/control/stop, which call `launchctl bootstrap`/`bootout` against the
two REAL, already-installed LaunchAgents that schedule this bot
(com.rytty.quant_v7.pead_bot, com.rytty.quant_v7.pead_watchdog), via
bot/launchd_control.py. This is NOT a second execution path -- it only
toggles the SAME scheduled invocation (`python3 -m bot.run_cycle`) that
already runs unattended via launchd; it can turn that existing schedule on
or off, nothing more. It never places an order, never writes to
bot/state/ directly, and never imports anything from a live-trading path.
Plist paths/labels are hardcoded constants in bot/launchd_control.py -- no
request input ever reaches the subprocess argument list, and every
subprocess call there uses an explicit argument list with the shell flag
never enabled. Before either control endpoint (or /api/launchd_status)
reports/acts on paper-trade mode, it calls
bot.execution.assert_paper_only_mode(), which re-verifies at request time
that LiveExecutionClient is still an unimplemented stub -- if that
invariant ever breaks, these endpoints fail loudly (HTTP 500) instead of
silently claiming paper mode. Every OTHER endpoint in this file remains
exactly as read-only as before: it only reads real files on disk and
returns their contents as JSON. The one bot/ import that touches "state"
outside the control endpoints is `PaperExecutionClient.from_ledger`, which
is itself a pure read-and-replay reconstruction (see execution.py's
docstring) -- it opens the ledger for reading only.

Binds to 127.0.0.1 ONLY (see the __main__ block / run instructions below)
-- this is a local-only tool, never expose it on 0.0.0.0 or a public
interface.

--------------------------------------------------------------------------
Install (check first -- this repo may already have these; verified via
`pip3 show fastapi uvicorn` while building this file: fastapi==0.139.0,
uvicorn==0.35.0 were already present in this environment. If they are
missing in yours):

    pip3 install fastapi uvicorn

Run:

    cd /Users/rytty/CCP/quant_v7
    PYTHONPATH=. uvicorn live_backtest.dashboard.backend:app --port 8420 --host 127.0.0.1

Then open http://127.0.0.1:8420/ in a browser.
--------------------------------------------------------------------------
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from data.ingestion import RAW_DATA_DIR
from bot.alerting import ALERTS_LOG_FILE
from bot.execution import LEDGER_FILE, PaperExecutionClient, assert_paper_only_mode, unrealized_pnl
from bot.heartbeat import read_heartbeat_age_seconds
from bot.kill_switch import read_kill_switch_status
from bot.launchd_control import get_operation_status, start_bot_operation, stop_bot_operation
from bot.performance import (
    cached_closes, daily_marked_nav, excess_metrics, price_panel, recorded_marks, risk_free_last_published,
)
from bot.position_manager import trading_days_elapsed

# -- real paths -------------------------------------------------------------
# LEDGER_FILE / ALERTS_LOG_FILE are imported directly from the bot's own
# modules (bot/execution.py, bot/alerting.py) so this dashboard can never
# drift out of sync with where the real bot actually writes those files.
STATE_DIR = LEDGER_FILE.parent  # bot/state/
CYCLE_LOG_PATH = STATE_DIR / "cycle_log.jsonl"  # mirrors bot/run_cycle.py::CYCLE_LOG_FILE
UPCOMING_EARNINGS_PATH = STATE_DIR / "upcoming_earnings.json"  # mirrors bot/run_cycle.py::UPCOMING_EARNINGS_FILE
BACKFILL_CYCLE_LOG_PATH = STATE_DIR / "backfill_cycle_log.jsonl"  # mirrors bot/run_cycle.py::BACKFILL_CYCLE_LOG_FILE

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
CIRCUIT_BREAKER_CSV = REPORTS_DIR / "circuit_breaker_daily_production.csv"
LIVE_BACKTEST_METRICS_PATH = REPORTS_DIR / "pead_live_backtest_metrics.json"
LIVE_BACKTEST_MONTE_CARLO_PATH = REPORTS_DIR / "pead_live_backtest_monte_carlo.json"
# Pre-registered out-of-sample tests (research/preregistrations.jsonl holds their hashes)
PREREGISTRATIONS_PATH = REPO_ROOT / "research" / "preregistrations.jsonl"
PEAD_2004_2014_RESULTS = REPORTS_DIR / "pead_2004_2014" / "results.json"
MULTIASSET_DEV_RESULTS = REPORTS_DIR / "multiasset" / "dev_results.json"
MULTIASSET_HOLDOUT_RESULTS = REPORTS_DIR / "multiasset" / "holdout" / "results.json"
CRYPTO_DEV_RESULTS = REPORTS_DIR / "multiasset" / "crypto" / "dev_results.json"
CRYPTO_HOLDOUT_RESULTS = REPORTS_DIR / "multiasset" / "crypto" / "holdout_results.json"
RESEARCH_TARGET = {"sharpe": 2.0, "cagr": 0.10}

# Daily bar cache (data.ingestion.refresh_cached_history). The bot refreshes it
# every cycle for the circuit-breaker basket only, so for most traded names it
# can lag; the per-position closes run_cycle records in the cycle logs ("marks")
# take precedence wherever they exist. Never a live quote.
PRICE_CACHE_DIR = RAW_DATA_DIR

DASHBOARD_DIR = Path(__file__).resolve().parent
INDEX_HTML_PATH = DASHBOARD_DIR / "index.html"

# Same constant as bot/run_cycle.py::STARTING_CAPITAL -- the paper account's
# cash-basis starting NAV.
STARTING_CAPITAL = 100_000.0

# Heartbeat is considered stale past 26 hours -- one missed trading day plus
# slack, matching the watchdog's own dead-man's-switch framing (see
# bot/watchdog.py) without importing that module (which is a running daemon,
# not a read helper).
HEARTBEAT_STALE_SECONDS = 26 * 3600

app = FastAPI(
    title="PEAD Paper-Trading Dashboard",
    description="Local, read-only monitor for the paper-trading bot. Never places orders.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8420", "http://localhost:8420"],
    allow_credentials=False,
    # "POST" is needed for /api/control/start and /api/control/stop -- the
    # ONLY write endpoints in this app. Still no wildcard origin and still
    # allow_credentials=False; requiring a JSON body ({"confirm": true}) on
    # both POST endpoints forces a CORS preflight for any cross-origin
    # attempt, which this restrictive allow_origins list rejects -- a cheap
    # CSRF mitigation layered on top of the 127.0.0.1-only bind.
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# -- shared read helpers ------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts. Missing file -> []. Any line
    that fails to parse is skipped rather than raising -- a partially
    written last line (e.g. a concurrent writer mid-flush) must not 500 a
    read-only dashboard."""
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return records


def _read_json_file(path: Path) -> dict | None:
    """Read a whole JSON file. Missing or unparsable -> None (caller decides
    the {"available": false} fallback)."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _tail_jsonl_newest_first(path: Path, limit: int) -> list[dict]:
    records = _read_jsonl(path)
    records.sort(key=lambda r: r.get("ts", 0.0), reverse=True)
    if limit is not None:
        records = records[: max(limit, 0)]
    return records


def _paper_mode_or_500() -> None:
    """Gate for /api/launchd_status and both /api/control/* endpoints.
    Converts a broken paper-mode invariant (see
    bot.execution.assert_paper_only_mode's docstring) into a loud HTTP 500
    instead of ever silently reporting or acting on PAPER_TRADE mode."""
    try:
        assert_paper_only_mode()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _cycle_log_record_to_wire_events(record: dict) -> list[dict[str, Any]]:
    """Flatten one cycle_log.jsonl row into one wire-feed line per exit,
    entry outcome, and error -- plus one summary "cycle_run" marker line --
    matching the terminal-style one-event-per-line format the LOOP EVENTS
    WIRE panel uses, instead of dumping one dense JSON blob per cycle. Line
    text mirrors bot/run_cycle.py's own logger.info lines (EXIT/ENTRY/SKIP)
    so the dashboard reads like the real log."""
    ts = record.get("ts", 0.0)
    as_of_date = record.get("as_of_date")
    events: list[dict[str, Any]] = [{
        "ts": ts, "source": "cycle", "kind": "cycle_run",
        "summary": (
            f"cycle {as_of_date}: breaker={record.get('breaker_tier')} "
            f"kill_switch={'ENGAGED' if record.get('kill_switch_engaged') else 'clear'} "
            f"nav {record.get('nav_before', 0.0):.2f}->{record.get('nav_after', 0.0):.2f} "
            f"entries_considered={record.get('entries_considered', 0)}"
        ),
    }]
    for exit_row in record.get("exits") or []:
        events.append({
            "ts": ts, "source": "cycle", "kind": "exit",
            "summary": f"EXIT {exit_row.get('ticker')}: held {exit_row.get('days_held')}d, "
                       f"pnl={exit_row.get('realized_pnl', 0.0):.2f}",
        })
    for entry in record.get("entries") or []:
        if entry.get("allowed"):
            events.append({
                "ts": ts, "source": "cycle", "kind": "entry_placed",
                "summary": f"ENTRY {entry.get('ticker')} {entry.get('direction')} "
                           f"size={entry.get('size_fraction', 0.0):.3%} proba={entry.get('calibrated_proba', 0.0):.3f}",
            })
        else:
            events.append({
                "ts": ts, "source": "cycle", "kind": "entry_skipped",
                "summary": f"SKIP {entry.get('ticker')}: {entry.get('reason')} -- {entry.get('detail')}",
            })
    for err in record.get("errors") or []:
        events.append({"ts": ts, "source": "cycle", "kind": "error", "summary": str(err)})
    return events


def _read_latest_circuit_breaker_tier() -> str:
    """The LAST row of reports/circuit_breaker_daily_production.csv is the
    most recent real circuit breaker tier (per the production calibration
    report's own convention -- see bot/risk_gate.py::current_breaker_tier's
    docstring contrasting itself with this static snapshot). Reading the
    static snapshot here (not recomputing live) keeps this a fast, read-only
    poll endpoint rather than one that re-runs the breaker's own trigger
    evaluation on every dashboard refresh."""
    if not CIRCUIT_BREAKER_CSV.exists():
        return "unknown"
    try:
        with open(CIRCUIT_BREAKER_CSV, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            last_row: dict | None = None
            for row in reader:
                last_row = row
        if not last_row:
            return "unknown"
        return last_row.get("tier") or "unknown"
    except OSError:
        return "unknown"


def _reconstruct_all_trades(ledger_path: Path) -> list[dict]:
    """Reconstruct every trade (open AND closed) from the ledger, one entry
    per open/close pair, in the trade schema the API contract defines.

    Deliberately NOT `PaperExecutionClient.from_ledger` here: that method
    (correctly, for its own purpose of reconstructing CURRENT open
    positions -- see /api/positions below) keeps only one entry per ticker,
    overwritten on every new "open" record. A ticker that opened and closed
    more than once over the life of the ledger would lose its earlier closed
    trades under that dict-keyed-by-ticker replay. This dashboard's trade
    LOG needs the full history, so it replays the same events into a list
    instead, matching each "close" to the most recently un-matched "open"
    for that ticker (place_order's own ValueError guard means a ticker can
    only ever have one open position at a time, so this pairing is
    unambiguous)."""
    records = _read_jsonl(ledger_path)
    trades: list[dict] = []
    open_by_ticker: dict[str, dict] = {}

    for record in records:
        event = record.get("event")
        if event == "open":
            trade = {
                "ticker": record.get("ticker"),
                "direction": record.get("direction"),
                "entry_date": record.get("entry_date"),
                "entry_price": record.get("fill_price"),
                "exit_date": None,
                "exit_price": None,
                "size_fraction": record.get("size_fraction"),
                "notional": record.get("notional"),
                "realized_pnl": None,
                "gross_pnl": None,
                "cost": None,
                "open": True,
                "backfill": bool(record.get("backfill")),
                "_sort_ts": record.get("ts", 0.0),
            }
            trades.append(trade)
            open_by_ticker[trade["ticker"]] = trade
        elif event == "close":
            ticker = record.get("ticker")
            trade = open_by_ticker.pop(ticker, None)
            if trade is None:
                # A close with no matching open in this ledger (e.g. a
                # truncated/rotated history). Surface it as its own row
                # rather than silently dropping real ledger data.
                trade = {
                    "ticker": ticker,
                    "direction": record.get("direction"),
                    "entry_date": None,
                    "entry_price": record.get("entry_price"),
                    "size_fraction": None,
                    "notional": record.get("notional"),
                    "gross_pnl": None,
                    "cost": None,
                    "open": True,
                    "backfill": bool(record.get("backfill")),
                    "_sort_ts": record.get("ts", 0.0),
                }
                trades.append(trade)
            trade["exit_date"] = record.get("exit_date")
            trade["exit_price"] = record.get("exit_price")
            trade["realized_pnl"] = record.get("realized_pnl")
            trade["gross_pnl"] = record.get("gross_pnl")
            trade["cost"] = record.get("cost")
            trade["open"] = False
            trade["_sort_ts"] = record.get("ts", trade["_sort_ts"])

    trades.sort(key=lambda t: t.get("_sort_ts", 0.0), reverse=True)
    for t in trades:
        t.pop("_sort_ts", None)
    return trades


def _price_panel(tickers: set[str]) -> pd.DataFrame:
    """Daily closes for `tickers`: the bot's recorded marks, else cached bars."""
    recorded = recorded_marks(_read_jsonl(CYCLE_LOG_PATH) + _read_jsonl(BACKFILL_CYCLE_LOG_PATH))
    panel = price_panel(cached_closes(tickers, PRICE_CACHE_DIR), recorded)
    return panel.reindex(columns=sorted(tickers))


def _latest_close(panel: pd.DataFrame, ticker: str, since: str | None) -> tuple[float | None, str | None]:
    """Latest close on or after `since` (the entry date): a close from before
    a position was opened says nothing about its P&L."""
    if ticker not in panel.columns:
        return None, None
    closes = panel[ticker].dropna()
    if since:
        closes = closes[closes.index >= pd.Timestamp(since).normalize()]
    if closes.empty:
        return None, None
    return float(closes.iloc[-1]), closes.index[-1].date().isoformat()


def _open_positions(ledger_path: Path) -> list[dict[str, Any]]:
    """Open positions (via PaperExecutionClient.from_ledger), each marked at
    its latest close (see _price_panel). unrealized_pnl mirrors
    PaperExecutionClient.close_position's P&L formula."""
    client = PaperExecutionClient.from_ledger(starting_capital=STARTING_CAPITAL, ledger_path=ledger_path)
    backfill_by_ticker = {r.get("ticker"): bool(r.get("backfill"))
                          for r in _read_jsonl(ledger_path) if r.get("event") == "open"}
    today_str = date.today().isoformat()
    panel = _price_panel({t for t, p in client.positions.items() if p.open})

    out: list[dict[str, Any]] = []
    for position in client.positions.values():
        if not position.open:
            continue
        last_close, last_close_date = _latest_close(panel, position.ticker, position.entry_date)
        unrealized = None
        if last_close is not None and position.entry_price:
            unrealized = unrealized_pnl(position.direction, position.notional, position.entry_price, last_close)
        out.append({
            "ticker": position.ticker,
            "direction": position.direction,
            "entry_price": position.entry_price,
            "entry_date": position.entry_date,
            "size_fraction": position.size_fraction,
            "notional": position.notional,
            "days_held": trading_days_elapsed(position.entry_date, today_str) if position.entry_date else 0,
            "last_close": last_close,
            "last_close_date": last_close_date,
            "unrealized_pnl": unrealized,
            "backfill": backfill_by_ticker.get(position.ticker, False),
        })
    out.sort(key=lambda p: p.get("entry_date") or "", reverse=True)
    return out


def _marked_nav_frame(ledger_path: Path) -> pd.DataFrame:
    """The paper account rebuilt day by day (bot.performance.daily_marked_nav):
    cash-basis and marked NAV on every trading day from the first entry, plus
    every entry and exit date, so all realized P&L is in the last row."""
    records = _read_jsonl(ledger_path)
    opens = [r for r in records if r.get("event") == "open" and r.get("ticker") and r.get("entry_date")]
    if not opens:
        return pd.DataFrame(columns=["cash_basis_nav", "marked_nav", "unrealized_pnl", "open_positions", "stale_marks"])
    panel = _price_panel({r["ticker"] for r in opens})
    first_entry = min(pd.Timestamp(r["entry_date"]).normalize() for r in opens)
    trading_days = panel.index[panel.notna().any(axis=1) & (panel.index >= first_entry)]
    event_days = [pd.Timestamp(r[k]).normalize() for r in records for k in ("entry_date", "exit_date") if r.get(k)]
    return daily_marked_nav(records, panel, trading_days.union(pd.DatetimeIndex(event_days)), STARTING_CAPITAL)


def _compute_equity_curve(ledger_path: Path) -> dict:
    """Real cumulative NAV over time: replay the ledger's close events
    chronologically by exit_date, starting from STARTING_CAPITAL. One point
    per exit date (the NAV after all of that day's closes), anchored at
    STARTING_CAPITAL on the first entry date so the curve shows where the
    account started rather than beginning at the first realized result.

    `marked` is the daily series performance is computed from: the NAV marked
    to market at each trading day's close, with the cash-basis NAV on the same
    days for comparison."""
    records = _read_jsonl(ledger_path)
    closes = [r for r in records if r.get("event") == "close"]
    closes.sort(key=lambda r: (r.get("exit_date") or "", r.get("ts", 0.0)))

    nav_by_date: dict[str, float] = {}
    running_nav = STARTING_CAPITAL
    for r in closes:
        running_nav += float(r.get("realized_pnl", 0.0) or 0.0)
        nav_by_date[r.get("exit_date")] = round(running_nav, 6)

    entry_dates = sorted(r.get("entry_date") for r in records if r.get("event") == "open" and r.get("entry_date"))
    if nav_by_date and entry_dates and entry_dates[0] < min(nav_by_date):
        nav_by_date = {entry_dates[0]: STARTING_CAPITAL, **nav_by_date}

    frame = _marked_nav_frame(ledger_path)
    marked = {
        "dates": [d.date().isoformat() for d in frame.index],
        "nav": [round(float(v), 2) for v in frame["marked_nav"]],
        "cash_basis_nav": [round(float(v), 2) for v in frame["cash_basis_nav"]],
    }
    return {"dates": list(nav_by_date), "nav": list(nav_by_date.values()), "marked": marked}


def _compute_stats(ledger_path: Path) -> dict:
    """Stats from the REAL production ledger. Sharpe / Sortino / max drawdown
    come from backtest/metrics.py::compute_metrics (the function every report
    in this repo uses) over the DAILY MARK-TO-MARKET NAV (_marked_nav_frame:
    cash plus open positions at each day's close), with Sharpe and Sortino in
    excess of the daily 1-month T-bill rate (Ken French daily RF, last
    published rate carried forward -- bot/performance.py).

    Until 2026-09-18 these used the cash-basis NAV (open positions at cost,
    changing only on exit days) with a zero risk-free rate, which roughly
    doubled the Sharpe (reports/pead_audit/REPORT.md). current_nav and
    total_return_pct are still cash-basis, as labelled on the dashboard;
    marked_nav is the account at its latest marks.

    Returns insufficient_data=True (with null float fields, not fabricated
    numbers) when there are fewer than 2 closed trades."""
    records = _read_jsonl(ledger_path)
    n_trades = sum(1 for r in records if r.get("event") == "open")
    n_backfilled_trades = sum(1 for r in records if r.get("event") == "open" and r.get("backfill"))
    closes = [r for r in records if r.get("event") == "close"]
    n_closed_trades = len(closes)
    marks = [p["unrealized_pnl"] for p in _open_positions(ledger_path)]
    unrealized_pnl = round(sum(marks), 2) if all(m is not None for m in marks) else None

    realized_pnls = [float(r.get("realized_pnl", 0.0) or 0.0) for r in closes]
    current_nav = STARTING_CAPITAL + sum(realized_pnls)
    total_return_pct = (current_nav - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0

    frame = _marked_nav_frame(ledger_path)
    marking = {
        "marked_nav": round(float(frame["marked_nav"].iloc[-1]), 2) if len(frame) else None,
        "stale_marks": int(frame["stale_marks"].sum()) if len(frame) else 0,
        "risk_free_rate": None,
        "risk_free_through": str(risk_free_last_published().date()),
    }

    if n_closed_trades < 2:
        return {
            "n_trades": n_trades,
            "n_closed_trades": n_closed_trades,
            "win_rate": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown": None,
            "current_nav": round(current_nav, 2),
            "total_return_pct": round(total_return_pct, 4),
            "unrealized_pnl": unrealized_pnl,
            "starting_capital": STARTING_CAPITAL,
            "n_backfilled_trades": n_backfilled_trades,
            **marking,
            "insufficient_data": True,
        }

    win_rate = sum(1 for p in realized_pnls if p > 0) / n_closed_trades

    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float | None = None

    if len(frame) >= 2:
        metrics, _, rf = excess_metrics(frame["marked_nav"], STARTING_CAPITAL, n_trades=n_closed_trades)
        sharpe_ratio = metrics.sharpe_ratio
        sortino_ratio = metrics.sortino_ratio
        max_drawdown = metrics.max_drawdown
        marking["risk_free_rate"] = round(float(rf.mean() * 252), 6)

    return {
        "n_trades": n_trades,
        "n_closed_trades": n_closed_trades,
        "win_rate": round(win_rate, 4),
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "current_nav": round(current_nav, 2),
        "total_return_pct": round(total_return_pct, 4),
        "unrealized_pnl": unrealized_pnl,
        "starting_capital": STARTING_CAPITAL,
        "n_backfilled_trades": n_backfilled_trades,
        **marking,
        "insufficient_data": False,
    }


# -- endpoints ----------------------------------------------------------------

@app.get("/api/status")
def get_status() -> dict[str, Any]:
    kill_status = read_kill_switch_status()
    heartbeat_age = read_heartbeat_age_seconds()
    cycle_records = _read_jsonl(CYCLE_LOG_PATH)
    last_cycle = None
    if cycle_records:
        last_cycle = max(cycle_records, key=lambda r: r.get("ts", 0.0))

    return {
        "kill_switch_engaged": kill_status.engaged,
        "kill_switch_reason": kill_status.reason,
        "circuit_breaker_tier": _read_latest_circuit_breaker_tier(),
        "heartbeat_age_seconds": heartbeat_age,
        "heartbeat_stale": heartbeat_age > HEARTBEAT_STALE_SECONDS,
        "last_cycle": last_cycle,
    }


@app.get("/api/positions")
def get_positions() -> list[dict[str, Any]]:
    return _open_positions(LEDGER_FILE)


@app.get("/api/trades")
def get_trades(limit: int = Query(200, ge=1, le=10_000)) -> list[dict[str, Any]]:
    trades = _reconstruct_all_trades(LEDGER_FILE)
    return trades[:limit]


@app.get("/api/equity_curve")
def get_equity_curve() -> dict[str, Any]:
    return _compute_equity_curve(LEDGER_FILE)


@app.get("/api/stats")
def get_stats() -> dict[str, Any]:
    return _compute_stats(LEDGER_FILE)


@app.get("/api/monte_carlo")
def get_monte_carlo() -> dict[str, Any]:
    data = _read_json_file(LIVE_BACKTEST_MONTE_CARLO_PATH)
    if data is None:
        return {"available": False}
    return data


@app.get("/api/live_backtest_metrics")
def get_live_backtest_metrics() -> dict[str, Any]:
    data = _read_json_file(LIVE_BACKTEST_METRICS_PATH)
    if data is None:
        return {"available": False}
    return data


def _registered_at(filename: str) -> str | None:
    if not PREREGISTRATIONS_PATH.exists():
        return None
    for line in PREREGISTRATIONS_PATH.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("file", "").endswith(filename):
            return rec.get("registered_at")
    return None


def _research_tests() -> dict[str, Any]:
    tests: list[dict[str, Any]] = []
    sleeves: list[dict[str, Any]] = []

    pead = _read_json_file(PEAD_2004_2014_RESULTS)
    if pead:
        m = pead.get("model", {})
        c = pead.get("all_events_control", {})
        tests.append({
            "id": "pead_2004_2014",
            "name": "Production PEAD model",
            "question": "Does the unchanged live model earn alpha on a decade it never saw?",
            "window": ["2004-01-01", "2014-12-31"],
            "registered_at": _registered_at("PREREGISTRATION_pead_2004_2014.md"),
            "passed": bool(pead.get("passed")),
            "criterion": "Alpha t ≥ 2, beats all-events control, alpha positive in both halves",
            "result": {"sharpe": m.get("sharpe_ratio"), "cagr": m.get("annualized_return"),
                       "max_dd": m.get("max_drawdown"), "t_stat": m.get("alpha_hac_t"), "t_label": "Alpha t"},
            "benchmark": {"name": "Control", "sharpe": c.get("sharpe_ratio"),
                          "cagr": c.get("annualized_return"), "max_dd": c.get("max_drawdown")},
            "report": "reports/pead_2004_2014/REPORT.md",
        })

    ma_dev, ma = _read_json_file(MULTIASSET_DEV_RESULTS), _read_json_file(MULTIASSET_HOLDOUT_RESULTS)
    if ma:
        p = ma.get("primary", {})
        spy = ma.get("descriptive", {}).get("spy", {})
        tests.append({
            "id": "multiasset_2018_2026",
            "name": "Multi-asset book",
            "question": "Do five literature premia (carry, trend, VIX basis, overnight reversal) combine into an edge?",
            "window": ma.get("window"),
            "registered_at": _registered_at("PREREGISTRATION_holdout.md"),
            "passed": bool(ma.get("passed")),
            "criterion": "Excess-return t ≥ 2 and alpha t ≥ 2 vs SPY",
            "result": {"sharpe": p.get("sharpe"), "cagr": p.get("cagr_total"), "max_dd": p.get("max_dd"),
                       "t_stat": p.get("hac_t"), "t_label": "Excess t"},
            "benchmark": {"name": "SPY", "sharpe": spy.get("sharpe"), "cagr": spy.get("cagr_total"),
                          "max_dd": spy.get("max_dd")},
            "report": "reports/multiasset/REPORT.md",
        })
        dev_sleeves = (ma_dev or {}).get("sleeves", {})
        for name, st in ma.get("sleeves", {}).items():
            sleeves.append({"name": name, "family": "multi-asset",
                            "dev_sharpe": dev_sleeves.get(name, {}).get("raw", {}).get("sharpe"),
                            "holdout_sharpe": st.get("sharpe"), "in_book": name in ma.get("book_sleeves", [])})

    cr_dev, cr = _read_json_file(CRYPTO_DEV_RESULTS), _read_json_file(CRYPTO_HOLDOUT_RESULTS)
    if cr:
        p = cr.get("primary", {})
        btc = cr.get("btc_buy_hold", {})
        tests.append({
            "id": "crypto_2022_2026",
            "name": "Crypto trend (BTC, ETH)",
            "question": "Does long-only multi-horizon trend earn a significant excess return?",
            "window": [p.get("start"), p.get("end")],
            "registered_at": _registered_at("PREREGISTRATION_crypto_holdout.md"),
            "passed": bool(cr.get("passed")),
            "criterion": "Excess-return t ≥ 2",
            "result": {"sharpe": p.get("sharpe"), "cagr": p.get("cagr_total"), "max_dd": p.get("max_dd"),
                       "t_stat": p.get("hac_t"), "t_label": "Excess t"},
            "benchmark": {"name": "BTC", "sharpe": btc.get("sharpe"), "cagr": btc.get("cagr_total"),
                          "max_dd": btc.get("max_dd")},
            "report": "reports/multiasset/crypto/holdout_results.json",
        })
        dev_c = (cr_dev or {}).get("candidates", {})
        for name, st in cr.get("all_candidates", {}).items():
            sleeves.append({"name": name, "family": "crypto", "dev_sharpe": dev_c.get(name, {}).get("sharpe"),
                            "holdout_sharpe": st.get("sharpe"), "in_book": name == cr.get("chosen")})

    return {"available": bool(tests), "target": RESEARCH_TARGET, "tests": tests, "sleeves": sleeves}


@app.get("/api/research_tests")
def get_research_tests() -> dict[str, Any]:
    """Out-of-sample verdicts of every pre-registered research test, read from their
    result files. Read-only; the dashboard never runs research itself."""
    return _research_tests()


@app.get("/api/upcoming_earnings")
def get_upcoming_earnings() -> dict[str, Any]:
    """Scheduled reports for the traded universe, as snapshotted by the
    bot's most recent cycle (the dashboard never queries yfinance itself)."""
    data = _read_json_file(UPCOMING_EARNINGS_PATH)
    if data is None:
        return {"available": False}
    return data


@app.get("/api/alerts")
def get_alerts(limit: int = Query(50, ge=1, le=10_000)) -> list[dict[str, Any]]:
    return _tail_jsonl_newest_first(ALERTS_LOG_FILE, limit)


@app.get("/api/cycle_log")
def get_cycle_log(limit: int = Query(50, ge=1, le=10_000)) -> list[dict[str, Any]]:
    return _tail_jsonl_newest_first(CYCLE_LOG_PATH, limit)


@app.get("/api/signals")
def get_signals(limit: int = Query(200, ge=1, le=5_000)) -> list[dict[str, Any]]:
    """Every earnings event the bot actually scored and gated, newest first,
    flattened out of the live cycle log and the backfill cycle log. This is
    the "why" behind the trade log: SUE, calibrated probability, the Kelly
    size the gate allowed, and the reason anything was skipped or blocked."""
    rows: list[dict[str, Any]] = []
    for path, backfill in ((CYCLE_LOG_PATH, False), (BACKFILL_CYCLE_LOG_PATH, True)):
        for record in _read_jsonl(path):
            for entry in record.get("entries") or []:
                rows.append({
                    "ticker": entry.get("ticker"),
                    "as_of_date": record.get("as_of_date"),
                    "ts": record.get("ts", 0.0),
                    "earnings_date": entry.get("earnings_date"),
                    "sue": entry.get("sue"),
                    "calibrated_proba": entry.get("calibrated_proba"),
                    "direction": entry.get("direction"),
                    "allowed": entry.get("allowed"),
                    "reason": entry.get("reason"),
                    "detail": entry.get("detail"),
                    "size_fraction": entry.get("size_fraction"),
                    "backfill": backfill,
                })
    rows.sort(key=lambda r: (r.get("ts", 0.0), r.get("ticker") or ""), reverse=True)
    return rows[:limit]


@app.get("/api/event_feed")
def get_event_feed(limit: int = Query(100, ge=1, le=2_000)) -> list[dict[str, Any]]:
    """Merged, chronological (newest-first) event feed for the LOOP EVENTS
    WIRE panel: real alerts (bot/state/bot_alerts.jsonl) + real cycle runs
    flattened into one line per exit/entry/error (bot/state/cycle_log.jsonl).
    Reuses _tail_jsonl_newest_first on the same real path constants every
    other endpoint in this file already uses -- no new file-reading logic."""
    alerts = _tail_jsonl_newest_first(ALERTS_LOG_FILE, limit)
    cycles = _tail_jsonl_newest_first(CYCLE_LOG_PATH, limit)

    events: list[dict[str, Any]] = [
        {"ts": a.get("ts", 0.0), "source": "alert", "kind": a.get("kind"), "summary": a.get("message", ""),
         "backfill": bool(a.get("backfill"))}
        for a in alerts
    ]
    for record in cycles:
        events.extend(_cycle_log_record_to_wire_events(record))

    events.sort(key=lambda e: e.get("ts", 0.0), reverse=True)
    return events[:limit]


# -- bot control (the only write surface in this app -- see module docstring) -

@app.get("/api/launchd_status")
def get_launchd_status() -> dict[str, Any]:
    _paper_mode_or_500()
    return {"mode": "PAPER_TRADE", "mode_verified": True, **get_operation_status()}


@app.post("/api/control/start")
def post_control_start(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    _paper_mode_or_500()
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail='body must include {"confirm": true}')
    return {"action": "start", "jobs": start_bot_operation(), "status": get_operation_status()}


@app.post("/api/control/stop")
def post_control_stop(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    _paper_mode_or_500()
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail='body must include {"confirm": true}')
    return {"action": "stop", "jobs": stop_bot_operation(), "status": get_operation_status()}


@app.get("/", response_model=None)
def get_index() -> FileResponse | JSONResponse:
    if INDEX_HTML_PATH.exists():
        return FileResponse(INDEX_HTML_PATH)
    return JSONResponse(
        {"detail": "index.html not found in live_backtest/dashboard/ yet"},
        status_code=404,
    )


# Fallback static mount for any other same-directory asset the frontend
# references relatively (e.g. a separate style.css / script.js), registered
# LAST so it never shadows the /api/* routes or the explicit "/" handler
# above (Starlette matches routes in registration order). DASHBOARD_DIR
# always exists (this file lives in it), so the mount itself is safe even
# before index.html exists.
app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard-static")


if __name__ == "__main__":
    import uvicorn

    # 127.0.0.1 ONLY -- see module docstring. Never bind 0.0.0.0 here.
    uvicorn.run(app, host="127.0.0.1", port=8420)
