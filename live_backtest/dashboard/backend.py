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

from backtest.metrics import compute_metrics
from bot.alerting import ALERTS_LOG_FILE
from bot.execution import LEDGER_FILE, PaperExecutionClient, assert_paper_only_mode
from bot.heartbeat import read_heartbeat_age_seconds
from bot.kill_switch import read_kill_switch_status
from bot.launchd_control import get_operation_status, start_bot_operation, stop_bot_operation
from bot.position_manager import trading_days_elapsed

# -- real paths -------------------------------------------------------------
# LEDGER_FILE / ALERTS_LOG_FILE are imported directly from the bot's own
# modules (bot/execution.py, bot/alerting.py) so this dashboard can never
# drift out of sync with where the real bot actually writes those files.
STATE_DIR = LEDGER_FILE.parent  # bot/state/
CYCLE_LOG_PATH = STATE_DIR / "cycle_log.jsonl"  # mirrors bot/run_cycle.py::CYCLE_LOG_FILE

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
CIRCUIT_BREAKER_CSV = REPORTS_DIR / "circuit_breaker_daily_production.csv"
LIVE_BACKTEST_METRICS_PATH = REPORTS_DIR / "pead_live_backtest_metrics.json"
LIVE_BACKTEST_MONTE_CARLO_PATH = REPORTS_DIR / "pead_live_backtest_monte_carlo.json"

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
                "open": True,
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
                    "open": True,
                    "_sort_ts": record.get("ts", 0.0),
                }
                trades.append(trade)
            trade["exit_date"] = record.get("exit_date")
            trade["exit_price"] = record.get("exit_price")
            trade["realized_pnl"] = record.get("realized_pnl")
            trade["open"] = False
            trade["_sort_ts"] = record.get("ts", trade["_sort_ts"])

    trades.sort(key=lambda t: t.get("_sort_ts", 0.0), reverse=True)
    for t in trades:
        t.pop("_sort_ts", None)
    return trades


def _compute_equity_curve(ledger_path: Path) -> dict:
    """Real cumulative NAV over time: replay the ledger's close events
    chronologically by exit_date, starting from STARTING_CAPITAL. One point
    per close event (not collapsed by date), matching each realized P&L
    event as its own step, mirroring the step-indexed style of
    reports/pead_live_backtest_monte_carlo.json's real_equity_curve_by_step."""
    records = _read_jsonl(ledger_path)
    closes = [r for r in records if r.get("event") == "close"]
    closes.sort(key=lambda r: (r.get("exit_date") or "", r.get("ts", 0.0)))

    dates: list[str] = []
    nav_values: list[float] = []
    running_nav = STARTING_CAPITAL
    for r in closes:
        running_nav += float(r.get("realized_pnl", 0.0) or 0.0)
        dates.append(r.get("exit_date"))
        nav_values.append(round(running_nav, 6))

    return {"dates": dates, "nav": nav_values}


def _compute_stats(ledger_path: Path) -> dict:
    """Stats from the REAL production ledger's realized trades. Sharpe /
    Sortino / max drawdown are computed by reusing
    backtest/metrics.py::compute_metrics (the same function -- and the same
    TRADING_DAYS_PER_YEAR=252 annualization -- used everywhere else in this
    repo) over a business-day NAV series built by forward-filling the
    ledger's realized P&L between close events. Forward-filling (rather than
    only using the trade dates themselves) matches the real NAV mechanics
    documented in bot/execution.py::PaperExecutionClient.nav(): NAV is
    cash-basis and only changes on a close event, so every business day with
    no close in between is correctly a zero-return day, not a missing one.

    Returns insufficient_data=True (with null float fields, not fabricated
    numbers) when there are fewer than 2 closed trades -- not enough to
    compute a meaningful return series."""
    records = _read_jsonl(ledger_path)
    n_trades = sum(1 for r in records if r.get("event") == "open")
    closes = [r for r in records if r.get("event") == "close"]
    n_closed_trades = len(closes)

    realized_pnls = [float(r.get("realized_pnl", 0.0) or 0.0) for r in closes]
    current_nav = STARTING_CAPITAL + sum(realized_pnls)
    total_return_pct = (current_nav - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0

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
            "insufficient_data": True,
        }

    win_rate = sum(1 for p in realized_pnls if p > 0) / n_closed_trades

    pnl_by_date: dict[str, float] = {}
    for r in closes:
        d = r.get("exit_date")
        if not d:
            continue
        pnl_by_date[d] = pnl_by_date.get(d, 0.0) + float(r.get("realized_pnl", 0.0) or 0.0)

    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float | None = None

    if pnl_by_date:
        cum = 0.0
        cum_by_date: dict[str, float] = {}
        for d in sorted(pnl_by_date.keys()):
            cum += pnl_by_date[d]
            cum_by_date[d] = cum

        s = pd.Series(cum_by_date)
        s.index = pd.to_datetime(s.index)

        first_date = s.index.min()
        today_ts = pd.Timestamp(date.today())
        last_date = max(s.index.max(), today_ts)

        bdays = pd.bdate_range(first_date, last_date)
        nav_series = (STARTING_CAPITAL + s).reindex(bdays).ffill()
        nav_series = nav_series.fillna(STARTING_CAPITAL)
        daily_returns = nav_series.pct_change().dropna()

        metrics = compute_metrics(daily_returns, n_trades=n_closed_trades)
        sharpe_ratio = metrics.sharpe_ratio
        sortino_ratio = metrics.sortino_ratio
        max_drawdown = metrics.max_drawdown

    return {
        "n_trades": n_trades,
        "n_closed_trades": n_closed_trades,
        "win_rate": round(win_rate, 4),
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "current_nav": round(current_nav, 2),
        "total_return_pct": round(total_return_pct, 4),
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
    client = PaperExecutionClient.from_ledger(starting_capital=STARTING_CAPITAL, ledger_path=LEDGER_FILE)
    today_str = date.today().isoformat()

    out: list[dict[str, Any]] = []
    for position in client.positions.values():
        if not position.open:
            continue
        days_held = trading_days_elapsed(position.entry_date, today_str) if position.entry_date else 0
        out.append({
            "ticker": position.ticker,
            "direction": position.direction,
            "entry_price": position.entry_price,
            "entry_date": position.entry_date,
            "size_fraction": position.size_fraction,
            "notional": position.notional,
            "days_held": days_held,
        })

    out.sort(key=lambda p: p.get("entry_date") or "", reverse=True)
    return out


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


@app.get("/api/alerts")
def get_alerts(limit: int = Query(50, ge=1, le=10_000)) -> list[dict[str, Any]]:
    return _tail_jsonl_newest_first(ALERTS_LOG_FILE, limit)


@app.get("/api/cycle_log")
def get_cycle_log(limit: int = Query(50, ge=1, le=10_000)) -> list[dict[str, Any]]:
    return _tail_jsonl_newest_first(CYCLE_LOG_PATH, limit)


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
        {"ts": a.get("ts", 0.0), "source": "alert", "kind": a.get("kind"), "summary": a.get("message", "")}
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
