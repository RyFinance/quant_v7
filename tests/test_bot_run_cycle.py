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
    monkeypatch.setattr(rc, "build_alerter", alerter)
    # The cycle's price refresh writes data/raw and its schedule snapshot
    # writes bot/state; keep both off real state. Tests that exercise the
    # session gate itself patch prepare_market_session explicitly.
    monkeypatch.setattr(rc, "prepare_market_session", lambda tickers, as_of: (True, "test session"))
    monkeypatch.setattr(rc, "UPCOMING_EARNINGS_FILE", tmp_path / "upcoming_earnings.json")
    monkeypatch.setattr(rc, "BACKFILL_CYCLE_LOG_FILE", tmp_path / "backfill_cycle_log.jsonl")
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


def _fake_event(earnings_date="2026-09-10 16:05:00"):
    return ReportedEarnings(
        ticker="ORCL", earnings_date=pd.Timestamp(earnings_date),
        eps_estimate=1.74, eps_actual=1.92, surprise_pct=10.45, days_since=1,
    )


def test_run_cycle_evaluates_each_announcement_only_once(isolated_state, monkeypatch):
    """An event rejected on its effective day must not be re-scored (and
    possibly entered late) by the next cycles inside the lookback window."""
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [_fake_event()])
    scored = []
    monkeypatch.setattr(rc, "score_event", lambda event, pipeline: scored.append(event.ticker) or ScoredEvent(
        ticker="ORCL", earnings_date=event.earnings_date, sue=0.1, calibrated_proba=0.01, direction="long",
    ))
    monkeypatch.setattr(rc, "current_breaker_tier", lambda: ("armed", {}))

    first = rc.run_cycle(as_of_date="2026-09-11", ledger_path=isolated_state["ledger"])
    second = rc.run_cycle(as_of_date="2026-09-14", ledger_path=isolated_state["ledger"])

    assert scored == ["ORCL"]
    assert first.entries[0].allowed is False
    assert first.entries[0].earnings_date == "2026-09-10T16:05:00"
    assert second.entries == []


def test_run_cycle_trades_nothing_outside_a_completed_session(isolated_state, monkeypatch):
    monkeypatch.setattr(rc, "prepare_market_session", lambda tickers, as_of: (False, "holiday"))
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [_fake_event()])
    monkeypatch.setattr(rc, "score_event", lambda event, pipeline: pytest.fail("must not score on a closed session"))
    monkeypatch.setattr(rc.PositionManager, "process_exits", lambda self, client, as_of_date: pytest.fail("must not exit"))
    monkeypatch.setattr(rc, "current_breaker_tier", lambda: ("armed", {}))

    report = rc.run_cycle(as_of_date="2026-09-11", ledger_path=isolated_state["ledger"])
    assert report.session_open is False
    assert report.session_detail == "holiday"
    assert report.entries == [] and report.exits == []
    assert report.marked_nav is None  # no completed session, no close to mark at
    assert isolated_state["heartbeat"].exists()  # a closed day is still a healthy cycle


def test_prepare_market_session_requires_a_bar_for_the_day(monkeypatch):
    day = pd.Timestamp("2026-09-11")
    monkeypatch.setattr(rc, "refresh_cached_history", lambda tickers: {t: day for t in tickers})
    assert rc.prepare_market_session(["A", "B"], "2026-09-11")[0] is True

    monkeypatch.setattr(rc, "refresh_cached_history", lambda tickers: {t: day - pd.Timedelta(days=1) for t in tickers})
    is_open, detail = rc.prepare_market_session(["A", "B"], "2026-09-11")
    assert is_open is False and "no regular session" in detail


def test_run_cycle_writes_upcoming_earnings_snapshot(isolated_state, monkeypatch):
    from bot.earnings_watcher import ScheduledEarnings
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [])
    monkeypatch.setattr(rc.EarningsWatcher, "scheduled_from_last_fetch", lambda self, days, now=None: [
        ScheduledEarnings(ticker="JPM", earnings_date=pd.Timestamp("2026-10-13 08:00:00"),
                          timing="before_close", eps_estimate=5.89, days_until=26),
    ])
    monkeypatch.setattr(rc, "current_breaker_tier", lambda: ("armed", {}))

    rc.run_cycle(as_of_date="2026-09-17", ledger_path=isolated_state["ledger"])
    snapshot = json.loads((isolated_state["ledger"].parent / "upcoming_earnings.json").read_text())
    assert snapshot["as_of_date"] == "2026-09-17"
    assert snapshot["events"] == [{"ticker": "JPM", "earnings_date": "2026-10-13T08:00:00",
                                   "timing": "before_close", "eps_estimate": 5.89, "days_until": 26}]


def test_run_cycle_gates_highest_conviction_first(isolated_state, monkeypatch):
    """With ~480 events a quarter the exposure cap binds most days, so the
    order candidates reach the gate decides what gets traded. It must be model
    conviction, not whichever name happened to report first."""
    weak = ReportedEarnings(ticker="AAPL", earnings_date=pd.Timestamp("2026-09-10 16:05:00"),
                            eps_estimate=1.0, eps_actual=1.1, surprise_pct=10.0, days_since=1)
    strong = ReportedEarnings(ticker="MSFT", earnings_date=pd.Timestamp("2026-09-10 16:05:00"),
                              eps_estimate=1.0, eps_actual=1.3, surprise_pct=30.0, days_since=1)
    # Reported order puts the weak signal first; conviction order must flip it.
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [weak, strong])
    probas = {"AAPL": 0.55, "MSFT": 0.92}
    monkeypatch.setattr(rc, "score_event", lambda event, pipeline: ScoredEvent(
        ticker=event.ticker, earnings_date=event.earnings_date, sue=1.0,
        calibrated_proba=probas[event.ticker], direction="long",
    ))
    monkeypatch.setattr(rc, "current_breaker_tier", lambda: ("armed", {}))
    monkeypatch.setattr(ex, "get_current_price", lambda ticker: 100.0)

    report = rc.run_cycle(as_of_date="2026-09-11", ledger_path=isolated_state["ledger"])
    assert [e.ticker for e in report.entries] == ["MSFT", "AAPL"]


def test_run_cycle_caps_each_position_at_the_bot_limit(isolated_state, monkeypatch):
    """A high-conviction event must still be sized within the bot's per-position
    cap, so one name cannot swallow the shared exposure budget."""
    event = ReportedEarnings(ticker="NVDA", earnings_date=pd.Timestamp("2026-09-10 16:05:00"),
                             eps_estimate=1.0, eps_actual=2.0, surprise_pct=100.0, days_since=1)
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported", lambda self, **kw: [event])
    monkeypatch.setattr(rc, "score_event", lambda e, pipeline: ScoredEvent(
        ticker="NVDA", earnings_date=e.earnings_date, sue=3.0, calibrated_proba=0.99, direction="long",
    ))
    monkeypatch.setattr(rc, "current_breaker_tier", lambda: ("armed", {}))
    monkeypatch.setattr(ex, "get_current_price", lambda ticker: 100.0)

    report = rc.run_cycle(as_of_date="2026-09-11", ledger_path=isolated_state["ledger"])
    assert report.entries[0].allowed is True
    assert report.entries[0].size_fraction == pytest.approx(rc.BOT_RISK_LIMITS.max_position_pct)
    # The live configuration chosen from live_backtest/compare_configurations.py.
    assert rc.BOT_RISK_LIMITS.max_position_pct == 0.05
    assert rc.BOT_RISK_LIMITS.max_total_exposure_pct == 1.00


def test_cycle_log_records_marked_nav_without_changing_what_is_traded(isolated_state, monkeypatch):
    """The cycle log carries a marked NAV that moves while a position is held,
    nav_before/nav_after stay cash-basis, a new order is still sized off the
    cash-basis NAV, and the two NAVs agree once everything has closed."""
    events = {
        "2026-09-11": [ReportedEarnings(ticker="NVDA", earnings_date=pd.Timestamp("2026-09-10 16:05:00"),
                                        eps_estimate=1.0, eps_actual=2.0, surprise_pct=100.0, days_since=1)],
        "2026-09-14": [ReportedEarnings(ticker="MSFT", earnings_date=pd.Timestamp("2026-09-11 16:05:00"),
                                        eps_estimate=1.0, eps_actual=2.0, surprise_pct=100.0, days_since=1)],
    }
    closes = {
        "2026-09-11": {"NVDA": 100.0},
        "2026-09-14": {"NVDA": 110.0, "MSFT": 50.0},
        "2026-10-09": {"NVDA": 120.0, "MSFT": 55.0},  # NVDA's 20th trading day: exits
        "2026-10-12": {"NVDA": 121.0, "MSFT": 54.0},  # MSFT's 20th trading day: exits
    }
    day = {}
    monkeypatch.setattr(rc.EarningsWatcher, "get_recently_reported",
                        lambda self, **kw: events.get(kw["now"].date().isoformat(), []))
    monkeypatch.setattr(rc, "score_event", lambda e, pipeline: ScoredEvent(
        ticker=e.ticker, earnings_date=e.earnings_date, sue=3.0, calibrated_proba=0.99, direction="long",
    ))
    monkeypatch.setattr(rc, "current_breaker_tier", lambda: ("armed", {}))
    monkeypatch.setattr(ex, "get_current_price", lambda ticker: closes[day["as_of"]][ticker])

    reports = {}
    for as_of in closes:
        day["as_of"] = as_of
        reports[as_of] = rc.run_cycle(as_of_date=as_of, ledger_path=isolated_state["ledger"])
    logged = {r["as_of_date"]: r for r in map(json.loads, isolated_state["cycle_log"].read_text().splitlines())}

    # Day 1: NVDA bought at the close and marked at that same close.
    assert logged["2026-09-11"]["marked_nav"] == pytest.approx(100_000.0)
    assert logged["2026-09-11"]["marks"] == {"NVDA": 100.0}
    # Day 2, a non-exit day: +10% on $5,000 shows in the marked NAV only.
    assert logged["2026-09-14"]["nav_after"] == 100_000.0
    assert logged["2026-09-14"]["marked_nav"] == pytest.approx(100_500.0)
    assert logged["2026-09-14"]["unrealized_pnl"] == pytest.approx(500.0)
    # ...and MSFT, bought that day, was sized off the cash-basis 100,000, not the marked 100,500.
    ledger = [json.loads(l) for l in isolated_state["ledger"].read_text().splitlines()]
    msft = next(r for r in ledger if r["event"] == "open" and r["ticker"] == "MSFT")
    assert msft["notional"] == pytest.approx(0.05 * 100_000.0)
    # NVDA exits; MSFT is still open, so the two NAVs differ by its mark.
    oct9 = logged["2026-10-09"]
    assert [e["ticker"] for e in oct9["exits"]] == ["NVDA"]
    assert oct9["marked_nav"] - oct9["nav_after"] == pytest.approx(5_000.0 * 0.10)
    # Last exit: book empty, marked == cash basis.
    oct12 = logged["2026-10-12"]
    assert [e["ticker"] for e in oct12["exits"]] == ["MSFT"]
    assert oct12["marks"] == {} and oct12["unmarked"] == []
    assert oct12["marked_nav"] == pytest.approx(oct12["nav_after"])
    assert reports["2026-10-12"].marked_nav == pytest.approx(reports["2026-10-12"].nav_after)
