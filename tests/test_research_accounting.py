"""Synthetic exact-answer accounting tests; no synthetic research results."""
import numpy as np
import pandas as pd
import pytest

from backtest.metrics import compute_metrics
from backtest.research import ledger_mark_to_market, simulate_weights
from research.compare_strategies import event_targets, price_targets


def test_metrics_arithmetic_sharpe_downside_rms_and_initial_drawdown():
    r = pd.Series([-.1, .2, -.05])
    m = compute_metrics(r, 0)
    assert m.sharpe_ratio == pytest.approx(r.mean() / r.std() * np.sqrt(252), abs=5e-5)
    assert m.sortino_ratio == pytest.approx(r.mean() * 252 / np.sqrt((.1**2 + .05**2) / 3 * 252), abs=5e-5)
    assert m.max_drawdown == -.1
    assert compute_metrics(pd.Series([-.2]), 0).max_drawdown == -.2


def test_metrics_risk_free_and_invalid_returns():
    r = pd.Series([.01, -.01, .02])
    daily_rf = 1.05 ** (1 / 252) - 1
    m = compute_metrics(r, 0, annual_risk_free_rate=.05)
    assert m.sharpe_ratio == pytest.approx((r.mean() - daily_rf) / r.std() * np.sqrt(252), abs=5e-5)
    with pytest.raises(ValueError):
        compute_metrics(pd.Series([np.nan]), 0)


def test_next_open_execution_and_overnight_marking():
    dates = pd.bdate_range('2024-01-01', periods=4)
    op = pd.DataFrame({'X': [10., 20., 30., 30.]}, index=dates)
    cp = pd.DataFrame({'X': [10., 22., 33., 30.]}, index=dates)
    target = pd.DataFrame({'X': [1., np.nan, 0., np.nan]}, index=dates)
    out = simulate_weights(op, cp, target, dates[1], dates[-1], cost_bps=0,
                           gross_cap=1, position_cap=1, borrow_rate=0)
    # Buy at 20 (not 10), mark 22 then 33, sell at next open 30.
    assert out.nav.tolist() == pytest.approx([1.1, 1.65, 1.5])
    assert out['return'].iloc[1] == pytest.approx(.5)


def test_cost_charged_both_sides_and_caps_after_cost():
    dates = pd.bdate_range('2024-01-01', periods=3)
    p = pd.DataFrame({'X': [10., 10., 10.]}, index=dates)
    t = pd.DataFrame({'X': [1., np.nan, np.nan]}, index=dates)
    out = simulate_weights(p, p, t, dates[1], dates[-1], cost_bps=10,
                           gross_cap=.6, position_cap=.6)
    assert out.gross.iloc[0] == pytest.approx(.6)
    assert out.nav.iloc[-1] == pytest.approx((1 - .6 * .0005) / (1 + .6 * .0005))


def test_ledger_marks_open_loss_then_reconciles_exit():
    dates = pd.bdate_range('2024-01-01', periods=3)
    cp = pd.DataFrame({'X': [10., 5., 12.]}, index=dates)
    records = [dict(event='open', ticker='X', entry_date=str(dates[0].date()),
                    notional=100., fill_price=10., direction='long'),
               dict(event='close', ticker='X', exit_date=str(dates[-1].date()), exit_price=12.)]
    out = ledger_mark_to_market(records, cp, dates, cost_bps=0, borrow_rate=0, starting_capital=100)
    assert out.nav.tolist() == [100., 50., 120.]
    assert compute_metrics(out['return'], 1).max_drawdown == -.5


def test_causal_targets_unaffected_by_future_price_change():
    dates = pd.bdate_range('2020-01-01', periods=400)
    cp = pd.DataFrame({'X': np.linspace(10, 30, 400), 'Y': np.linspace(20, 22, 400)}, index=dates)
    before = price_targets({'close': cp})
    changed = cp.copy()
    changed.iloc[350:] *= 3
    after = price_targets({'close': changed})
    for name in before:
        pd.testing.assert_frame_equal(before[name].iloc[:350], after[name].iloc[:350])


def test_event_holding_period_counts_real_sessions():
    dates = pd.to_datetime(['2024-07-02', '2024-07-03', '2024-07-05', '2024-07-08', '2024-07-09'])
    cp = pd.DataFrame({'X': 10.}, index=dates)
    events = pd.DataFrame({'date': [dates[0]], 'ticker': ['X'], 'signal': [2.]})
    t = event_targets(cp, events, hold=2)
    # Close July 2 signal -> July 3 buy -> July 8 exit (July 4 holiday).
    assert t.X.tolist() == [.05, .05, 0., 0., 0.]


def test_missing_held_price_is_not_silently_zero_return():
    dates = pd.bdate_range('2024-01-01', periods=3)
    op = pd.DataFrame({'X': [10., 10., 10.]}, index=dates)
    cp = op.copy()
    cp.iloc[-1] = np.nan
    t = pd.DataFrame({'X': [.1, np.nan, np.nan]}, index=dates)
    with pytest.raises(ValueError, match='held price'):
        simulate_weights(op, cp, t, dates[1], dates[-1])


def test_initializes_from_last_known_target_without_future_target():
    dates = pd.bdate_range('2024-01-01', periods=5)
    p = pd.DataFrame({'X': [10., 10., 10., 11., 11.]}, index=dates)
    t = pd.DataFrame({'X': [.5, np.nan, np.nan, np.nan, .1]}, index=dates)
    out = simulate_weights(p, p, t, dates[2], dates[-1], cost_bps=0,
                           position_cap=.6, borrow_rate=0)
    assert out.nav.tolist() == pytest.approx([1., 1.05, 1.05])


def test_cash_interest_and_short_collateral_no_rebate():
    dates = pd.bdate_range('2024-01-01', periods=3)
    p = pd.DataFrame({'X': [10., 10., 10.]}, index=dates)
    rf = pd.Series(.001, index=dates)
    t = pd.DataFrame({'X': [-.5, np.nan, np.nan]}, index=dates)
    out = simulate_weights(p, p, t, dates[1], dates[-1], cost_bps=0,
                           position_cap=.6, borrow_rate=0, cash_returns=rf)
    # 100% initial equity earns on each day, extra short proceeds do not.
    assert out.nav.iloc[-1] == pytest.approx(1.001**2)
    long_t = -t
    long_out = simulate_weights(p, p, long_t, dates[1], dates[-1], cost_bps=0,
                                position_cap=.6, borrow_rate=0, cash_returns=rf)
    assert long_out.nav.iloc[-1] == pytest.approx(1.001 * (1 + .0005))


def test_beta_hedge_is_causal_and_gross_capped():
    from research.higher_sharpe import add_beta_hedge
    d = pd.bdate_range('2024-01-01', periods=2)
    t = pd.DataFrame({'X': [.6, np.nan], 'SPY': [0., np.nan]}, index=d)
    beta = pd.DataFrame({'X': [2., 10.], 'SPY': [1., 1.]}, index=d)
    h = add_beta_hedge(t, beta)
    assert h.iloc[0].abs().sum() == pytest.approx(.6)
    assert (h.iloc[0] * beta.iloc[0]).sum() == pytest.approx(0)
    assert h.iloc[1].isna().all()
