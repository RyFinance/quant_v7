"""Tests for bot/kill_switch.py -- the bottom of the paper-bot risk stack.
Sentinel-file path is isolated to tmp_path per test (never touches the
real bot/state/KILL_SWITCH file a developer might have set).
"""
from __future__ import annotations

import pytest

import bot.kill_switch as ks


@pytest.fixture
def isolated_kill_switch(tmp_path, monkeypatch):
    sentinel = tmp_path / "KILL_SWITCH"
    monkeypatch.setattr(ks, "KILL_SWITCH_FILE", sentinel)
    return sentinel


def test_kill_switch_default_clear(isolated_kill_switch):
    assert ks.is_kill_switch_engaged() is False


def test_engage_and_disengage_kill_switch(isolated_kill_switch):
    ks.engage_kill_switch("test reason")
    assert ks.is_kill_switch_engaged() is True
    status = ks.read_kill_switch_status()
    assert status.engaged is True
    assert status.reason == "test reason"
    assert status.engaged_at is not None

    ks.disengage_kill_switch()
    assert ks.is_kill_switch_engaged() is False


def test_disengage_when_already_clear_is_noop(isolated_kill_switch):
    ks.disengage_kill_switch()  # must not raise
    assert ks.is_kill_switch_engaged() is False


def test_engage_is_idempotent(isolated_kill_switch):
    ks.engage_kill_switch("first")
    ks.engage_kill_switch("second")
    assert ks.is_kill_switch_engaged() is True


def test_drawdown_cap_not_breached_below_threshold():
    check = ks.check_capital_drawdown_cap(current_nav=95_000.0, high_water_mark=100_000.0, max_drawdown_pct=0.20)
    assert check.breached is False


def test_drawdown_cap_breached_at_threshold():
    check = ks.check_capital_drawdown_cap(current_nav=79_000.0, high_water_mark=100_000.0, max_drawdown_pct=0.20)
    assert check.breached is True


def test_drawdown_cap_exactly_at_threshold_breaches():
    # HARD FAIL-SAFE stance: >= the cap breaches, not only strictly past it.
    check = ks.check_capital_drawdown_cap(current_nav=80_000.0, high_water_mark=100_000.0, max_drawdown_pct=0.20)
    assert check.breached is True


def test_drawdown_cap_no_high_water_mark_yet_never_breaches():
    check = ks.check_capital_drawdown_cap(current_nav=100.0, high_water_mark=0.0, max_drawdown_pct=0.20)
    assert check.breached is False
