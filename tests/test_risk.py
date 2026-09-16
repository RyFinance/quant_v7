"""Tests for Part E (risk/kelly.py, risk/limits.py, risk/adaptive_exits.py,
risk/transaction_costs.py). Payoff-ratio estimation uses real cached
labeled signal data (data/labeled_features.parquet via the training
partition) -- this is also a regression test for a real bug caught during
this build: an earlier MIN_PAYOFF_RATIO floor (0.05) was silently
overriding the true ~0.025 estimate computed from real data.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.validation import split_time_disjoint_panel
from risk.kelly import estimate_payoff_ratio, kelly_fraction, fractional_kelly_size, MIN_PAYOFF_RATIO
from risk.limits import RiskLimits, check_risk_limits
from risk.adaptive_exits import adaptive_exit_thresholds, check_exit
from risk.transaction_costs import cost_as_return, round_trip_cost_bps
from schemas.reason_codes import DecisionReason

DATA_PATH = Path(__file__).parent.parent / "data" / "labeled_features.parquet"


@pytest.fixture(scope="module")
def train_partition():
    if not DATA_PATH.exists():
        pytest.skip("labeled_features.parquet not built yet")
    df = pd.read_parquet(DATA_PATH)
    parts, _ = split_time_disjoint_panel(df, holding_period=5)
    return parts["train"]


def test_payoff_ratio_matches_manual_calculation(train_partition):
    """Regression test for the MIN_PAYOFF_RATIO floor bug: the estimate must
    match a hand computation on the same real data, not get silently clamped."""
    label_col = "label_cost_adjusted"
    wins = train_partition.loc[train_partition[label_col] == 1, "position_return"]
    losses = train_partition.loc[train_partition[label_col] == 0, "position_return"]
    expected_avg_win = wins[wins > 0].mean()
    expected_avg_loss_abs = losses[losses < 0].abs().mean()

    payoff = estimate_payoff_ratio(train_partition, label_col)
    assert np.isclose(payoff.avg_win, expected_avg_win)
    assert np.isclose(payoff.avg_loss_abs, expected_avg_loss_abs)
    assert payoff.avg_loss_abs > MIN_PAYOFF_RATIO * 10  # not sitting on the degenerate floor
    assert np.isclose(payoff.b, expected_avg_win / expected_avg_loss_abs)


def test_kelly_fraction_zero_at_fifty_fifty():
    # p=0.5, any finite b -> f* = 0.5 - 0.5/b; only exactly 0 when b=1
    assert kelly_fraction(0.5, b=1.0) == pytest.approx(0.0, abs=1e-9)


def test_kelly_fraction_negative_edge_clips_to_zero():
    assert kelly_fraction(0.2, b=1.0) == 0.0  # p < 1/(1+b) -> negative raw Kelly -> clipped


def test_kelly_fraction_monotonic_in_probability():
    p = np.array([0.3, 0.4, 0.5, 0.6, 0.7])
    f = kelly_fraction(p, b=1.2)
    assert np.all(np.diff(f) >= 0)


def test_fractional_kelly_respects_position_ceiling():
    sized = fractional_kelly_size(p=0.99, b=5.0, kelly_fraction_mult=1.0, max_position_fraction=0.10)
    assert sized <= 0.10 + 1e-9


def test_fractional_kelly_smaller_than_full_kelly():
    p, b = 0.6, 1.2
    full = kelly_fraction(p, b)
    quarter = fractional_kelly_size(p, b, kelly_fraction_mult=0.25, max_position_fraction=1.0)
    assert quarter == pytest.approx(0.25 * full)


def test_risk_limits_block_on_daily_loss():
    result = check_risk_limits(0.02, current_total_exposure_pct=0.1, current_daily_pnl_pct=-0.05)
    assert result.allowed is False
    assert result.reason == DecisionReason.RISK_BLOCKED


def test_risk_limits_block_on_position_size():
    result = check_risk_limits(0.5, current_total_exposure_pct=0.0, current_daily_pnl_pct=0.0)
    assert result.allowed is False


def test_risk_limits_block_on_total_exposure():
    result = check_risk_limits(0.05, current_total_exposure_pct=0.58, current_daily_pnl_pct=0.0)
    assert result.allowed is False


def test_risk_limits_allow_within_bounds():
    result = check_risk_limits(0.03, current_total_exposure_pct=0.2, current_daily_pnl_pct=0.0)
    assert result.allowed is True
    assert result.reason is None


def test_adaptive_exits_tighten_over_holding_period():
    t0 = adaptive_exit_thresholds(entry_deviation=0.02, cluster_std_return=0.01, day_in_holding=0, holding_period=5)
    t5 = adaptive_exit_thresholds(entry_deviation=0.02, cluster_std_return=0.01, day_in_holding=5, holding_period=5)
    assert t5.take_profit_return < t0.take_profit_return
    assert t5.stop_loss_return < t0.stop_loss_return
    assert t5.tighten_factor < t0.tighten_factor


def test_adaptive_exits_scale_with_signal_strength():
    weak = adaptive_exit_thresholds(entry_deviation=0.005, cluster_std_return=0.01, day_in_holding=0, holding_period=5)
    strong = adaptive_exit_thresholds(entry_deviation=0.03, cluster_std_return=0.01, day_in_holding=0, holding_period=5)
    assert strong.take_profit_return > weak.take_profit_return


def test_check_exit_take_profit_and_stop_loss():
    th = adaptive_exit_thresholds(entry_deviation=0.02, cluster_std_return=0.01, day_in_holding=0, holding_period=5)
    assert check_exit(th.take_profit_return + 0.001, th) == "take_profit"
    assert check_exit(-(th.stop_loss_return + 0.001), th) == "stop_loss"
    assert check_exit(0.0, th) is None


def test_transaction_cost_helpers():
    assert cost_as_return(10.0) == pytest.approx(0.001)
    assert round_trip_cost_bps() == 10.0
