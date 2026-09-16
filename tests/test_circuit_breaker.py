"""Tests for Part F (circuit_breaker/triggers.py, breaker.py, alerts.py,
market_correlation.py). Trigger-math tests use small hand-built arrays
(SYNTHETIC -- exact-answer sanity checks on threshold comparisons, same
rationale as ml/metrics tests). The market-correlation and false-positive-
rate regression tests use real cached universe data.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from circuit_breaker.triggers import (
    TriggerCategory,
    check_correlation_spike_trigger,
    check_cluster_collapse_trigger,
    check_infrastructure_trigger,
    check_magnitude_trigger,
    check_speed_trigger,
    mean_pairwise_abs_correlation,
)
from circuit_breaker.breaker import CircuitBreakerState, ResponseTier
from circuit_breaker.alerts import CircuitBreakerAlerter, ALERT_HALT_NEW_ENTRIES


def test_magnitude_trigger_fires_on_index_move():
    returns = pd.Series({"AAPL": -0.01, "MSFT": 0.02})
    event = check_magnitude_trigger(returns, index_return=-0.07, single_asset_threshold=0.35, index_threshold=0.06)
    assert event.fired is True
    assert event.category == TriggerCategory.MAGNITUDE


def test_magnitude_trigger_fires_on_single_asset_move():
    returns = pd.Series({"AAPL": -0.40, "MSFT": 0.01})
    event = check_magnitude_trigger(returns, index_return=0.0, single_asset_threshold=0.35, index_threshold=0.06)
    assert event.fired is True


def test_magnitude_trigger_silent_on_calm_day():
    returns = pd.Series({"AAPL": -0.01, "MSFT": 0.015})
    event = check_magnitude_trigger(returns, index_return=0.005, single_asset_threshold=0.35, index_threshold=0.06)
    assert event.fired is False


def test_mean_pairwise_abs_correlation_known_matrix():
    m = np.array([[1.0, 0.5, 0.5], [0.5, 1.0, 0.5], [0.5, 0.5, 1.0]])
    assert mean_pairwise_abs_correlation(m) == pytest.approx(0.5)


def test_correlation_spike_trigger():
    fired = check_correlation_spike_trigger(0.75, spike_threshold=0.60)
    quiet = check_correlation_spike_trigger(0.40, spike_threshold=0.60)
    assert fired.fired is True
    assert quiet.fired is False


def test_cluster_collapse_trigger():
    collapsed = check_cluster_collapse_trigger(k_ev_today=10, k_ev_trailing_median=27, collapse_fraction=0.40)
    stable = check_cluster_collapse_trigger(k_ev_today=26, k_ev_trailing_median=27, collapse_fraction=0.40)
    assert collapsed.fired is True
    assert stable.fired is False


def test_infrastructure_trigger():
    fired = check_infrastructure_trigger(n_stale_tickers=10, n_total_tickers=75, stale_fraction_threshold=0.10)
    quiet = check_infrastructure_trigger(n_stale_tickers=1, n_total_tickers=75, stale_fraction_threshold=0.10)
    assert fired.fired is True
    assert quiet.fired is False


def test_speed_trigger_on_synthetic_flash_crash():
    """SYNTHETIC price path -- a real historical flash-crash intraday
    sequence is not available (documented limitation, see
    circuit_breaker/calibration_config.py). This constructs a price path
    that drops 5% in 3 minutes and recovers, to verify the mechanism
    itself fires correctly on a known, deliberately-extreme input."""
    times = pd.date_range("2024-01-01 09:30", periods=10, freq="1min")
    prices = pd.Series([100, 100, 99, 96, 95, 96, 98, 99, 100, 100], index=times)
    event = check_speed_trigger(prices, window_minutes=5, move_threshold=0.03)
    assert event.fired is True


def test_speed_trigger_silent_on_flat_prices():
    times = pd.date_range("2024-01-01 09:30", periods=10, freq="1min")
    prices = pd.Series([100 + 0.01 * i for i in range(10)], index=times)
    event = check_speed_trigger(prices, window_minutes=5, move_threshold=0.03)
    assert event.fired is False


# ---------------------------------------------------------------------------
# breaker state machine
# ---------------------------------------------------------------------------
def _event(category, fired, value=1.0, threshold=0.5):
    from circuit_breaker.triggers import TriggerEvent
    return TriggerEvent(category, fired, "test", value, threshold)


def test_breaker_stays_armed_with_no_triggers():
    breaker = CircuitBreakerState()
    for i in range(5):
        result = breaker.process_day(f"day{i}", [])
    assert result.tier == ResponseTier.ARMED


def test_breaker_halts_on_single_category():
    breaker = CircuitBreakerState()
    result = breaker.process_day("day0", [_event(TriggerCategory.MAGNITUDE, True)])
    assert result.tier == ResponseTier.HALT_NEW_ENTRIES


def test_breaker_full_flattens_on_two_categories_same_day():
    breaker = CircuitBreakerState()
    result = breaker.process_day("day0", [
        _event(TriggerCategory.MAGNITUDE, True), _event(TriggerCategory.STRUCTURAL, True),
    ])
    assert result.tier == ResponseTier.FULL_FLATTEN


def test_breaker_requires_consecutive_clean_days_to_rearm():
    breaker = CircuitBreakerState(cooldown_confirmation_days=3)
    breaker.process_day("day0", [_event(TriggerCategory.MAGNITUDE, True)])
    assert breaker.tier == ResponseTier.HALT_NEW_ENTRIES
    breaker.process_day("day1", [])
    breaker.process_day("day2", [])
    assert breaker.tier == ResponseTier.HALT_NEW_ENTRIES  # only 2 clean days, not yet 3
    result = breaker.process_day("day3", [])
    assert result.tier == ResponseTier.ARMED  # 3rd consecutive clean day -> re-armed


def test_breaker_resets_clean_day_counter_on_renewed_trigger():
    breaker = CircuitBreakerState(cooldown_confirmation_days=3)
    breaker.process_day("day0", [_event(TriggerCategory.MAGNITUDE, True)])
    breaker.process_day("day1", [])
    breaker.process_day("day2", [_event(TriggerCategory.MAGNITUDE, True)])  # re-fires, resets counter
    breaker.process_day("day3", [])
    breaker.process_day("day4", [])
    assert breaker.tier == ResponseTier.HALT_NEW_ENTRIES  # only 2 clean days since the reset


def test_breaker_never_downgrades_from_full_flatten_without_rearm():
    breaker = CircuitBreakerState(cooldown_confirmation_days=3)
    breaker.process_day("day0", [_event(TriggerCategory.MAGNITUDE, True), _event(TriggerCategory.STRUCTURAL, True)])
    assert breaker.tier == ResponseTier.FULL_FLATTEN
    result = breaker.process_day("day1", [_event(TriggerCategory.MAGNITUDE, True)])  # single trigger, milder
    assert result.tier == ResponseTier.FULL_FLATTEN  # does not downgrade to halt_new_entries


def test_alerter_writes_local_jsonl_without_webhook(tmp_path):
    import json
    log_path = tmp_path / "alerts.jsonl"
    alerter = CircuitBreakerAlerter(webhook_url="", alerts_path=log_path)
    assert alerter.enabled is False
    alerter.alert(ALERT_HALT_NEW_ENTRIES, "test halt", categories=["magnitude"])
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == ALERT_HALT_NEW_ENTRIES


# ---------------------------------------------------------------------------
# real-data regression: production calibration report reproducibility
# ---------------------------------------------------------------------------
CALIB_PATH = Path(__file__).parent.parent / "reports" / "circuit_breaker_calibration.json"


@pytest.mark.skipif(not CALIB_PATH.exists(), reason="run reports/run_circuit_breaker_calibration.py first")
def test_calibration_report_shows_covid_true_positive():
    import json
    report = json.loads(CALIB_PATH.read_text())
    assert report["production_backtest_75name_2015_2026"]["covid_window_true_positive"]["fired_at_least_once_during_covid"] is True


@pytest.mark.skipif(not CALIB_PATH.exists(), reason="run reports/run_circuit_breaker_calibration.py first")
def test_calibration_report_shows_2010_flash_crash_daily_bar_limitation():
    import json
    report = json.loads(CALIB_PATH.read_text())
    flash = report["legacy_tail_event_check_2005_2026"]["2010_flash_crash_day"]
    assert flash["magnitude_trigger_fires"] == 0  # documented limitation, not a silent gap
