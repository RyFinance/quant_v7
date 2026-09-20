import numpy as np
import pandas as pd
import pytest

from research.fundamentals import signals as sg
from research.fundamentals import evaluate as fe
from research.options_signals import evaluate as ev

CAL = pd.bdate_range("2010-01-01", "2012-12-31")


def test_acceptance_lag_next_trading_day():
    acc = pd.Series(["2011-02-10 16:30:00", "2011-02-11 09:00:00"])  # Thu, Fri
    pe = pd.Series(["2010-12-31", "2010-12-31"])
    out = sg.availability(acc, pe, pd.Series(["FY", "FY"]), CAL)
    assert out.iloc[0] == pd.Timestamp("2011-02-11")
    assert out.iloc[1] == pd.Timestamp("2011-02-14")  # skips weekend


def test_placeholder_acceptance_uses_fallback():
    acc = pd.Series(["2011-03-31 04:00:00", "2010-12-31 00:00:00"])
    pe = pd.Series(["2011-03-31", "2010-12-31"])
    out = sg.availability(acc, pe, pd.Series(["Q1", "FY"]), CAL)
    assert out.iloc[0] == CAL[CAL.searchsorted(pd.Timestamp("2011-05-15"), side="right")]
    assert out.iloc[1] == CAL[CAL.searchsorted(pd.Timestamp("2011-03-31"), side="right")]


def _q(shs, pes, avails):
    return pd.DataFrame({"pe": pd.to_datetime(pes), "avail": pd.to_datetime(avails), "shs": shs})


def test_split_guard_removes_raw_split():
    sp = pd.DataFrame({"eff": [pd.Timestamp("2010-09-01")], "ratio": [2.0]})
    q = _q([100.0, 206.0], ["2010-03-31", "2011-03-31"], ["2010-05-01", "2011-05-01"])
    f1 = sg.issuance_at(q, pd.Timestamp("2011-10-31"), sp)
    assert f1 == pytest.approx(np.log(1.03))
    # restated (already adjusted) counts are left alone
    q2 = _q([200.0, 206.0], ["2010-03-31", "2011-03-31"], ["2010-05-01", "2011-05-01"])
    assert sg.issuance_at(q2, pd.Timestamp("2011-10-31"), sp) == pytest.approx(np.log(1.03))
    # a small stock dividend is not treated as a split
    sp_small = pd.DataFrame({"eff": [pd.Timestamp("2010-09-01")], "ratio": [1.05]})
    assert sg.issuance_at(q, pd.Timestamp("2011-10-31"), sp_small) == pytest.approx(np.log(2.06))


def test_issuance_no_lookahead_and_skip():
    sp = pd.DataFrame(columns=["eff", "ratio"])
    q = _q([100.0, 110.0, 150.0], ["2010-03-31", "2011-03-31", "2011-06-30"],
           ["2010-05-01", "2011-05-01", "2011-12-15"])
    t = pd.Timestamp("2011-12-30")
    # before the June row is available, the March row is the latest
    assert sg.issuance_at(q, pd.Timestamp("2011-11-30"), sp) == pytest.approx(np.log(1.1))
    # period end must be <= t - 6 months
    assert np.isnan(sg.issuance_at(q, pd.Timestamp("2011-09-15"), sp))


def test_consistency_definition_and_lag():
    pes = pd.date_range("2003-12-31", periods=7, freq="YE")
    eps = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6]
    fy = pd.DataFrame({"pe": pes, "avail": pes + pd.Timedelta(days=60), "eps": eps})
    e = np.array(eps)
    g = [(e[i] - e[i - 1]) / (0.5 * (abs(e[i - 1]) + abs(e[i - 2]))) for i in range(2, 7)]
    t = pes[-1] + pd.Timedelta(days=61)
    assert sg.consistency_at(fy, t) == pytest.approx(np.mean(g))
    assert np.isnan(sg.consistency_at(fy, pes[-1] + pd.Timedelta(days=30)))  # 7th year not yet filed
    fy2 = fy.copy(); fy2.loc[6, "eps"] = 1.45  # growth flips sign -> dropped
    assert np.isnan(sg.consistency_at(fy2, t))
    fy3 = fy.copy(); fy3.loc[6, "eps"] = 20.0  # > 600% -> dropped
    assert np.isnan(sg.consistency_at(fy3, t))


def test_costs_in_backtest():
    cal = pd.bdate_range("2020-01-01", periods=60)
    names = [f"S{i}" for i in range(30)]
    opens = pd.DataFrame(100.0, index=cal, columns=names)
    closes = opens.copy()
    dates = pd.DatetimeIndex([cal[0], cal[20], cal[40]])
    score = pd.DataFrame(np.tile(np.arange(30.0), (3, 1)), index=dates, columns=names)
    rf = pd.Series(0.0001, index=cal)
    base = ev.backtest(score, opens, closes, dates, cal, rf, ev.COSTS["base"])
    first = base.iloc[0]
    assert first["gross"] == 0 and first["turnover"] == pytest.approx(2.0)
    days = (first["exit"] - first["entry"]).days
    assert first["net"] == pytest.approx(-(2.0 * 0.0005) - 1.0 * 0.005 * days / 365)
    stress = ev.backtest(score, opens, closes, dates, cal, rf, ev.COSTS["stress"])
    assert stress.iloc[0]["proceeds_drag"] > 0 and stress.iloc[1]["cost"] == pytest.approx(0.0)


def test_validation_locked_without_unlock():
    if not (fe.ROOT / fe.UNLOCK).exists():
        assert not fe.validation_unlocked()
