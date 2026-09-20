import numpy as np
import pandas as pd
import pytest

from research.share_class import pair_targets, simulate


def test_financing_uses_short_collateral_and_costs_hit_both_sides():
    dates = pd.bdate_range('2020-01-01', periods=3)
    p = pd.DataFrame({'A': 10., 'B': 10.}, index=dates)
    t = pd.DataFrame({'A': [1., np.nan, np.nan], 'B': [-1., np.nan, np.nan]}, index=dates)
    rf = pd.Series(.001, index=dates)
    d = simulate(p,p,t,rf,[[0,1]],cost=0,borrow=0,debit_spread=0,start=str(dates[1].date()))
    # Initial free cash earns on first day; entry collateral consumes all free cash thereafter.
    assert d.nav.tolist() == pytest.approx([1.001,1.001])
    t *= 2
    d = simulate(p,p,t,rf,[[0,1]],cost=0,borrow=0,debit_spread=0,start=str(dates[1].date()))
    assert d.nav.tolist() == pytest.approx([1.001,1.001*(1-.001)])


def test_pair_is_atomic_when_one_entry_missing():
    dates=pd.bdate_range('2020-01-01',periods=3)
    p=pd.DataFrame({'A':[10.,np.nan,10.],'B':[10.,10.,10.]},index=dates)
    t=pd.DataFrame({'A':[1.,np.nan,np.nan],'B':[-1.,np.nan,np.nan]},index=dates)
    d=simulate(p,p,t,pd.Series(0.,index=dates),[[0,1]],cost=10,borrow=.03,start=str(dates[1].date()))
    assert d.nav.tolist()==[1.,1.]


def test_actual_units_retained_and_exit_costs_reconcile():
    dates=pd.bdate_range('2020-01-01',periods=4)
    p=pd.DataFrame({'A':[10.,10.,11.,12.],'B':[10.,10.,10.,10.]},index=dates)
    t=pd.DataFrame({'A':[1.,np.nan,0.,np.nan],'B':[-1.,np.nan,0.,np.nan]},index=dates)
    d=simulate(p,p,t,pd.Series(0.,index=dates),[[0,1]],cost=10,borrow=0,debit_spread=0,start=str(dates[1].date()))
    entry_nav=1/1.001
    assert d.nav.iloc[1]==pytest.approx(entry_nav*1.1)
    assert d.nav.iloc[-1]==pytest.approx(entry_nav*(1.2-.0005*2.2))


def test_pair_signal_causal():
    dates=pd.bdate_range('2014-01-01',periods=500)
    p=pd.DataFrame({'A':100+np.sin(np.arange(500)/20),'B':100.},index=dates)
    a=pair_targets(p)
    p.iloc[400:,0]*=2
    b=pair_targets(p)
    pd.testing.assert_frame_equal(a.iloc[:400],b.iloc[:400])
