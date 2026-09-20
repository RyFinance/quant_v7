"""Tests for bot/performance.py: the daily mark-to-market NAV rebuilt from the
paper ledger, the T-bill series excess returns are measured against, and
compute_metrics' daily risk-free input. Prices are synthetic and set by hand
so every expected NAV can be written down."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import bot.execution as ex
import bot.kill_switch as ks
import bot.risk_gate as rg
from backtest.metrics import compute_metrics
from bot.alerting import BotAlerter
from bot.performance import (
    daily_marked_nav, daily_returns, daily_risk_free, excess_metrics, ledger_trades, price_panel, read_jsonl,
    recorded_marks, risk_free_last_published,
)
from risk.limits import RiskLimits

DAYS = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08"]
# Close each day. AAPL is held long 09-01 -> exit 09-04, MSFT short 09-01 -> exit 09-08.
CLOSES = {
    "AAPL": [100.0, 104.0, 101.0, 103.0, 99.0],
    "MSFT": [50.0, 51.0, 49.0, 48.0, 47.0],
}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ks, "KILL_SWITCH_FILE", tmp_path / "KILL_SWITCH")
    alerter = lambda: BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl")
    monkeypatch.setattr(ex, "build_alerter", alerter)
    monkeypatch.setattr(rg, "build_alerter", alerter)
    return tmp_path


def _decision(ticker):
    return rg.evaluate(ticker=ticker, calibrated_proba=0.99, payoff_ratio_b=1.2, current_total_exposure_pct=0.0,
                       current_daily_pnl_pct=0.0, paper_nav=100_000.0, paper_high_water_mark=100_000.0,
                       limits=RiskLimits(max_position_pct=0.05), breaker_tier="armed")


def _trade_the_script(tmp_path, monkeypatch) -> tuple[list[dict], pd.DataFrame]:
    """Run the scripted account through the real client, one day at a time,
    and return what it reported each day plus the closes it saw."""
    ledger = tmp_path / "ledger.jsonl"
    client = ex.PaperExecutionClient(ledger_path=ledger)
    today = {}
    monkeypatch.setattr(ex, "get_current_price", lambda t: CLOSES[t][today["i"]])
    reported = []
    for i, day in enumerate(DAYS):
        today["i"] = i
        if i == 0:
            client.place_order("AAPL", "long", _decision("AAPL"), entry_date=day)
            client.place_order("MSFT", "short", _decision("MSFT"), entry_date=day)
        if day == "2026-09-04":
            client.close_position("AAPL", exit_date=day)
        if day == "2026-09-08":
            client.close_position("MSFT", exit_date=day)
        marked = client.marked_nav()
        reported.append({"day": day, "marked": marked.nav, "cash": client.nav()})
    closes = pd.DataFrame(CLOSES, index=pd.to_datetime(DAYS))
    return reported, closes


def test_rebuilt_series_reproduces_the_live_marks_day_by_day(isolated, monkeypatch):
    reported, closes = _trade_the_script(isolated, monkeypatch)
    frame = daily_marked_nav(read_jsonl(isolated / "ledger.jsonl"), closes, DAYS, 100_000.0)
    assert list(frame["marked_nav"]) == pytest.approx([r["marked"] for r in reported])
    assert list(frame["cash_basis_nav"]) == pytest.approx([r["cash"] for r in reported])
    assert list(frame["stale_marks"]) == [0] * len(DAYS)
    assert list(frame["open_positions"]) == [2, 2, 2, 1, 0]


def test_a_position_held_across_days_moves_the_marked_nav_on_non_exit_days(isolated, monkeypatch):
    reported, closes = _trade_the_script(isolated, monkeypatch)
    frame = daily_marked_nav(read_jsonl(isolated / "ledger.jsonl"), closes, DAYS, 100_000.0)
    held = frame.loc["2026-09-01":"2026-09-03"]  # both open, nothing closes
    # Cash basis is flat until the first exit; the marked NAV moves every day.
    assert held["cash_basis_nav"].nunique() == 1
    assert held["marked_nav"].diff().dropna().abs().min() > 0
    # 09-02: AAPL 100 -> 104 on $5,000 long, MSFT 50 -> 51 on $5,000 short.
    assert frame.loc["2026-09-02", "marked_nav"] == pytest.approx(100_000.0 + 200.0 - 100.0)
    # The cash-basis return series is zero on every non-exit day; the marked one is not.
    cash_returns = daily_returns(frame["cash_basis_nav"], 100_000.0)
    marked_returns = daily_returns(frame["marked_nav"], 100_000.0)
    assert (cash_returns.loc["2026-09-02":"2026-09-03"] == 0).all()
    assert (marked_returns.loc["2026-09-02":"2026-09-03"] != 0).all()


def test_marked_and_cash_basis_agree_once_every_position_has_closed(isolated, monkeypatch):
    reported, closes = _trade_the_script(isolated, monkeypatch)
    frame = daily_marked_nav(read_jsonl(isolated / "ledger.jsonl"), closes, DAYS, 100_000.0)
    last = frame.iloc[-1]
    assert last["open_positions"] == 0
    assert last["marked_nav"] == pytest.approx(last["cash_basis_nav"])
    assert last["cash_basis_nav"] == pytest.approx(ex.PaperExecutionClient.from_ledger(ledger_path=isolated / "ledger.jsonl").nav())
    # Days that stay flat after the book is empty stay equal too.
    later = daily_marked_nav(read_jsonl(isolated / "ledger.jsonl"), closes, DAYS + ["2026-09-09"], 100_000.0)
    assert later.iloc[-1]["marked_nav"] == pytest.approx(later.iloc[-1]["cash_basis_nav"])


def test_exit_day_step_is_exactly_the_round_trip_cost_when_price_is_unchanged(isolated, monkeypatch):
    """Marks are gross of the exit cost (it is charged at the close), so with
    an unchanged price the marked NAV drops by exactly the cost on exit day."""
    client = ex.PaperExecutionClient(ledger_path=isolated / "ledger.jsonl")
    monkeypatch.setattr(ex, "get_current_price", lambda t: 100.0)
    client.place_order("AAPL", "long", _decision("AAPL"), entry_date="2026-09-01")
    client.close_position("AAPL", exit_date="2026-09-03")
    records = read_jsonl(isolated / "ledger.jsonl")
    closes = pd.DataFrame({"AAPL": [100.0, 100.0, 100.0]}, index=pd.to_datetime(DAYS[:3]))
    frame = daily_marked_nav(records, closes, DAYS[:3], 100_000.0)
    assert frame["marked_nav"].iloc[1] - frame["marked_nav"].iloc[2] == pytest.approx(records[-1]["cost"])


def test_never_marks_with_a_price_from_before_entry_and_counts_stale_marks():
    records = [
        {"event": "open", "ticker": "XYZ", "direction": "long", "entry_date": "2026-09-02",
         "fill_price": 100.0, "notional": 5_000.0},
    ]
    # Only a pre-entry close, then one close on 09-03, then nothing.
    closes = pd.DataFrame({"XYZ": [80.0, 110.0]}, index=pd.to_datetime(["2026-08-14", "2026-09-03"]))
    frame = daily_marked_nav(records, closes, ["2026-09-02", "2026-09-03", "2026-09-04"], 100_000.0)
    assert frame.loc["2026-09-02", "unrealized_pnl"] == 0.0        # carried at cost, not at 80
    assert frame.loc["2026-09-03", "unrealized_pnl"] == pytest.approx(500.0)
    assert frame.loc["2026-09-04", "unrealized_pnl"] == pytest.approx(500.0)  # 09-03 close carried forward
    assert list(frame["stale_marks"]) == [1, 0, 1]


def test_reopened_ticker_is_two_trades():
    records = [
        {"event": "open", "ticker": "A", "direction": "long", "entry_date": "2026-01-02", "fill_price": 10.0, "notional": 100.0},
        {"event": "close", "ticker": "A", "exit_date": "2026-02-02", "realized_pnl": 5.0},
        {"event": "open", "ticker": "A", "direction": "short", "entry_date": "2026-03-02", "fill_price": 12.0, "notional": 100.0},
    ]
    trades = ledger_trades(records)
    assert [(t.direction, t.exit_date is not None) for t in trades] == [("long", True), ("short", False)]


def test_recorded_marks_override_cached_closes():
    cycles = [
        {"ts": 1.0, "as_of_date": "2026-09-17", "session_open": True, "marks": {"XYZ": 101.0}},
        {"ts": 2.0, "as_of_date": "2026-09-17", "session_open": True, "marks": {"XYZ": 102.0}},  # a re-run wins
        {"ts": 3.0, "as_of_date": "2026-09-19", "session_open": False, "marks": {"XYZ": 999.0}},  # closed session
    ]
    cached = pd.DataFrame({"XYZ": [95.0, 97.0]}, index=pd.to_datetime(["2026-09-16", "2026-09-17"]))
    panel = price_panel(cached, recorded_marks(cycles))
    assert panel["XYZ"].to_dict() == {pd.Timestamp("2026-09-16"): 95.0, pd.Timestamp("2026-09-17"): 102.0}


def test_daily_risk_free_is_the_french_rate_carried_forward():
    last = risk_free_last_published()
    rf = daily_risk_free(pd.to_datetime([last, last + pd.Timedelta(days=45)]))
    assert rf.iloc[0] == rf.iloc[1] > 0
    assert rf.iloc[0] < 0.001  # a simple DAILY rate, not an annual one
    with pytest.raises(ValueError):
        daily_risk_free(pd.to_datetime(["1900-01-02"]))


def test_compute_metrics_takes_sharpe_in_excess_of_a_daily_rate():
    idx = pd.bdate_range("2024-01-01", periods=60)
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.0005, 0.01, len(idx)), index=idx)
    rf = pd.Series(np.linspace(0.0001, 0.0002, len(idx)), index=idx)
    m = compute_metrics(returns, 0, daily_risk_free=rf)
    expected = (returns - rf).mean() * 252 / (returns.std(ddof=1) * np.sqrt(252))
    assert m.sharpe_ratio == pytest.approx(round(expected, 4))
    assert m.sharpe_ratio < compute_metrics(returns, 0).sharpe_ratio
    assert m.annualized_return == compute_metrics(returns, 0).annualized_return  # the NAV path itself is unchanged
    with pytest.raises(ValueError):
        compute_metrics(returns, 0, daily_risk_free=rf.iloc[:-1])  # a return date without a rate
    with pytest.raises(ValueError):
        compute_metrics(returns, 0, annual_risk_free_rate=0.04, daily_risk_free=rf)


def test_excess_metrics_uses_the_french_rate_on_each_day():
    nav = pd.Series([100_000.0, 100_500.0, 100_200.0, 101_000.0], index=pd.bdate_range("2025-03-03", periods=4))
    m, returns, rf = excess_metrics(nav, 100_000.0, n_trades=1)
    assert returns.iloc[0] == 0.0 and returns.iloc[1] == pytest.approx(0.005)
    assert rf.equals(daily_risk_free(nav.index))
    assert m.sharpe_ratio == compute_metrics(returns, 1, daily_risk_free=rf).sharpe_ratio


def test_a_ticker_with_no_prices_at_all_is_carried_at_cost():
    records = [{"event": "open", "ticker": "NOPX", "direction": "short", "entry_date": "2026-09-02",
                "fill_price": 20.0, "notional": 2_000.0}]
    frame = daily_marked_nav(records, pd.DataFrame(), ["2026-09-02", "2026-09-03"], 100_000.0)
    assert list(frame["marked_nav"]) == [100_000.0, 100_000.0]
    assert list(frame["stale_marks"]) == [1, 1]
