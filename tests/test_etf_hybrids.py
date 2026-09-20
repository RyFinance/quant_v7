"""Tests for research/etf_hybrids: point-in-time universe, no look-ahead in the signals, costs."""
import numpy as np
import pandas as pd
import pytest

from research.etf_hybrids import evaluate as ev
from research.etf_hybrids import signals as sg


def synth_prices(start="1999-01-01", end="2004-12-31", names=("A", "B", "C", "D"), seed=0, late=None):
    rng = np.random.default_rng(seed)
    cal = pd.bdate_range(start, end)
    r = rng.normal(0.0003, 0.01, (len(cal), len(names)))
    px = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=cal, columns=list(names))
    if late:
        for t, d in late.items():
            px.loc[:pd.Timestamp(d) - pd.Timedelta(days=1), t] = np.nan
    return px


# -- point-in-time universe ----------------------------------------------------------------------------
def test_eligibility_needs_close_at_me_minus_13():
    px = synth_prices(late={"D": "2000-06-15"})
    me = sg.month_ends(px.index)
    el = sg.eligibility(px, me)
    first = el.index[el["D"]][0]
    # first close 2000-06-15 -> close at ME(2000-06) -> eligible at ME(2001-07)
    assert (first.year, first.month) == (2001, 7)
    assert el.loc[me[me < first], "D"].sum() == 0
    assert el.loc[me[me >= first], "D"].all()


def test_real_universe_first_eligible_dates_match_plan():
    panel = sg.load_panel(upto=pd.Timestamp("2020-12-31"), names=["XLB", "EWH", "EWT", "EFA", "EEM", "XLRE", "XLC", "SPY"])
    me = sg.month_ends(panel["adj_close"].index)
    el = sg.eligibility(panel["adj_close"], me)
    first = {t: str(el.index[el[t]][0].date()) for t in el.columns}
    assert first == {"XLB": "2000-01-31", "EWH": "1997-04-30", "EWT": "2001-07-31", "EFA": "2002-09-30",
                     "EEM": "2004-05-28", "XLRE": "2016-11-30", "XLC": "2019-07-31", "SPY": "1994-02-28"}


def test_load_panel_truncates_before_anything():
    p = sg.load_panel(upto=pd.Timestamp("2014-12-31"), names=["SPY", "XLK"])
    for f in p.values():
        assert f.index.max() <= pd.Timestamp("2014-12-31")


# -- no look-ahead -------------------------------------------------------------------------------------
def _signals(px, rf):
    panel = {"adj_close": px, "adj_open": px, "close": px}
    return sg.signal_panels(panel, rf)


def test_signals_ignore_prices_after_signal_date():
    px = synth_prices(start="1990-01-01", end="2004-12-31", names=tuple(sg.UNIVERSE))
    rf = pd.Series(0.0001, index=px.index)
    me = sg.month_ends(px.index)
    k = len(me) - 10
    d = me[k]
    base = _signals(px, rf)
    alt_px = px.copy()
    alt_px.loc[alt_px.index > d] *= np.linspace(0.5, 3.0, int((alt_px.index > d).sum()))[:, None]
    alt = _signals(alt_px, rf)
    for key in ("eligible", "mom", "r12", "high52", "vol", "e4", "seas"):
        pd.testing.assert_series_equal(base[key].loc[d], alt[key].loc[d], check_names=False)
    assert base["rf12"].loc[d] == pytest.approx(alt["rf12"].loc[d])
    bb, ba = sg.target_books(base, me[k:k + 1]), sg.target_books(alt, me[k:k + 1])
    for key in bb:
        pd.testing.assert_series_equal(bb[key][d], ba[key][d])


def test_momentum_skips_latest_month_and_r12_does_not():
    px = synth_prices(start="1999-01-01", end="2001-12-31")
    me = sg.month_ends(px.index)
    mom, r12 = sg.momentum_12_1(px, me), sg.return_12m(px, me)
    d = me[20]
    assert mom.loc[d, "A"] == pytest.approx(px.loc[me[19], "A"] / px.loc[me[8], "A"] - 1)
    assert r12.loc[d, "A"] == pytest.approx(px.loc[me[20], "A"] / px.loc[me[8], "A"] - 1)


def test_seasonality_uses_same_calendar_month_of_prior_years():
    px = synth_prices(start="1990-01-01", end="2004-12-31")
    me = sg.month_ends(px.index)
    mr = sg.monthly_returns(px, me)
    seas = sg.seasonality(px, me)
    d = pd.Timestamp(me[me.to_series().dt.to_period("M") == pd.Period("2004-05", "M")][0])  # holds June 2004
    junes = [mr.loc[me[(me.year == y) & (me.month == 6)][0], "A"] for y in range(1994, 2004)]
    assert seas.loc[d, "A"] == pytest.approx(np.mean(junes))
    # fewer than 5 prior same-month returns -> no score
    px2 = synth_prices(start="1999-01-01", end="2004-12-31")
    me2 = sg.month_ends(px2.index)
    s2 = sg.seasonality(px2, me2)
    assert s2.loc[me2[(me2.year == 2003) & (me2.month == 5)][0]].isna().all()     # June: 1999-2002 = 4 obs
    assert s2.loc[me2[(me2.year == 2004) & (me2.month == 5)][0]].notna().all()    # June: 1999-2003 = 5 obs


def test_high52_uses_quoted_close_window_252():
    px = synth_prices(start="1999-01-01", end="2001-12-31")
    me = sg.month_ends(px.index)
    h = sg.high_52w(px, me)
    d = me[-1]
    win = px.loc[:d].iloc[-252:]
    assert h.loc[d, "A"] == pytest.approx(px.loc[d, "A"] / win["A"].max())


# -- books ---------------------------------------------------------------------------------------------
def test_half_weights_tercile_ties_and_fallback():
    names = [f"T{i}" for i in range(9)]
    score = pd.Series(np.arange(9, dtype=float), index=names)
    elig = pd.Series(True, index=names)
    w = sg.half_weights(score, elig, names)
    assert set(w[w > 0].index) == {"T8", "T7", "T6"} and w.sum() == pytest.approx(0.5)
    tied = pd.Series(1.0, index=names)
    w = sg.half_weights(tied, elig, names)
    assert set(w[w > 0].index) == {"T0", "T1", "T2"}   # ties -> alphabetical
    few = score.where(score > 6)          # two valid scores -> equal-weight benchmark of the eligible
    w = sg.half_weights(few, elig, names)
    assert (w == 0.5 / 9).all()
    names20 = [f"C{i:02d}" for i in range(20)]
    w = sg.half_weights(pd.Series(np.arange(20.0), index=names20), pd.Series(True, index=names20), names20)
    assert int((w > 0).sum()) == 7


def test_dual_momentum_sends_failing_slots_to_tbills():
    names = sg.SECTORS[:9] + sg.COUNTRY
    elig = pd.Series(False, index=sg.UNIVERSE)
    elig[names] = True
    r12 = pd.Series(np.nan, index=sg.UNIVERSE)
    r12[sg.SECTORS[:9]] = [0.30, 0.20, 0.01, -0.1, -0.2, -0.3, -0.4, -0.5, -0.6]
    r12[sg.COUNTRY] = np.linspace(0.5, -0.5, len(sg.COUNTRY))
    w = sg.dual_momentum_book(r12, 0.02, elig)
    assert w["XLB"] == pytest.approx(0.5 / 3) and w["XLE"] == pytest.approx(0.5 / 3)
    assert w["XLF"] == 0.0                      # selected but 1% <= 2% T-bill return -> T-bills
    assert w.sum() == pytest.approx(0.5 / 3 * 2 + 0.5)


# -- marking and costs ---------------------------------------------------------------------------------
def test_mark_alignment_and_costs():
    idx = pd.bdate_range("2020-01-01", periods=4)
    opens = pd.DataFrame({"XLK": [100, 101, 103, 106], "EWG": [50, 50, 50, 50]}, index=idx, dtype=float)
    closes = pd.DataFrame({"XLK": [100, 102, 104, 108], "EWG": [50, 51, 52, 53]}, index=idx, dtype=float)
    rf = pd.Series(0.0, index=idx)
    costs = pd.Series({"XLK": 0.0003, "EWG": 0.0008})
    sched = {idx[1]: pd.Series({"XLK": 1.0}), idx[3]: pd.Series({"EWG": 0.5})}
    f = ev.mark(sched, opens, closes, rf, idx[3], costs)
    # day 1: entry from cash at the open, open->close
    assert f.loc[idx[1], "gross"] == pytest.approx(102 / 101 - 1)
    assert f.loc[idx[1], "cost"] == pytest.approx(0.0003)
    # day 2: close->close
    assert f.loc[idx[2], "gross"] == pytest.approx(104 / 102 - 1)
    # day 3: old book close->open (106/104), sell all XLK, buy 50% EWG, open->close 53/50
    g = (106 / 104) * (0.5 * 53 / 50 + 0.5) - 1
    assert f.loc[idx[3], "gross"] == pytest.approx(g)
    assert f.loc[idx[3], "cost"] == pytest.approx(1.0 * 0.0003 + 0.5 * 0.0008)
    assert f.loc[idx[3], "turnover"] == pytest.approx(1.5)
    net = ev.with_costs(f)
    assert net.loc[idx[3]] == pytest.approx((1 + g) * (1 - 0.0007) - 1)
    stress = ev.with_costs(f, 3.0)
    assert stress.loc[idx[3]] == pytest.approx((1 + g) * (1 - 0.0021) - 1)


def test_cash_earns_rf_and_drifted_weights_set_turnover():
    idx = pd.bdate_range("2020-01-01", periods=3)
    px = pd.DataFrame({"SPY": [100.0, 110.0, 110.0]}, index=idx)
    rf = pd.Series(0.001, index=idx)
    sched = {idx[0]: pd.Series({"SPY": 0.5}), idx[2]: pd.Series({"SPY": 0.5})}
    f = ev.mark(sched, px, px, rf, idx[2], pd.Series({"SPY": 0.0003}))
    assert f.loc[idx[0], "gross"] == pytest.approx(0.5 * 0.001)            # open==close, cash earns rf
    w0, cash0 = 0.5 / 1.0005, 0.5 * 1.001 / 1.0005                        # weights at the day-0 close
    assert f.loc[idx[1], "gross"] == pytest.approx(w0 * 1.1 + cash0 * 1.001 - 1)
    drift = w0 * 1.1 / (1 + f.loc[idx[1], "gross"])                     # open 2 == close 1
    assert f.loc[idx[2], "turnover"] == pytest.approx(abs(0.5 - drift))


def test_vol_scale_formula_and_cap():
    idx = pd.bdate_range("2020-01-01", periods=200)
    x = pd.Series(0.01, index=idx)                        # sigma = sqrt(252) * 1% = 15.9%
    assert ev.vol_scale(x, idx[-1]) == pytest.approx(0.12 / (np.sqrt(252) * 0.01))
    assert ev.vol_scale(pd.Series(0.001, index=idx), idx[-1]) == 1.0
    with pytest.raises(ValueError):
        ev.vol_scale(x.iloc[:100], idx[99])


def test_cost_table():
    assert sg.COST_PER_SIDE["XLK"] == 0.0003 and sg.COST_PER_SIDE["SPY"] == 0.0003
    assert sg.COST_PER_SIDE["EEM"] == 0.0003 and sg.COST_PER_SIDE["EFA"] == 0.0003
    assert all(sg.COST_PER_SIDE[t] == 0.0008 for t in sg.SINGLE_COUNTRY)
    assert len(sg.UNIVERSE) == 31 and ev.STRESS_MULT == 3.0


# -- inference and lock ----------------------------------------------------------------------------------
def test_paired_sharpe_p_direction():
    rng = np.random.default_rng(1)
    y = rng.normal(0.0002, 0.01, 2000)
    assert ev.paired_sharpe_p(y + 0.001, y, draws=500) < 0.01
    assert ev.paired_sharpe_p(y, y, draws=200) == pytest.approx(1.0)


def test_validation_locked_without_unlock(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    monkeypatch.setattr(ev, "PREREG", tmp_path / "prereg.jsonl")
    assert not ev.validation_unlocked()
    (tmp_path / "research" / "etf_hybrids").mkdir(parents=True)
    (tmp_path / ev.UNLOCK).write_text("unlock")
    (tmp_path / "prereg.jsonl").write_text('{"file": "research/etf_hybrids/VALIDATION_UNLOCK.md", "sha256": "bad"}\n')
    assert not ev.validation_unlocked()
    with pytest.raises(SystemExit):
        ev.run("validation")
