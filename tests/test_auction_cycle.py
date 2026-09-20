import numpy as np
import pandas as pd
import pytest

from research.auction_cycle import evaluate as ev
from research.auction_cycle import signals as sg


def _cal(n=40):
    return pd.bdate_range("2021-03-01", periods=n)


def test_event_windows_alignment():
    t = _cal()
    a = t[[20]]
    w = sg.windows(t, a)
    assert list(np.flatnonzero(w["pre"])) == [16, 17, 18, 19, 20]  # close a-5 -> close a
    assert list(np.flatnonzero(w["post"])) == [21, 22, 23]


def test_positions_disjoint_and_combined():
    t = _cal()
    a = t[[10, 13]]  # clustered auctions: day 11-13 are post of 10 and pre of 13
    p = sg.positions(t, a)
    assert (p.loc[t[11:14], "A1_pre_short"] == -1).all()
    assert (p.loc[t[11:14], "A2_post_long"] == 0).all()
    assert list(np.flatnonzero(p["A2_post_long"] == 1)) == [14, 15, 16]
    assert (p["A3_combined"] == p["A1_pre_short"] + p["A2_post_long"]).all()
    assert set(p["A3_combined"].unique()) <= {-1.0, 0.0, 1.0}


def test_non_trading_auction_maps_forward_and_beyond_end():
    t = _cal(10)
    sat = t[4] + pd.Timedelta(days=1)  # Saturday after a Friday? use a date not in t
    assert sat not in t
    idx = sg.auction_index(pd.DatetimeIndex([sat]), t)
    assert t[idx[0]] > sat
    # auction 2 bdays after the calendar end still marks the last pre days
    beyond = pd.bdate_range(t[-1], periods=3)[-1]
    w = sg.windows(t, pd.DatetimeIndex([beyond]))
    assert list(np.flatnonzero(w["pre"])) == [7, 8, 9]


def test_no_lookahead_positions_do_not_depend_on_prices():
    t = _cal()
    a = t[[20]]
    p1 = sg.positions(t, a)
    p2 = sg.positions(t[:22], a)  # truncating the price calendar after the auction
    assert p1.loc[t[:21]].equals(p2.loc[t[:21]])


def test_backtest_timing_and_costs():
    t = _cal(6)
    w = pd.Series([0, -1, -1, 1, 0, 0], index=t, dtype=float)
    xr = pd.Series([0.01, 0.002, -0.001, 0.003, 0.004, 0.005], index=t)
    c = 0.0002
    net = ev.backtest(w, xr, c)
    exp = w * xr - c * np.array([0, 1, 0, 2, 1, 0])
    assert np.allclose(net, exp)
    lag = ev.backtest(w, xr, 0.0, lag=1)
    assert np.allclose(lag, w.shift(1).fillna(0) * xr)


def test_dev_truncation():
    x = ev.excess("IEF", ev.DEV_END)
    assert x.index.max() <= ev.DEV_END


def test_amendment1_fiscal_mapping():
    f = sg.fiscal_auctions()
    assert pd.Timestamp("2019-06-21") not in set(f.date)       # same-day announced, dropped
    r = f[f.date == pd.Timestamp("2015-05-26")]
    assert set(r.tenor) == {2}                                   # reopened old 5y sold as 2y
    assert set(f.tenor) <= {2, 3, 5, 7, 10, 30}


def test_validation_locked_without_unlock():
    if not ev.validation_unlocked():
        with pytest.raises(SystemExit):
            ev.run("validation")
