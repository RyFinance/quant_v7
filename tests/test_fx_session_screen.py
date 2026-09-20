import numpy as np
import pandas as pd
import pytest

from research.fx_session_screen import local_session, simulate, trade_cost, usd_pnl_fraction


def test_usd_quote_and_base_pnl_conversion():
    assert usd_pnl_fraction('EURUSD', 1.2, 1.32, 1) == pytest.approx(.1)
    assert usd_pnl_fraction('USDJPY', 100, 110, 1) == pytest.approx(10 / 110)
    assert usd_pnl_fraction('USDJPY', 100, 90, -1) == pytest.approx(10 / 90)


def test_fees_both_sides_and_minimum_commissions():
    costs = dict(spread_slippage_bps_per_side=.5,
                 commission_bps_per_side=.2, minimum_commission_usd_per_order=2)
    assert trade_cost('EURUSD', 1, 1.1, 10000, costs) == pytest.approx(5.05)
    assert trade_cost('USDJPY', 100, 110, 10000, costs) == pytest.approx(5)


def test_signal_has_no_future_information_and_handles_dst():
    idx = pd.date_range('2012-01-01', '2012-06-01', freq='h', tz='UTC')
    p = 1 + np.sin(np.arange(len(idx)) / 17) / 100
    d = pd.DataFrame({'open': p, 'close': p + .0001}, index=idx)
    # Real FX closes during the Sunday DST change; remove weekends for pivot.
    d = d[d.index.weekday < 5]
    cal = pd.bdate_range('2012-01-01', '2012-06-01')
    op, before = local_session(d, 'Europe/London', cal)
    altered = d.copy()
    altered.loc[altered.index >= '2012-05-01'] *= 4
    _, after = local_session(altered, 'Europe/London', cal)
    pd.testing.assert_series_equal(before.loc[:'2012-04-30'], after.loc[:'2012-04-30'])
    assert op.loc['2012-04-02', 9] == d.loc['2012-04-02 08:00:00+00:00', 'open']
    assert op.loc['2012-03-23', 9] == d.loc['2012-03-23 09:00:00+00:00', 'open']


def test_fixed_units_compounding_and_fees_reconcile():
    orders = pd.DataFrame([dict(date=pd.Timestamp('2010-01-04'), symbol='EURUSD',
                               side=1, entry=1, exit=1.03, gross_fraction=.03)])
    cost = dict(spread_slippage_bps_per_side=0, commission_bps_per_side=0,
                minimum_commission_usd_per_order=2)
    daily, fills = simulate(orders, cost)
    assert daily.loc['2010-01-04', 'nav'] == pytest.approx(100996)
    assert daily.iloc[-1]['nav'] == pytest.approx(100996)
    assert fills.gross_pnl_usd.sum() - fills.cost_usd.sum() == pytest.approx(daily.iloc[-1]['nav'] - 100000)
