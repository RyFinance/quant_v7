"""Tests for Part H (backtest/engine.py, backtest/metrics.py). Position-
outcome and simulation tests use real cached data (labeled_features.parquet,
residual_returns_wide.parquet). Metric-math tests use small hand-built
return series (SYNTHETIC -- exact-answer checks on the formulas themselves).
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engine import precompute_position_outcomes, simulate_portfolio
from backtest.metrics import compute_metrics

DATA_DIR = Path(__file__).parent.parent / "data"
pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "labeled_features.parquet").exists() or not (DATA_DIR / "residual_returns_wide.parquet").exists(),
    reason="backtest input caches not built yet",
)


@pytest.fixture(scope="module")
def small_slice():
    df = pd.read_parquet(DATA_DIR / "labeled_features.parquet")
    resid = pd.read_parquet(DATA_DIR / "residual_returns_wide.parquet")
    recent = df[df["date"] >= df["date"].max() - pd.Timedelta(days=120)]
    return recent, resid


def test_position_outcomes_exit_day_within_holding_period(small_slice):
    candidates, resid = small_slice
    out = precompute_position_outcomes(candidates, resid, holding_period=5)
    assert out["exit_day"].between(1, 5).all()
    assert len(out) > 0


def test_position_outcomes_realized_return_matches_manual_walk(small_slice):
    """Regenerate one row's outcome by hand and check it matches."""
    candidates, resid = small_slice
    out = precompute_position_outcomes(candidates, resid, holding_period=5)
    row = out.iloc[0]
    ticker, date = row["ticker"], row["date"]
    direction = np.sign(row["signal"])
    idx = resid.index.get_loc(date)

    cumulative = 0.0
    expected_exit_day, expected_return = 5, None
    for day in range(1, 6):
        cumulative += direction * resid[ticker].iloc[idx + day]
        tighten = 1.0 - 0.5 * (day / 5)
        tp = 0.5 * abs(row["deviation"]) * tighten
        sl = 2.0 * abs(row["cluster_std_return"]) * tighten
        if cumulative >= tp or cumulative <= -sl:
            expected_exit_day, expected_return = day, cumulative
            break
    else:
        expected_return = cumulative

    assert row["exit_day"] == expected_exit_day
    assert np.isclose(row["realized_return"], expected_return, atol=1e-9)


def test_simulate_portfolio_blocks_new_entries_when_not_armed(small_slice):
    candidates, resid = small_slice
    out = precompute_position_outcomes(candidates, resid, holding_period=5)
    proba = np.full(len(out), 0.9)  # maximal conviction -> would trade heavily if allowed
    all_halted = {d: "halt_new_entries" for d in out["date"].unique()}
    result = simulate_portfolio(out, proba, payoff_ratio_b=1.0, breaker_tier_by_date=all_halted, cost_bps=10.0)
    assert result.n_trades == 0
    assert result.n_blocked_by_circuit_breaker == len(out)


def test_simulate_portfolio_trades_when_armed_and_confident(small_slice):
    candidates, resid = small_slice
    out = precompute_position_outcomes(candidates, resid, holding_period=5)
    proba = np.full(len(out), 0.9)
    all_armed = {d: "armed" for d in out["date"].unique()}
    result = simulate_portfolio(out, proba, payoff_ratio_b=1.0, breaker_tier_by_date=all_armed, cost_bps=10.0)
    assert result.n_trades > 0


def test_simulate_portfolio_respects_max_position_ceiling(small_slice):
    from risk.limits import RiskLimits
    candidates, resid = small_slice
    out = precompute_position_outcomes(candidates, resid, holding_period=5)
    proba = np.full(len(out), 0.99)
    all_armed = {d: "armed" for d in out["date"].unique()}
    limits = RiskLimits(max_position_pct=0.05, max_daily_loss_pct=0.03, max_total_exposure_pct=0.60)
    result = simulate_portfolio(out, proba, payoff_ratio_b=5.0, breaker_tier_by_date=all_armed, cost_bps=10.0, risk_limits=limits)
    assert all(t.size_fraction <= 0.05 + 1e-9 for t in result.trades)


def test_zero_cost_beats_or_equals_high_cost(small_slice):
    """A given trade set's return should never IMPROVE as cost increases."""
    candidates, resid = small_slice
    out = precompute_position_outcomes(candidates, resid, holding_period=5)
    proba = np.full(len(out), 0.7)
    all_armed = {d: "armed" for d in out["date"].unique()}
    r0 = simulate_portfolio(out, proba, 1.0, all_armed, cost_bps=0.0)
    r10 = simulate_portfolio(out, proba, 1.0, all_armed, cost_bps=10.0)
    assert r0.daily_returns.sum() >= r10.daily_returns.sum() - 1e-9


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def test_metrics_flat_returns_are_zero():
    flat = pd.Series([0.0] * 100)
    m = compute_metrics(flat, n_trades=0)
    assert m.annualized_return == 0.0
    assert m.sharpe_ratio == 0.0
    assert m.max_drawdown == 0.0


def test_metrics_all_positive_returns_have_zero_drawdown():
    positive = pd.Series([0.001] * 100)
    m = compute_metrics(positive, n_trades=10)
    assert m.max_drawdown == 0.0
    assert m.annualized_return > 0


def test_metrics_drawdown_matches_manual_calc():
    # SYNTHETIC: hand-built path with a known 20% peak-to-trough drawdown
    returns = pd.Series([0.10, -0.20, 0.05])  # nav: 1.10, 0.88, 0.924
    m = compute_metrics(returns, n_trades=5)
    nav = (1 + returns).cumprod()
    expected_dd = (nav.min() - nav.cummax().loc[nav.idxmin()]) / nav.cummax().loc[nav.idxmin()]
    assert np.isclose(m.max_drawdown, expected_dd, atol=1e-6)


def test_metrics_empty_series_handled():
    m = compute_metrics(pd.Series([], dtype=float), n_trades=0)
    assert m.n_days == 0
    assert m.sharpe_ratio == 0
