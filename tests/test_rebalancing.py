import numpy as np
import pandas as pd
import pytest

from research.rebalancing import evaluate as ev
from research.rebalancing import signals as sg


def synth(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-04", periods=n)
    return pd.DataFrame({"SPY": rng.normal(0, 0.012, n), "IEF": rng.normal(0, 0.004, n)}, index=idx)


def test_drift_matches_paper_example():
    # equity +10%, bonds flat: 66/106 = 62.26%
    s = sg.threshold_signal(np.array([0.10]), np.array([0.0]), delta=0.05)
    assert s[0] == pytest.approx(66 / 106 - 0.6)


def test_threshold_resets_after_breach():
    re, rb = np.array([0.10, 0.0]), np.array([0.0, 0.0])
    s = sg.threshold_signal(re, rb, delta=0.02)
    assert s[0] > 0.02 and s[1] == pytest.approx(0.0)
    s_wide = sg.threshold_signal(re, rb, delta=0.05)
    assert s_wide[1] == pytest.approx(s_wide[0])


def test_no_lookahead_in_positions():
    r = synth()
    base = sg.positions(r)
    k = 200
    r2 = r.copy()
    r2.iloc[k + 1:] = r2.iloc[k + 1:] * -3 + 0.02
    alt = sg.positions(r2)
    # up to and including day k, nothing may change (month-end flags depend only on the calendar)
    pd.testing.assert_frame_equal(base.iloc[: k + 1], alt.iloc[: k + 1])


def test_calendar_resets_on_last_trading_day_and_week4():
    r = synth(120)
    cal = sg.calendar_signal(r)
    mp = sg.month_position(r.index)
    last_days = r.index[mp["from_end"] == 0]
    d = last_days[1]
    nxt = r.index[r.index.get_loc(d) + 1]
    expect = sg._drift(0.6, r.loc[nxt, "SPY"], r.loc[nxt, "IEF"]) - 0.6
    assert cal.loc[nxt] == pytest.approx(expect)
    pos = sg.calendar_position(r, cal)
    i = r.index.get_loc(d)
    for j in range(i - 4, i + 1):
        assert pos.iloc[j] == np.sign(-cal.iloc[j])
    assert pos.iloc[i - 5] == 0.0
    assert pos.iloc[i + 1] == np.sign(cal.iloc[i + 1 - 4])  # first day of month: sign(Cal_{t-4})
    assert pos.iloc[i + 2] == 0.0


def test_partial_final_month_uses_calendar_not_data_end():
    idx = pd.bdate_range("2026-09-01", "2026-09-18")
    mp = sg.month_position(idx)
    assert (mp["from_end"] >= 5).all()  # Sept 2026 has trading days after the 18th


def test_backtest_alignment_and_costs():
    idx = pd.bdate_range("2020-01-01", periods=4)
    w = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    r = pd.Series([0.01, 0.02, 0.03, 0.04], index=idx)
    net = ev.backtest(w, r, per_side=0.0)
    assert list(net.round(10)) == [0.0, 0.0, 0.03, 0.04]
    c = 0.0002
    net_c = ev.backtest(w, r, per_side=c)
    assert net_c.iloc[2] == pytest.approx(0.03 - 2 * c)   # entry at close of day 1, cost on day 2
    assert net_c.iloc[3] == pytest.approx(0.04)           # no change at close of day 2
    lag = ev.backtest(w, r, per_side=0.0, lag=1)
    assert lag.iloc[3] == pytest.approx(0.04) and lag.iloc[2] == 0.0


def test_validation_locked_without_unlock(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    monkeypatch.setattr(ev, "PREREG", tmp_path / "prereg.jsonl")
    assert not ev.validation_unlocked()
