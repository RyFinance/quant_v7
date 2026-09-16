"""Tests for bot/risk_gate.py -- the single choke point every paper order
must pass through. Kill-switch sentinel is isolated to tmp_path per test.
"""
from __future__ import annotations

import pytest

import bot.kill_switch as ks
import bot.risk_gate as rg
from schemas.reason_codes import DecisionReason


@pytest.fixture
def isolated_kill_switch(tmp_path, monkeypatch):
    sentinel = tmp_path / "KILL_SWITCH"
    monkeypatch.setattr(ks, "KILL_SWITCH_FILE", sentinel)
    # Regression fix (2026-08-19): rg.evaluate() calls build_alerter() on
    # every denied/approved decision, which previously defaulted to the
    # REAL production bot/state/bot_alerts.jsonl -- every test run in this
    # file was silently appending fake kill-switch/risk-blocked alerts to
    # the real bot's alert log. Isolate it the same way KILL_SWITCH_FILE
    # already is here.
    from bot.alerting import BotAlerter
    monkeypatch.setattr(rg, "build_alerter", lambda: BotAlerter(webhook_url="", alerts_path=tmp_path / "alerts.jsonl"))
    return sentinel


def _evaluate(**overrides):
    defaults = dict(
        ticker="AAPL", calibrated_proba=0.65, payoff_ratio_b=1.2,
        current_total_exposure_pct=0.0, current_daily_pnl_pct=0.0,
        paper_nav=100_000.0, paper_high_water_mark=100_000.0,
        breaker_tier="armed",
    )
    defaults.update(overrides)
    return rg.evaluate(**defaults)


def test_approved_order_mints_single_use_token(isolated_kill_switch):
    decision = _evaluate()
    assert decision.allowed is True
    assert decision.reason == DecisionReason.EXECUTED
    assert decision.approval_token is not None
    assert decision.size_fraction > 0

    assert rg.consume_approval(decision.approval_token) is True
    # single-use: a second attempt to spend the SAME token must fail
    assert rg.consume_approval(decision.approval_token) is False


def test_fabricated_token_is_rejected(isolated_kill_switch):
    assert rg.consume_approval("not-a-real-token") is False
    assert rg.consume_approval(None) is False


def test_denied_decision_carries_no_token(isolated_kill_switch):
    decision = _evaluate(breaker_tier="halt_new_entries")
    assert decision.allowed is False
    assert decision.approval_token is None


def test_kill_switch_blocks_before_anything_else(isolated_kill_switch):
    ks.engage_kill_switch("test halt")
    # even parameters that would otherwise clearly pass must be blocked
    decision = _evaluate(calibrated_proba=0.99, payoff_ratio_b=5.0)
    assert decision.allowed is False
    assert decision.approval_token is None
    assert "kill switch" in decision.detail


def test_drawdown_cap_breach_auto_engages_kill_switch(isolated_kill_switch):
    assert ks.is_kill_switch_engaged() is False
    decision = _evaluate(paper_nav=70_000.0, paper_high_water_mark=100_000.0)  # 30% > 20% default cap
    assert decision.allowed is False
    assert ks.is_kill_switch_engaged() is True  # the gate itself tripped the switch

    # a subsequent order, even a well-sized one, is now blocked by the switch itself
    decision2 = _evaluate(paper_nav=100_000.0, paper_high_water_mark=100_000.0)
    assert decision2.allowed is False
    assert "kill switch" in decision2.detail


def test_circuit_breaker_tier_blocks_new_entries(isolated_kill_switch):
    decision = _evaluate(breaker_tier="halt_new_entries")
    assert decision.allowed is False
    assert decision.reason == DecisionReason.CIRCUIT_BREAKER_HALT


def test_circuit_breaker_full_flatten_blocks_new_entries(isolated_kill_switch):
    decision = _evaluate(breaker_tier="full_flatten")
    assert decision.allowed is False
    assert decision.reason == DecisionReason.CIRCUIT_BREAKER_HALT


def test_no_conviction_blocks_when_kelly_size_zero(isolated_kill_switch):
    # p below breakeven for b -> negative raw Kelly -> clipped to 0
    decision = _evaluate(calibrated_proba=0.1, payoff_ratio_b=1.0)
    assert decision.allowed is False
    assert decision.reason == DecisionReason.NO_CONVICTION


def test_risk_limits_block_oversized_total_exposure(isolated_kill_switch):
    decision = _evaluate(current_total_exposure_pct=0.59, calibrated_proba=0.9, payoff_ratio_b=3.0)
    assert decision.allowed is False
    assert decision.reason == DecisionReason.RISK_BLOCKED


def test_risk_limits_block_daily_loss_cap(isolated_kill_switch):
    decision = _evaluate(current_daily_pnl_pct=-0.05)  # past default -3% cap
    assert decision.allowed is False
    assert decision.reason == DecisionReason.RISK_BLOCKED


def test_current_breaker_tier_runs_against_real_cached_data():
    """Real (non-mocked) call against the cached Phase-1 universe parquet
    files -- no network required, load_universe reads local parquet."""
    tier, detail = rg.current_breaker_tier()
    assert tier in {"armed", "halt_new_entries", "full_flatten"}
    assert isinstance(detail, dict)
