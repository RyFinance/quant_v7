"""Tests for live_backtest/dashboard/backend.py -- the read-only monitoring
dashboard's FastAPI app.

Two kinds of coverage here:

1. Contract/shape tests against the REAL state files currently on disk
   (bot/state/paper_ledger.jsonl, bot_alerts.jsonl, cycle_log.jsonl,
   reports/circuit_breaker_daily_production.csv, reports/pead_live_*.json).
   These tolerate whatever real content currently exists -- including an
   empty or missing ledger -- rather than assuming a specific trade count,
   since this is a real, currently-running paper bot whose state changes
   over time.
2. Behavioral tests against synthetic ledgers/alerts written to tmp_path and
   swapped in via monkeypatch.setattr on the backend module's path
   constants (the same pattern tests/test_bot_execution.py already uses for
   bot.kill_switch.KILL_SWITCH_FILE) -- these exercise code paths (multiple
   trades, reopened tickers, closed-trade stats, staleness) that the real
   state files may not currently contain.

No test ever writes to a REAL bot/state/ file or calls anything on
PaperExecutionClient's write path (place_order/close_position). The FastAPI
TestClient drives the app in-process (httpx-based, synchronous) -- no
uvicorn server is started.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import live_backtest.dashboard.backend as backend

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    return TestClient(backend.app)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# Contract tests against REAL repo files (tolerant of empty/missing state)
# ---------------------------------------------------------------------------

def test_real_paths_point_inside_repo():
    # Sanity check the module resolved the real production paths, not some
    # accidental other location -- every path must live under this repo.
    assert backend.LEDGER_FILE == REPO_ROOT / "bot" / "state" / "paper_ledger.jsonl"
    assert backend.ALERTS_LOG_FILE == REPO_ROOT / "bot" / "state" / "bot_alerts.jsonl"
    assert backend.CYCLE_LOG_PATH == REPO_ROOT / "bot" / "state" / "cycle_log.jsonl"
    assert backend.CIRCUIT_BREAKER_CSV == REPO_ROOT / "reports" / "circuit_breaker_daily_production.csv"
    assert backend.LIVE_BACKTEST_METRICS_PATH == REPO_ROOT / "reports" / "pead_live_backtest_metrics.json"
    assert backend.LIVE_BACKTEST_MONTE_CARLO_PATH == REPO_ROOT / "reports" / "pead_live_backtest_monte_carlo.json"


def test_status_endpoint_real(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["kill_switch_engaged"], bool)
    assert body["kill_switch_reason"] is None or isinstance(body["kill_switch_reason"], str)
    assert isinstance(body["circuit_breaker_tier"], str) and body["circuit_breaker_tier"] != ""
    assert isinstance(body["heartbeat_age_seconds"], (int, float))
    assert isinstance(body["heartbeat_stale"], bool)
    # heartbeat_stale must be exactly the > 26h rule against the age we were given
    assert body["heartbeat_stale"] == (body["heartbeat_age_seconds"] > 26 * 3600)
    assert body["last_cycle"] is None or isinstance(body["last_cycle"], dict)


def test_status_circuit_breaker_tier_matches_csv_last_row(client):
    r = client.get("/api/status")
    body = r.json()
    if not backend.CIRCUIT_BREAKER_CSV.exists():
        assert body["circuit_breaker_tier"] == "unknown"
        return
    with open(backend.CIRCUIT_BREAKER_CSV, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    last_row = lines[-1].split(",")
    header = lines[0].split(",")
    tier_idx = header.index("tier")
    assert body["circuit_breaker_tier"] == last_row[tier_idx]


def test_positions_endpoint_real_shape(client):
    r = client.get("/api/positions")
    assert r.status_code == 200
    positions = r.json()
    assert isinstance(positions, list)
    for p in positions:
        assert set(p.keys()) == {
            "ticker", "direction", "entry_price", "entry_date",
            "size_fraction", "notional", "days_held",
            "last_close", "last_close_date", "unrealized_pnl", "backfill",
        }
        assert p["direction"] in ("long", "short")
        assert isinstance(p["days_held"], int)
        assert p["days_held"] >= 0


def test_trades_endpoint_real_shape_and_limit(client):
    r = client.get("/api/trades?limit=5")
    assert r.status_code == 200
    trades = r.json()
    assert isinstance(trades, list)
    assert len(trades) <= 5
    for t in trades:
        assert set(t.keys()) == {
            "ticker", "direction", "entry_date", "entry_price",
            "exit_date", "exit_price", "size_fraction", "notional",
            "realized_pnl", "gross_pnl", "cost", "open", "backfill",
        }
        assert isinstance(t["open"], bool)
        if not t["open"]:
            assert t["exit_date"] is not None
            assert t["realized_pnl"] is not None


def test_equity_curve_endpoint_real_shape(client):
    r = client.get("/api/equity_curve")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"dates", "nav", "marked"}
    assert isinstance(body["dates"], list)
    assert isinstance(body["nav"], list)
    assert len(body["dates"]) == len(body["nav"])
    # dates must be non-decreasing (chronological replay)
    assert body["dates"] == sorted(body["dates"])
    marked = body["marked"]
    assert set(marked.keys()) == {"dates", "nav", "cash_basis_nav"}
    assert len(marked["dates"]) == len(marked["nav"]) == len(marked["cash_basis_nav"])
    assert marked["dates"] == sorted(set(marked["dates"]))


def test_stats_endpoint_real_shape(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "n_trades", "n_closed_trades", "win_rate", "sharpe_ratio",
        "sortino_ratio", "max_drawdown", "current_nav", "total_return_pct",
        "unrealized_pnl", "n_backfilled_trades", "starting_capital", "insufficient_data",
        "marked_nav", "stale_marks", "risk_free_rate", "risk_free_through",
    }
    assert isinstance(body["n_trades"], int)
    assert isinstance(body["n_closed_trades"], int)
    assert body["n_closed_trades"] <= body["n_trades"]
    assert isinstance(body["current_nav"], (int, float))

    if body["insufficient_data"]:
        # Tolerates the real bot currently having < 2 closed trades: no
        # fabricated float stats, nulls only.
        assert body["win_rate"] is None
        assert body["sharpe_ratio"] is None
        assert body["sortino_ratio"] is None
        assert body["max_drawdown"] is None
    else:
        assert 0.0 <= body["win_rate"] <= 1.0
        assert isinstance(body["sharpe_ratio"], (int, float))
        assert isinstance(body["sortino_ratio"], (int, float))
        assert isinstance(body["max_drawdown"], (int, float))


def test_monte_carlo_endpoint_real(client):
    r = client.get("/api/monte_carlo")
    assert r.status_code == 200
    body = r.json()
    if backend.LIVE_BACKTEST_MONTE_CARLO_PATH.exists():
        assert body.get("available") is not False
        assert "fan_chart_nav_by_step" in body
        assert "real_equity_curve_by_step" in body
    else:
        assert body == {"available": False}


def test_live_backtest_metrics_endpoint_real(client):
    r = client.get("/api/live_backtest_metrics")
    assert r.status_code == 200
    body = r.json()
    if backend.LIVE_BACKTEST_METRICS_PATH.exists():
        assert body.get("available") is not False
        assert "n_trades" in body
    else:
        assert body == {"available": False}


def test_alerts_endpoint_real_newest_first(client):
    r = client.get("/api/alerts?limit=10")
    assert r.status_code == 200
    alerts = r.json()
    assert isinstance(alerts, list)
    assert len(alerts) <= 10
    timestamps = [a["ts"] for a in alerts]
    assert timestamps == sorted(timestamps, reverse=True)
    for a in alerts:
        assert "ts" in a and "kind" in a and "message" in a


def test_cycle_log_endpoint_real_newest_first(client):
    r = client.get("/api/cycle_log?limit=10")
    assert r.status_code == 200
    records = r.json()
    assert isinstance(records, list)
    assert len(records) <= 10
    timestamps = [c["ts"] for c in records]
    assert timestamps == sorted(timestamps, reverse=True)


def test_index_route_serves_something(client):
    r = client.get("/")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert "text/html" in r.headers.get("content-type", "")


def test_cors_configured_for_localhost_only():
    # No live-request assertion needed (TestClient doesn't enforce CORS
    # itself) -- just confirm the app was configured with the intended
    # origin allowlist and GET-only methods, not a wildcard.
    cors_middlewares = [
        m for m in backend.app.user_middleware
        if m.cls.__name__ == "CORSMiddleware"
    ]
    assert len(cors_middlewares) == 1
    kwargs = cors_middlewares[0].kwargs
    assert set(kwargs["allow_origins"]) == {"http://127.0.0.1:8420", "http://localhost:8420"}
    assert "*" not in kwargs["allow_origins"]


# ---------------------------------------------------------------------------
# Behavioral tests against synthetic ledgers (isolated via monkeypatch)
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_ledger(tmp_path, monkeypatch):
    ledger_path = tmp_path / "paper_ledger.jsonl"
    monkeypatch.setattr(backend, "LEDGER_FILE", ledger_path)
    return ledger_path


@pytest.fixture
def isolated_alerts(tmp_path, monkeypatch):
    alerts_path = tmp_path / "bot_alerts.jsonl"
    monkeypatch.setattr(backend, "ALERTS_LOG_FILE", alerts_path)
    return alerts_path


@pytest.fixture
def isolated_cycle_log(tmp_path, monkeypatch):
    cycle_log_path = tmp_path / "cycle_log.jsonl"
    monkeypatch.setattr(backend, "CYCLE_LOG_PATH", cycle_log_path)
    return cycle_log_path


def test_missing_ledger_file_yields_empty_not_error(isolated_ledger, client):
    assert not isolated_ledger.exists()
    assert client.get("/api/positions").json() == []
    assert client.get("/api/trades").json() == []
    assert client.get("/api/equity_curve").json() == {"dates": [], "nav": [],
                                                       "marked": {"dates": [], "nav": [], "cash_basis_nav": []}}
    stats = client.get("/api/stats").json()
    assert stats["n_trades"] == 0
    assert stats["n_closed_trades"] == 0
    assert stats["insufficient_data"] is True
    assert stats["current_nav"] == 100_000.0
    assert stats["total_return_pct"] == 0.0


def test_missing_alerts_and_cycle_log_yield_empty(isolated_alerts, isolated_cycle_log, client):
    assert client.get("/api/alerts").json() == []
    assert client.get("/api/cycle_log").json() == []
    assert client.get("/api/status").json()["last_cycle"] is None


def test_open_position_reconstructed_via_paper_execution_client(isolated_ledger, client):
    _write_jsonl(isolated_ledger, [
        {
            "event": "open", "entry_date": "2026-07-01", "ticker": "AAPL",
            "direction": "long", "fill_price": 200.0, "size_fraction": 0.05,
            "notional": 5000.0, "ts": 1000.0, "mode": "paper",
        },
    ])
    r = client.get("/api/positions")
    assert r.status_code == 200
    positions = r.json()
    assert len(positions) == 1
    p = positions[0]
    assert p["ticker"] == "AAPL"
    assert p["direction"] == "long"
    assert p["entry_price"] == 200.0
    assert p["entry_date"] == "2026-07-01"
    assert p["size_fraction"] == 0.05
    assert p["notional"] == 5000.0
    assert p["days_held"] >= 0

    trades = client.get("/api/trades").json()
    assert len(trades) == 1
    assert trades[0]["open"] is True
    assert trades[0]["exit_date"] is None
    assert trades[0]["realized_pnl"] is None


def test_reopened_ticker_preserves_full_trade_history(isolated_ledger, client):
    # A ticker that opens, closes, then re-opens and closes again must
    # surface as TWO distinct trades in /api/trades, not be collapsed into
    # one -- this is exactly the gap between from_ledger's per-ticker dict
    # (used for /api/positions) and this dashboard's full trade log.
    _write_jsonl(isolated_ledger, [
        {"event": "open", "entry_date": "2026-06-01", "ticker": "AAPL", "direction": "long",
         "fill_price": 100.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 1000.0, "mode": "paper"},
        {"event": "close", "ticker": "AAPL", "direction": "long", "entry_price": 100.0,
         "exit_price": 110.0, "notional": 5000.0, "realized_pnl": 500.0,
         "reason": "holding_period_exit", "exit_date": "2026-06-15", "ts": 2000.0},
        {"event": "open", "entry_date": "2026-06-16", "ticker": "AAPL", "direction": "short",
         "fill_price": 90.0, "size_fraction": 0.03, "notional": 3000.0, "ts": 3000.0, "mode": "paper"},
        {"event": "close", "ticker": "AAPL", "direction": "short", "entry_price": 90.0,
         "exit_price": 95.0, "notional": 3000.0, "realized_pnl": -150.0,
         "reason": "holding_period_exit", "exit_date": "2026-06-30", "ts": 4000.0},
    ])
    trades = client.get("/api/trades").json()
    assert len(trades) == 2
    # newest first -> the short (closed later, ts=4000) comes before the long
    assert trades[0]["direction"] == "short"
    assert trades[0]["realized_pnl"] == -150.0
    assert trades[1]["direction"] == "long"
    assert trades[1]["realized_pnl"] == 500.0

    # No open position remains for AAPL (both trades closed).
    assert client.get("/api/positions").json() == []

    curve = client.get("/api/equity_curve").json()
    assert curve["dates"] == ["2026-06-01", "2026-06-15", "2026-06-30"]  # anchored at the first entry
    assert curve["nav"] == pytest.approx([100_000.0, 100_500.0, 100_350.0])


def test_trades_surface_the_charged_trading_cost(isolated_ledger, client):
    _write_jsonl(isolated_ledger, [
        {"event": "open", "entry_date": "2026-09-01", "ticker": "AAPL", "direction": "long",
         "fill_price": 100.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 1.0, "mode": "paper"},
        {"event": "close", "ticker": "AAPL", "direction": "long", "entry_price": 100.0, "exit_price": 110.0,
         "notional": 5000.0, "realized_pnl": 494.75, "gross_pnl": 500.0, "cost": 5.25,
         "cost_bps_round_trip": 10.0, "reason": "holding_period_exit", "exit_date": "2026-09-29", "ts": 2.0},
    ])
    [trade] = client.get("/api/trades").json()
    assert trade["realized_pnl"] == pytest.approx(494.75)
    assert trade["gross_pnl"] == pytest.approx(500.0)
    assert trade["cost"] == pytest.approx(5.25)


def test_equity_curve_has_one_point_per_exit_date(isolated_ledger, client):
    _write_jsonl(isolated_ledger, [
        {"event": "open", "entry_date": "2026-07-29", "ticker": "VRT", "direction": "long",
         "fill_price": 100.0, "size_fraction": 0.1, "notional": 10000.0, "ts": 1.0, "mode": "paper"},
        {"event": "open", "entry_date": "2026-07-29", "ticker": "APH", "direction": "long",
         "fill_price": 50.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 2.0, "mode": "paper"},
        {"event": "close", "ticker": "VRT", "direction": "long", "entry_price": 100.0, "exit_price": 110.0,
         "notional": 10000.0, "realized_pnl": 1000.0, "reason": "holding_period_exit", "exit_date": "2026-08-26", "ts": 3.0},
        {"event": "close", "ticker": "APH", "direction": "long", "entry_price": 50.0, "exit_price": 55.0,
         "notional": 5000.0, "realized_pnl": 500.0, "reason": "holding_period_exit", "exit_date": "2026-08-26", "ts": 4.0},
    ])
    curve = client.get("/api/equity_curve").json()
    assert {k: curve[k] for k in ("dates", "nav")} == {"dates": ["2026-07-29", "2026-08-26"], "nav": [100_000.0, 101_500.0]}


def test_open_positions_are_marked_at_latest_cached_close(isolated_ledger, tmp_path, monkeypatch, client):
    pd.DataFrame({"timestamp": pd.to_datetime(["2026-09-15", "2026-09-16"]), "close": [95.0, 90.0]}) \
        .to_parquet(tmp_path / "XYZ.parquet", index=False)
    monkeypatch.setattr(backend, "PRICE_CACHE_DIR", tmp_path)
    _write_jsonl(isolated_ledger, [
        {"event": "open", "entry_date": "2026-09-01", "ticker": "XYZ", "direction": "short",
         "fill_price": 100.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 1000.0, "mode": "paper",
         "backfill": True},
    ])
    [p] = client.get("/api/positions").json()
    assert p["last_close"] == 90.0 and p["last_close_date"] == "2026-09-16"
    assert p["unrealized_pnl"] == pytest.approx(500.0)  # short from 100 to 90 on $5,000
    assert p["backfill"] is True

    stats = client.get("/api/stats").json()
    assert stats["unrealized_pnl"] == pytest.approx(500.0)
    assert stats["n_backfilled_trades"] == 1
    assert client.get("/api/trades").json()[0]["backfill"] is True


def test_stats_with_two_closed_trades_is_not_insufficient(isolated_ledger, client):
    _write_jsonl(isolated_ledger, [
        {"event": "open", "entry_date": "2026-06-01", "ticker": "AAPL", "direction": "long",
         "fill_price": 100.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 1000.0, "mode": "paper"},
        {"event": "close", "ticker": "AAPL", "direction": "long", "entry_price": 100.0,
         "exit_price": 110.0, "notional": 5000.0, "realized_pnl": 500.0,
         "reason": "holding_period_exit", "exit_date": "2026-06-15", "ts": 2000.0},
        {"event": "open", "entry_date": "2026-06-16", "ticker": "MSFT", "direction": "long",
         "fill_price": 300.0, "size_fraction": 0.03, "notional": 3000.0, "ts": 3000.0, "mode": "paper"},
        {"event": "close", "ticker": "MSFT", "direction": "long", "entry_price": 300.0,
         "exit_price": 290.0, "notional": 3000.0, "realized_pnl": -100.0,
         "reason": "holding_period_exit", "exit_date": "2026-06-20", "ts": 4000.0},
    ])
    stats = client.get("/api/stats").json()
    assert stats["n_trades"] == 2
    assert stats["n_closed_trades"] == 2
    assert stats["insufficient_data"] is False
    assert stats["win_rate"] == 0.5
    assert stats["current_nav"] == pytest.approx(100_400.0)
    assert stats["total_return_pct"] == pytest.approx(0.4)
    # Sharpe/Sortino/max_drawdown must be real finite numbers, not NaN/inf,
    # and not fabricated placeholders.
    for key in ("sharpe_ratio", "sortino_ratio", "max_drawdown"):
        val = stats[key]
        assert isinstance(val, (int, float))
        assert not math.isnan(val)
        assert not math.isinf(val)


def test_status_heartbeat_stale_true_when_old(tmp_path, monkeypatch, client):
    stale_file = tmp_path / "heartbeat.txt"
    stale_file.write_text("1000.0")  # epoch 1970 -- guaranteed far in the past
    monkeypatch.setattr(backend, "read_heartbeat_age_seconds", lambda: 30 * 3600.0)
    body = client.get("/api/status").json()
    assert body["heartbeat_age_seconds"] == 30 * 3600.0
    assert body["heartbeat_stale"] is True


def test_status_kill_switch_engaged_reflected(monkeypatch, client):
    from bot.kill_switch import KillSwitchStatus

    def fake_read_kill_switch_status():
        return KillSwitchStatus(engaged=True, reason="test drawdown breach", engaged_at=12345.0)

    monkeypatch.setattr(backend, "read_kill_switch_status", fake_read_kill_switch_status)
    body = client.get("/api/status").json()
    assert body["kill_switch_engaged"] is True
    assert body["kill_switch_reason"] == "test drawdown breach"


def test_circuit_breaker_tier_reads_last_row_of_synthetic_csv(tmp_path, monkeypatch, client):
    csv_path = tmp_path / "circuit_breaker_daily_production.csv"
    csv_path.write_text(
        "date,tier,fired_categories,magnitude_fired,structural_fired,index_return,mean_abs_corr_raw\n"
        "2026-08-17,armed,,False,False,0.01,0.27\n"
        "2026-08-18,halt_new_entries,magnitude,True,False,-0.05,0.31\n"
    )
    monkeypatch.setattr(backend, "CIRCUIT_BREAKER_CSV", csv_path)
    body = client.get("/api/status").json()
    assert body["circuit_breaker_tier"] == "halt_new_entries"


def test_circuit_breaker_tier_missing_csv_is_unknown_not_error(tmp_path, monkeypatch, client):
    monkeypatch.setattr(backend, "CIRCUIT_BREAKER_CSV", tmp_path / "does_not_exist.csv")
    body = client.get("/api/status").json()
    assert body["circuit_breaker_tier"] == "unknown"


def test_monte_carlo_missing_file_returns_available_false(tmp_path, monkeypatch, client):
    monkeypatch.setattr(backend, "LIVE_BACKTEST_MONTE_CARLO_PATH", tmp_path / "nope.json")
    assert client.get("/api/monte_carlo").json() == {"available": False}


def test_live_backtest_metrics_missing_file_returns_available_false(tmp_path, monkeypatch, client):
    monkeypatch.setattr(backend, "LIVE_BACKTEST_METRICS_PATH", tmp_path / "nope.json")
    assert client.get("/api/live_backtest_metrics").json() == {"available": False}


def test_signals_endpoint_flattens_both_cycle_logs(tmp_path, monkeypatch, client):
    live = tmp_path / "cycle_log.jsonl"
    backfill = tmp_path / "backfill_cycle_log.jsonl"
    _write_jsonl(live, [{
        "ts": 200.0, "as_of_date": "2026-09-16", "entries": [
            {"ticker": "COST", "sue": 1.2, "calibrated_proba": 0.42, "direction": "long", "allowed": False,
             "reason": "no_conviction", "detail": "Kelly size <= 0", "size_fraction": 0.0,
             "earnings_date": "2026-09-24T16:00:00"},
        ],
    }])
    _write_jsonl(backfill, [{
        "ts": 100.0, "as_of_date": "2026-07-29", "entries": [
            {"ticker": "VRT", "sue": 0.88, "calibrated_proba": 0.857, "direction": "long", "allowed": True,
             "reason": "executed", "detail": "approved", "size_fraction": 0.1,
             "earnings_date": "2026-07-28T16:05:00"},
        ],
    }])
    monkeypatch.setattr(backend, "CYCLE_LOG_PATH", live)
    monkeypatch.setattr(backend, "BACKFILL_CYCLE_LOG_PATH", backfill)

    signals = client.get("/api/signals").json()
    assert [s["ticker"] for s in signals] == ["COST", "VRT"]  # newest first
    assert signals[0]["backfill"] is False and signals[1]["backfill"] is True
    assert signals[1]["allowed"] is True and signals[1]["size_fraction"] == 0.1
    assert client.get("/api/signals?limit=1").json() == signals[:1]


def test_signals_endpoint_tolerates_missing_logs(tmp_path, monkeypatch, client):
    monkeypatch.setattr(backend, "CYCLE_LOG_PATH", tmp_path / "nope.jsonl")
    monkeypatch.setattr(backend, "BACKFILL_CYCLE_LOG_PATH", tmp_path / "also_nope.jsonl")
    assert client.get("/api/signals").json() == []


def test_upcoming_earnings_missing_file_returns_available_false(tmp_path, monkeypatch, client):
    monkeypatch.setattr(backend, "UPCOMING_EARNINGS_PATH", tmp_path / "nope.json")
    assert client.get("/api/upcoming_earnings").json() == {"available": False}


def test_upcoming_earnings_passes_snapshot_through(tmp_path, monkeypatch, client):
    snapshot = {"ts": 1.0, "as_of_date": "2026-09-17", "horizon_days": 60, "events": [
        {"ticker": "JPM", "earnings_date": "2026-10-13T08:00:00", "timing": "before_close", "eps_estimate": 5.89, "days_until": 26},
    ]}
    path = tmp_path / "upcoming.json"
    path.write_text(json.dumps(snapshot))
    monkeypatch.setattr(backend, "UPCOMING_EARNINGS_PATH", path)
    assert client.get("/api/upcoming_earnings").json() == snapshot


def test_live_backtest_metrics_passes_through_generically(tmp_path, monkeypatch, client):
    # Schema may evolve -- confirm this is a generic passthrough (no
    # hardcoded key allowlist dropping unknown fields).
    payload = {"n_trades": 42, "totally_new_future_field": "abc", "sharpe_ratio": 1.23}
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(backend, "LIVE_BACKTEST_METRICS_PATH", path)
    assert client.get("/api/live_backtest_metrics").json() == payload


def test_alerts_and_cycle_log_respect_limit(isolated_alerts, isolated_cycle_log, client):
    _write_jsonl(isolated_alerts, [
        {"ts": float(i), "kind": "position_opened", "message": f"m{i}"} for i in range(20)
    ])
    _write_jsonl(isolated_cycle_log, [
        {"ts": float(i), "as_of_date": "2026-06-01", "kill_switch_engaged": False,
         "breaker_tier": "armed", "nav_before": 100000.0, "nav_after": 100000.0,
         "exits": [], "entries_considered": 0, "entries": [], "errors": []}
        for i in range(20)
    ])
    alerts = client.get("/api/alerts?limit=3").json()
    assert len(alerts) == 3
    assert [a["ts"] for a in alerts] == [19.0, 18.0, 17.0]

    cycles = client.get("/api/cycle_log?limit=5").json()
    assert len(cycles) == 5
    assert [c["ts"] for c in cycles] == [19.0, 18.0, 17.0, 16.0, 15.0]


def test_read_only_never_writes_paper_execution_write_paths(isolated_ledger):
    # Static/behavioral guard: the backend module must never CALL
    # PaperExecutionClient.place_order or .close_position -- those are the
    # only write paths onto the ledger (mentioning them in prose/comments,
    # e.g. explaining why they're avoided, is fine; an actual call syntax
    # is not). This dashboard must only ever call
    # PaperExecutionClient.from_ledger (a read/replay).
    import inspect

    source = inspect.getsource(backend)
    assert "place_order(" not in source
    assert "close_position(" not in source
    assert ".from_ledger(" in source


# ---------------------------------------------------------------------------
# Bot control: /api/launchd_status, /api/control/start, /api/control/stop,
# /api/event_feed -- the ONE deliberate write surface in this app. Every
# test in this section mocks backend.start_bot_operation / stop_bot_operation
# / get_operation_status (imported names on the backend module, same pattern
# already used above for read_kill_switch_status/read_heartbeat_age_seconds)
# so the REAL launchctl binary is never invoked by this test file -- proven
# by real launchctl `runs=` counters being checked unchanged before/after the
# full suite as part of this feature's separate real-verification pass.
# ---------------------------------------------------------------------------

def test_control_endpoints_are_the_only_write_surface():
    import inspect

    source = inspect.getsource(backend)
    assert "place_order(" not in source
    assert "close_position(" not in source
    assert "shell=True" not in source
    # backend.py must only ever reach launchctl through bot.launchd_control's
    # functions -- never call subprocess itself. This keeps the narrow write
    # surface in exactly one place.
    assert "import subprocess" not in source
    assert "from subprocess" not in source


def test_cors_allows_post_but_still_no_wildcard():
    cors_middlewares = [m for m in backend.app.user_middleware if m.cls.__name__ == "CORSMiddleware"]
    assert len(cors_middlewares) == 1
    kwargs = cors_middlewares[0].kwargs
    assert "POST" in kwargs["allow_methods"]
    assert "GET" in kwargs["allow_methods"]
    assert "*" not in kwargs["allow_origins"]
    assert kwargs["allow_credentials"] is False


def test_launchd_status_endpoint_shape(monkeypatch, client):
    fake_status = {
        "operation_state": "RUNNING",
        "jobs": {
            "pead_bot": {"key": "pead_bot", "label": "com.rytty.quant_v7.pead_bot",
                         "loaded": True, "state": "not running", "last_exit_code": 0, "error": None},
            "pead_watchdog": {"key": "pead_watchdog", "label": "com.rytty.quant_v7.pead_watchdog",
                               "loaded": True, "state": "not running", "last_exit_code": 0, "error": None},
        },
    }
    monkeypatch.setattr(backend, "get_operation_status", lambda: fake_status)
    r = client.get("/api/launchd_status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "PAPER_TRADE"
    assert body["mode_verified"] is True
    assert body["operation_state"] == "RUNNING"
    assert body["jobs"]["pead_bot"]["loaded"] is True
    assert body["jobs"]["pead_watchdog"]["loaded"] is True


def test_launchd_status_mode_guard_failure_returns_500(monkeypatch, client):
    def _raise():
        raise RuntimeError("paper-mode assertion failed: simulated for this test")

    monkeypatch.setattr(backend, "assert_paper_only_mode", _raise)
    r = client.get("/api/launchd_status")
    assert r.status_code == 500
    assert "simulated for this test" in r.json()["detail"]


def test_control_start_calls_start_bot_operation_exactly_once(monkeypatch, client):
    calls = []

    def fake_start():
        calls.append("start")
        return {"watchdog": {"ok": True, "already_in_state": False}, "bot": {"ok": True, "already_in_state": False}}

    monkeypatch.setattr(backend, "start_bot_operation", fake_start)
    monkeypatch.setattr(backend, "get_operation_status", lambda: {"operation_state": "RUNNING", "jobs": {}})
    r = client.post("/api/control/start", json={"confirm": True})
    assert r.status_code == 200
    assert calls == ["start"]
    body = r.json()
    assert body["action"] == "start"
    assert body["jobs"]["bot"]["ok"] is True
    assert body["status"]["operation_state"] == "RUNNING"


def test_control_stop_calls_stop_bot_operation_exactly_once(monkeypatch, client):
    calls = []

    def fake_stop():
        calls.append("stop")
        return {"bot": {"ok": True, "already_in_state": False}, "watchdog": {"ok": True, "already_in_state": False}}

    monkeypatch.setattr(backend, "stop_bot_operation", fake_stop)
    monkeypatch.setattr(backend, "get_operation_status", lambda: {"operation_state": "STOPPED", "jobs": {}})
    r = client.post("/api/control/stop", json={"confirm": True})
    assert r.status_code == 200
    assert calls == ["stop"]
    assert r.json()["status"]["operation_state"] == "STOPPED"


def test_control_endpoints_require_confirm_true(monkeypatch, client):
    calls = []
    monkeypatch.setattr(backend, "start_bot_operation", lambda: calls.append("start"))
    monkeypatch.setattr(backend, "stop_bot_operation", lambda: calls.append("stop"))

    assert client.post("/api/control/start", json={}).status_code == 400
    assert client.post("/api/control/stop", json={"confirm": False}).status_code == 400
    assert client.post("/api/control/start").status_code == 400  # no body at all
    assert calls == []  # never reached the real operation, matching every other 400 case


def test_control_endpoints_refuse_when_paper_mode_guard_fails(monkeypatch, client):
    def _raise():
        raise RuntimeError("guard broke for this test")

    monkeypatch.setattr(backend, "assert_paper_only_mode", _raise)
    calls = []
    monkeypatch.setattr(backend, "start_bot_operation", lambda: calls.append("start"))
    monkeypatch.setattr(backend, "stop_bot_operation", lambda: calls.append("stop"))

    r1 = client.post("/api/control/start", json={"confirm": True})
    r2 = client.post("/api/control/stop", json={"confirm": True})
    assert r1.status_code == 500
    assert r2.status_code == 500
    # The critical proof the guard is a hard gate, not cosmetic: the real
    # start/stop operations must NEVER be reached when the guard fails.
    assert calls == []


def test_paper_mode_guard_passes_for_real_class(client):
    # Exercises the REAL invariant, unmocked -- safe because
    # LiveExecutionClient.__init__ only ever raises, never has a side effect.
    backend.assert_paper_only_mode()  # must not raise


def test_event_feed_endpoint_merges_and_sorts_newest_first(isolated_alerts, isolated_cycle_log, client):
    _write_jsonl(isolated_alerts, [
        {"ts": 500.0, "kind": "position_opened", "message": "paper position opened: AAPL long @ 100.00"},
    ])
    _write_jsonl(isolated_cycle_log, [
        {
            "ts": 100.0, "as_of_date": "2026-06-01", "kill_switch_engaged": False,
            "breaker_tier": "armed", "nav_before": 100000.0, "nav_after": 100500.0,
            "exits": [{"ticker": "MSFT", "entry_date": "2026-05-01", "exit_date": "2026-06-01",
                       "days_held": 20, "realized_pnl": 500.0}],
            "entries_considered": 2,
            "entries": [
                {"ticker": "AAPL", "sue": 1.5, "calibrated_proba": 0.7, "direction": "long",
                 "allowed": True, "reason": None, "detail": "approved", "size_fraction": 0.05},
                {"ticker": "TSLA", "sue": 0.1, "calibrated_proba": 0.4, "direction": "long",
                 "allowed": False, "reason": "no_conviction", "detail": "below threshold", "size_fraction": 0.0},
            ],
            "errors": ["NVDA: place_order failed: ValueError('boom')"],
        },
    ])
    events = client.get("/api/event_feed?limit=50").json()
    # 1 alert + (1 cycle_run + 1 exit + 1 entry_placed + 1 entry_skipped + 1 error) = 6
    assert len(events) == 6
    kinds = {e["kind"] for e in events}
    assert kinds == {"position_opened", "cycle_run", "exit", "entry_placed", "entry_skipped", "error"}
    timestamps = [e["ts"] for e in events]
    assert timestamps == sorted(timestamps, reverse=True)
    # the alert (ts=500) is strictly newer than every flattened cycle event (ts=100) -> first
    assert events[0]["kind"] == "position_opened"

    exit_event = next(e for e in events if e["kind"] == "exit")
    assert "MSFT" in exit_event["summary"] and "500.00" in exit_event["summary"]
    entry_placed = next(e for e in events if e["kind"] == "entry_placed")
    assert "AAPL" in entry_placed["summary"]
    entry_skipped = next(e for e in events if e["kind"] == "entry_skipped")
    assert "TSLA" in entry_skipped["summary"] and "no_conviction" in entry_skipped["summary"]
    error_event = next(e for e in events if e["kind"] == "error")
    assert "NVDA" in error_event["summary"]


def test_event_feed_respects_limit(isolated_alerts, isolated_cycle_log, client):
    _write_jsonl(isolated_alerts, [
        {"ts": float(i), "kind": "position_opened", "message": f"m{i}"} for i in range(20)
    ])
    _write_jsonl(isolated_cycle_log, [])
    events = client.get("/api/event_feed?limit=4").json()
    assert len(events) == 4
    assert [e["ts"] for e in events] == [19.0, 18.0, 17.0, 16.0]


def test_event_feed_empty_state(isolated_alerts, isolated_cycle_log, client):
    assert client.get("/api/event_feed").json() == []


# -- /api/research_tests: pre-registered hold-out verdicts ---------------------

def _point_research_paths_at(monkeypatch, root: Path) -> None:
    for name, rel in [("PREREGISTRATIONS_PATH", "preregistrations.jsonl"),
                      ("PEAD_2004_2014_RESULTS", "pead.json"),
                      ("MULTIASSET_DEV_RESULTS", "ma_dev.json"),
                      ("MULTIASSET_HOLDOUT_RESULTS", "ma_holdout.json"),
                      ("CRYPTO_DEV_RESULTS", "cr_dev.json"),
                      ("CRYPTO_HOLDOUT_RESULTS", "cr_holdout.json")]:
        monkeypatch.setattr(backend, name, root / rel)


def test_research_tests_unavailable_without_results(client, monkeypatch, tmp_path):
    _point_research_paths_at(monkeypatch, tmp_path)
    body = client.get("/api/research_tests").json()
    assert body["available"] is False
    assert body["tests"] == [] and body["sleeves"] == []
    assert body["target"] == {"sharpe": 2.0, "cagr": 0.10}


def test_research_tests_reads_verdicts_and_dev_vs_holdout(client, monkeypatch, tmp_path):
    _point_research_paths_at(monkeypatch, tmp_path)
    (tmp_path / "preregistrations.jsonl").write_text(json.dumps(
        {"file": "research/multiasset/PREREGISTRATION_holdout.md", "registered_at": "2026-09-18T12:06:06-0700"}) + "\n")
    (tmp_path / "ma_dev.json").write_text(json.dumps(
        {"sleeves": {"fx_carry": {"raw": {"sharpe": 0.45}}, "xs_momentum": {"raw": {"sharpe": -0.15}}}}))
    (tmp_path / "ma_holdout.json").write_text(json.dumps({
        "window": ["2018-01-01", "2026-09-17"], "passed": False, "book_sleeves": ["fx_carry"],
        "primary": {"sharpe": -0.02, "cagr_total": 0.019, "max_dd": -0.31, "hac_t": -0.07},
        "sleeves": {"fx_carry": {"sharpe": 0.25}, "xs_momentum": {"sharpe": 0.13}},
        "descriptive": {"spy": {"sharpe": 0.67, "cagr_total": 0.145, "max_dd": -0.34}}}))
    body = client.get("/api/research_tests").json()
    assert body["available"] is True
    [test] = body["tests"]
    assert test["id"] == "multiasset_2018_2026" and test["passed"] is False
    assert test["registered_at"] == "2026-09-18T12:06:06-0700"
    assert test["result"]["sharpe"] == -0.02 and test["benchmark"]["name"] == "SPY"
    by_name = {s["name"]: s for s in body["sleeves"]}
    assert by_name["fx_carry"] == {"name": "fx_carry", "family": "multi-asset", "dev_sharpe": 0.45,
                                   "holdout_sharpe": 0.25, "in_book": True}
    assert by_name["xs_momentum"]["in_book"] is False


def test_research_tests_against_real_reports(client):
    body = client.get("/api/research_tests").json()
    assert set(body) == {"available", "target", "tests", "sleeves"}
    for t in body["tests"]:
        assert isinstance(t["passed"], bool)
        assert {"sharpe", "cagr", "max_dd", "t_stat"} <= set(t["result"])


# ---------------------------------------------------------------------------
# Marked-to-market performance (bot/performance.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_marking(tmp_path, monkeypatch):
    """Synthetic ledger, bar cache and cycle logs: nothing real is read."""
    ledger = tmp_path / "paper_ledger.jsonl"
    cache = tmp_path / "raw"
    cache.mkdir()
    monkeypatch.setattr(backend, "LEDGER_FILE", ledger)
    monkeypatch.setattr(backend, "PRICE_CACHE_DIR", cache)
    monkeypatch.setattr(backend, "CYCLE_LOG_PATH", tmp_path / "cycle_log.jsonl")
    monkeypatch.setattr(backend, "BACKFILL_CYCLE_LOG_PATH", tmp_path / "backfill_cycle_log.jsonl")
    return {"ledger": ledger, "cache": cache, "cycle_log": tmp_path / "cycle_log.jsonl"}


def _bars(path: Path, closes: dict[str, float]) -> None:
    pd.DataFrame({"timestamp": pd.to_datetime(list(closes)), "close": list(closes.values())}).to_parquet(path, index=False)


def _two_trade_ledger(ledger: Path) -> None:
    # AAAA long 06-01 -> 06-05 at 100 -> 102; BBBB long 06-02 -> 06-09 at 50 -> 49.
    _write_jsonl(ledger, [
        {"event": "open", "entry_date": "2026-06-01", "ticker": "AAAA", "direction": "long",
         "fill_price": 100.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 1.0, "mode": "paper"},
        {"event": "open", "entry_date": "2026-06-02", "ticker": "BBBB", "direction": "long",
         "fill_price": 50.0, "size_fraction": 0.05, "notional": 5000.0, "ts": 2.0, "mode": "paper"},
        {"event": "close", "ticker": "AAAA", "direction": "long", "entry_price": 100.0, "exit_price": 102.0,
         "notional": 5000.0, "realized_pnl": 94.95, "gross_pnl": 100.0, "cost": 5.05,
         "reason": "holding_period_exit", "exit_date": "2026-06-05", "ts": 3.0},
        {"event": "close", "ticker": "BBBB", "direction": "long", "entry_price": 50.0, "exit_price": 49.0,
         "notional": 5000.0, "realized_pnl": -104.95, "gross_pnl": -100.0, "cost": 4.95,
         "reason": "holding_period_exit", "exit_date": "2026-06-09", "ts": 4.0},
    ])


def test_stats_and_curve_come_from_the_daily_marked_nav_over_tbills(isolated_marking, client):
    from bot.performance import daily_returns, daily_risk_free
    _two_trade_ledger(isolated_marking["ledger"])
    _bars(isolated_marking["cache"] / "AAAA.parquet",
          {"2026-06-01": 100.0, "2026-06-02": 104.0, "2026-06-03": 97.0, "2026-06-04": 101.0, "2026-06-05": 102.0})
    _bars(isolated_marking["cache"] / "BBBB.parquet",
          {"2026-06-02": 50.0, "2026-06-03": 53.0, "2026-06-04": 51.0, "2026-06-05": 48.0,
           "2026-06-08": 52.0, "2026-06-09": 49.0})

    marked = client.get("/api/equity_curve").json()["marked"]
    assert marked["dates"] == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
                               "2026-06-08", "2026-06-09"]
    nav = dict(zip(marked["dates"], marked["nav"]))
    cash = dict(zip(marked["dates"], marked["cash_basis_nav"]))
    # 06-03, a day with no exit: AAAA -3% and BBBB +6% on $5,000 each.
    assert nav["2026-06-03"] == pytest.approx(100_000.0 - 150.0 + 300.0)
    assert cash["2026-06-03"] == 100_000.0
    # Both closed by 06-09: the two NAVs agree.
    assert nav["2026-06-09"] == pytest.approx(cash["2026-06-09"]) == pytest.approx(100_000.0 + 94.95 - 104.95)

    stats = client.get("/api/stats").json()
    series = pd.Series(marked["nav"], index=pd.to_datetime(marked["dates"]))
    returns = daily_returns(series, 100_000.0)
    rf = daily_risk_free(returns.index)
    expected = (returns - rf).mean() * 252 / (returns.std(ddof=1) * math.sqrt(252))
    assert stats["sharpe_ratio"] == pytest.approx(expected, abs=1e-3)
    assert stats["risk_free_rate"] == pytest.approx(rf.mean() * 252, abs=1e-6)
    assert stats["stale_marks"] == 0
    assert stats["marked_nav"] == pytest.approx(nav["2026-06-09"], abs=0.01)
    assert stats["current_nav"] == pytest.approx(100_000.0 - 10.0)  # still cash-basis, as labelled


def test_recorded_cycle_marks_take_precedence_over_a_stale_cache(isolated_marking, client):
    """The bar cache only covers the circuit-breaker basket; for anything else
    the bot's own recorded mark is the latest close available."""
    _write_jsonl(isolated_marking["ledger"], [
        {"event": "open", "entry_date": "2026-09-14", "ticker": "KR", "direction": "long",
         "fill_price": 60.0, "size_fraction": 0.05, "notional": 6000.0, "ts": 1.0, "mode": "paper"},
    ])
    _bars(isolated_marking["cache"] / "KR.parquet", {"2026-08-14": 50.0})  # stale, and from before entry
    _write_jsonl(isolated_marking["cycle_log"], [
        {"ts": 1.0, "as_of_date": "2026-09-14", "session_open": True, "marks": {"KR": 60.0}, "marked_nav": 100_000.0},
        {"ts": 2.0, "as_of_date": "2026-09-15", "session_open": True, "marks": {"KR": 63.0}, "marked_nav": 100_300.0},
    ])
    [p] = client.get("/api/positions").json()
    assert (p["last_close"], p["last_close_date"]) == (63.0, "2026-09-15")
    assert p["unrealized_pnl"] == pytest.approx(300.0)
    marked = client.get("/api/equity_curve").json()["marked"]
    assert marked["dates"] == ["2026-09-14", "2026-09-15"]
    assert marked["nav"] == [100_000.0, 100_300.0]


def test_open_pnl_ignores_a_close_from_before_the_position_was_opened(isolated_marking, client):
    _write_jsonl(isolated_marking["ledger"], [
        {"event": "open", "entry_date": "2026-09-11", "ticker": "KR", "direction": "long",
         "fill_price": 60.0, "size_fraction": 0.05, "notional": 6000.0, "ts": 1.0, "mode": "paper"},
    ])
    _bars(isolated_marking["cache"] / "KR.parquet", {"2026-08-14": 50.0})
    [p] = client.get("/api/positions").json()
    assert p["last_close"] is None and p["unrealized_pnl"] is None
    stats = client.get("/api/stats").json()
    assert stats["unrealized_pnl"] is None
    assert stats["stale_marks"] == 1  # the entry day, carried at cost
