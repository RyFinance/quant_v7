"""Tests for bot/execution.py. Hits real yfinance data for current prices
(no synthetic price series) -- skipped gracefully if offline, matching the
project convention in tests/test_ingestion.py.
"""
from __future__ import annotations

import json

import pytest

import bot.execution as ex
import bot.kill_switch as ks
import bot.risk_gate as rg


@pytest.fixture
def isolated_kill_switch(tmp_path, monkeypatch):
    sentinel = tmp_path / "KILL_SWITCH"
    monkeypatch.setattr(ks, "KILL_SWITCH_FILE", sentinel)
    # Regression fix (2026-08-19): PaperExecutionClient() defaults to
    # build_alerter(), which previously wrote real alerts to the REAL
    # production bot/state/bot_alerts.jsonl on every test run in this file.
    # Isolate it the same way KILL_SWITCH_FILE already is here.
    from bot.alerting import BotAlerter
    monkeypatch.setattr(ex, "build_alerter", lambda: BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl"))
    monkeypatch.setattr(rg, "build_alerter", lambda: BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl"))
    return sentinel


def _approved_decision(**overrides):
    defaults = dict(
        ticker="AAPL", calibrated_proba=0.65, payoff_ratio_b=1.2,
        current_total_exposure_pct=0.0, current_daily_pnl_pct=0.0,
        paper_nav=100_000.0, paper_high_water_mark=100_000.0,
        breaker_tier="armed",
    )
    defaults.update(overrides)
    return rg.evaluate(**defaults)


def test_get_current_price_returns_real_positive_price():
    try:
        price = ex.get_current_price("AAPL")
    except Exception as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")
    assert price > 0


def test_place_order_requires_valid_approval(isolated_kill_switch, tmp_path):
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=tmp_path / "ledger.jsonl")
    denied = rg.RiskGateDecision(allowed=False, reason=None, detail="denied", approval_token=None)
    with pytest.raises(PermissionError):
        client.place_order("AAPL", "long", denied, entry_date="2024-01-02")


def test_place_order_rejects_fabricated_token(isolated_kill_switch, tmp_path):
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=tmp_path / "ledger.jsonl")
    fabricated = rg.RiskGateDecision(
        allowed=True, reason=None, detail="fake", size_fraction=0.05, approval_token="fabricated-not-minted",
    )
    with pytest.raises(PermissionError):
        client.place_order("AAPL", "long", fabricated, entry_date="2024-01-02")


def test_place_order_fills_at_real_price_and_writes_ledger(isolated_kill_switch, tmp_path):
    decision = _approved_decision()
    assert decision.allowed is True  # sanity: these defaults must pass the gate

    ledger_path = tmp_path / "ledger.jsonl"
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=ledger_path)
    try:
        fill = client.place_order("AAPL", "long", decision, entry_date="2024-01-02")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    assert fill.fill_price > 0
    assert fill.mode == "paper"
    assert "AAPL" in client.positions
    assert client.positions["AAPL"].open is True
    assert client.positions["AAPL"].entry_price == fill.fill_price

    assert ledger_path.exists()
    lines = ledger_path.read_text().strip().splitlines()
    assert len(lines) == 1


def test_place_order_rejects_duplicate_open_position(isolated_kill_switch, tmp_path):
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=tmp_path / "ledger.jsonl")
    decision1 = _approved_decision()
    try:
        client.place_order("AAPL", "long", decision1, entry_date="2024-01-02")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    decision2 = _approved_decision()
    with pytest.raises(ValueError):
        client.place_order("AAPL", "long", decision2, entry_date="2024-01-03")


def test_place_order_token_cannot_be_reused_across_clients(isolated_kill_switch, tmp_path):
    decision = _approved_decision()
    client_a = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=tmp_path / "a.jsonl")
    client_b = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=tmp_path / "b.jsonl")
    try:
        client_a.place_order("AAPL", "long", decision, entry_date="2024-01-02")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    with pytest.raises(PermissionError):
        client_b.place_order("MSFT", "long", decision, entry_date="2024-01-02")


def test_close_position_updates_nav_and_ledger(isolated_kill_switch, tmp_path):
    decision = _approved_decision()
    ledger_path = tmp_path / "ledger.jsonl"
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=ledger_path)
    try:
        client.place_order("AAPL", "long", decision, entry_date="2024-01-02")
        pnl = client.close_position("AAPL", exit_date="2024-02-01")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    assert client.positions["AAPL"].open is False
    assert client.positions["AAPL"].realized_pnl == pnl
    assert client.nav() == client.starting_capital + client.realized_pnl
    lines = ledger_path.read_text().strip().splitlines()
    assert len(lines) == 2  # open + close


def test_live_execution_client_always_raises():
    with pytest.raises(NotImplementedError):
        ex.LiveExecutionClient()
    with pytest.raises(NotImplementedError):
        ex.LiveExecutionClient(api_key="doesnt-matter")


def test_from_ledger_reconstructs_open_position(isolated_kill_switch, tmp_path):
    """Regression test: place_order's ledger record must carry entry_date
    (an earlier version of this code omitted it from the JSONL write, which
    would silently break position_manager's holding-period math on replay)."""
    decision = _approved_decision()
    ledger_path = tmp_path / "ledger.jsonl"
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=ledger_path)
    try:
        client.place_order("AAPL", "long", decision, entry_date="2024-01-02")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    replayed = ex.PaperExecutionClient.from_ledger(starting_capital=100_000.0, ledger_path=ledger_path)
    assert "AAPL" in replayed.positions
    assert replayed.positions["AAPL"].open is True
    assert replayed.positions["AAPL"].entry_date == "2024-01-02"
    assert replayed.positions["AAPL"].entry_price == client.positions["AAPL"].entry_price
    assert replayed.nav() == client.nav()


def test_from_ledger_reconstructs_closed_position_and_pnl(isolated_kill_switch, tmp_path):
    decision = _approved_decision()
    ledger_path = tmp_path / "ledger.jsonl"
    client = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=ledger_path)
    try:
        client.place_order("AAPL", "long", decision, entry_date="2024-01-02")
        pnl = client.close_position("AAPL", exit_date="2024-02-01")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    replayed = ex.PaperExecutionClient.from_ledger(starting_capital=100_000.0, ledger_path=ledger_path)
    assert replayed.positions["AAPL"].open is False
    assert replayed.positions["AAPL"].realized_pnl == pnl
    assert replayed.realized_pnl == client.realized_pnl
    assert replayed.nav() == client.nav()
    assert replayed.high_water_mark >= replayed.starting_capital


def test_from_ledger_missing_file_returns_empty_client(tmp_path):
    client = ex.PaperExecutionClient.from_ledger(starting_capital=50_000.0, ledger_path=tmp_path / "nope.jsonl")
    assert client.positions == {}
    assert client.nav() == 50_000.0


def test_from_ledger_open_then_reopen_across_two_tickers(isolated_kill_switch, tmp_path):
    """Simulates two separate cron-fired processes: first opens AAPL, a
    second (fresh client, same ledger) opens MSFT -- both must be visible
    after a third replay, proving state genuinely survives process restarts."""
    ledger_path = tmp_path / "ledger.jsonl"
    client1 = ex.PaperExecutionClient(starting_capital=100_000.0, ledger_path=ledger_path)
    try:
        client1.place_order("AAPL", "long", _approved_decision(ticker="AAPL"), entry_date="2024-01-02")
    except RuntimeError as e:
        pytest.skip(f"network unavailable / yfinance unreachable: {e!r}")

    client2 = ex.PaperExecutionClient.from_ledger(starting_capital=100_000.0, ledger_path=ledger_path)
    client2.place_order("MSFT", "long", _approved_decision(ticker="MSFT"), entry_date="2024-01-03")

    client3 = ex.PaperExecutionClient.from_ledger(starting_capital=100_000.0, ledger_path=ledger_path)
    assert set(client3.positions.keys()) == {"AAPL", "MSFT"}
    assert all(p.open for p in client3.positions.values())


def test_close_position_charges_the_round_trip_cost(tmp_path, monkeypatch):
    """The paper account must quote returns net of the same 10 bps round trip
    the cost-adjusted label and every research backtest already assume."""
    import json
    from bot.alerting import BotAlerter
    from risk.limits import RiskLimits

    alerter = BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl")
    client = ex.PaperExecutionClient(ledger_path=tmp_path / "ledger.jsonl", alerter=alerter)
    decision = _approved_decision(calibrated_proba=0.99, limits=RiskLimits(max_position_pct=0.05))
    assert decision.size_fraction == pytest.approx(0.05)

    monkeypatch.setattr(ex, "get_current_price", lambda ticker: 100.0)
    client.place_order("AAPL", "long", decision, entry_date="2026-09-01")
    monkeypatch.setattr(ex, "get_current_price", lambda ticker: 110.0)
    pnl = client.close_position("AAPL", exit_date="2026-09-29")

    notional = 5_000.0                                     # 5% of 100k
    gross = notional * 0.10                                # +10% move
    cost = (notional + notional * 1.10) * (10.0 / 2 / 10_000)
    assert pnl == pytest.approx(gross - cost)
    assert client.nav() == pytest.approx(100_000.0 + gross - cost)

    record = json.loads((tmp_path / "ledger.jsonl").read_text().strip().splitlines()[-1])
    assert record["gross_pnl"] == pytest.approx(gross)
    assert record["cost"] == pytest.approx(cost)
    assert record["cost_bps_round_trip"] == 10.0
    # NAV replayed from the ledger must match the in-process client exactly.
    assert ex.PaperExecutionClient.from_ledger(ledger_path=tmp_path / "ledger.jsonl").nav() == pytest.approx(client.nav())


def test_cost_free_client_reproduces_the_old_gross_accounting(tmp_path, monkeypatch):
    """The cost is a parameter, not a hardcode: research callers can still
    replay gross by passing 0 bps."""
    from bot.alerting import BotAlerter
    from risk.limits import RiskLimits

    client = ex.PaperExecutionClient(ledger_path=tmp_path / "ledger.jsonl", round_trip_cost_bps=0.0,
                                     alerter=BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl"))
    monkeypatch.setattr(ex, "get_current_price", lambda ticker: 100.0)
    client.place_order("MSFT", "long", _approved_decision(calibrated_proba=0.99, limits=RiskLimits(max_position_pct=0.05)),
                       entry_date="2026-09-01")
    monkeypatch.setattr(ex, "get_current_price", lambda ticker: 110.0)
    assert client.close_position("MSFT", exit_date="2026-09-29") == pytest.approx(500.0)


# -- marked-to-market NAV ------------------------------------------------------

def _priced_client(tmp_path, monkeypatch, price: float = 100.0):
    """Client whose fills and default marks come from a settable price table."""
    from bot.alerting import BotAlerter

    prices = {}
    monkeypatch.setattr(ex, "get_current_price", lambda ticker: prices.get(ticker, price))
    client = ex.PaperExecutionClient(ledger_path=tmp_path / "ledger.jsonl",
                                     alerter=BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl"))
    return client, prices


def _five_pct_decision(ticker="AAPL"):
    from risk.limits import RiskLimits
    return _approved_decision(ticker=ticker, calibrated_proba=0.99, limits=RiskLimits(max_position_pct=0.05))


def test_marked_nav_moves_on_non_exit_days_while_cash_basis_stays_put(isolated_kill_switch, tmp_path, monkeypatch):
    client, prices = _priced_client(tmp_path, monkeypatch)
    client.place_order("AAPL", "long", _five_pct_decision(), entry_date="2026-09-01")  # $5,000 at 100
    client.place_order("MSFT", "short", _five_pct_decision("MSFT"), entry_date="2026-09-01")

    day0 = client.marked_nav()
    assert day0.nav == pytest.approx(100_000.0)  # marked at the fill price on the entry day

    # Day 1: AAPL +10%, MSFT (short) +4% against us. Nothing closes.
    prices.update(AAPL=110.0, MSFT=104.0)
    day1 = client.marked_nav()
    assert day1.unrealized_pnl == pytest.approx(500.0 - 200.0)
    assert day1.nav == pytest.approx(100_300.0)
    assert day1.marks == {"AAPL": 110.0, "MSFT": 104.0} and day1.unmarked == []

    # Day 2: both move again; still no exit.
    prices.update(AAPL=95.0, MSFT=90.0)
    day2 = client.marked_nav()
    assert day2.nav == pytest.approx(100_000.0 - 250.0 + 500.0)

    # The cash-basis NAV -- the one sizing and the risk gate read -- never moved.
    assert day0.cash_basis_nav == day1.cash_basis_nav == day2.cash_basis_nav == client.nav() == 100_000.0
    assert len({day0.nav, day1.nav, day2.nav}) == 3


def test_marked_and_cash_basis_nav_agree_after_all_positions_close(isolated_kill_switch, tmp_path, monkeypatch):
    client, prices = _priced_client(tmp_path, monkeypatch)
    client.place_order("AAPL", "long", _five_pct_decision(), entry_date="2026-09-01")
    client.place_order("MSFT", "short", _five_pct_decision("MSFT"), entry_date="2026-09-01")
    prices.update(AAPL=112.0, MSFT=97.0)
    assert client.marked_nav().nav != pytest.approx(client.nav())

    client.close_position("AAPL", exit_date="2026-09-29")
    partly = client.marked_nav()
    assert partly.marks == {"MSFT": 97.0}  # a closed position is no longer marked
    client.close_position("MSFT", exit_date="2026-09-29")

    closed = client.marked_nav()
    assert closed.unrealized_pnl == 0.0 and closed.marks == {}
    assert closed.nav == pytest.approx(client.nav())
    assert closed.nav == pytest.approx(100_000.0 + client.realized_pnl)
    # ...and the last marks were exactly what closing realised, before its cost.
    record = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()][-1]
    assert partly.unrealized_pnl == pytest.approx(record["gross_pnl"])


def test_marked_nav_carries_an_unpriceable_position_at_cost(isolated_kill_switch, tmp_path, monkeypatch):
    client, _ = _priced_client(tmp_path, monkeypatch)
    client.place_order("AAPL", "long", _five_pct_decision(), entry_date="2026-09-01")

    def no_price(ticker):
        raise RuntimeError("yfinance returned nothing")

    marked = client.marked_nav(price_for=no_price)
    assert marked.unmarked == ["AAPL"] and marked.marks == {}
    assert marked.nav == client.nav()


def test_marked_nav_does_not_change_state_or_the_ledger(isolated_kill_switch, tmp_path, monkeypatch):
    client, prices = _priced_client(tmp_path, monkeypatch)
    client.place_order("AAPL", "long", _five_pct_decision(), entry_date="2026-09-01")
    ledger_before = (tmp_path / "ledger.jsonl").read_text()
    prices["AAPL"] = 80.0
    client.marked_nav()
    assert (tmp_path / "ledger.jsonl").read_text() == ledger_before
    assert client.nav() == 100_000.0 and client.high_water_mark == 100_000.0
    assert client.current_total_exposure_pct() == pytest.approx(0.05)
