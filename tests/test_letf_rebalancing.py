import numpy as np
import pandas as pd
import pytest

from research.letf_rebalancing import evaluate as le


def _bars(days=120, seed=0):
    rng = np.random.default_rng(seed)
    rows, price = [], 100.0
    for d in pd.bdate_range("2019-01-02", periods=days):
        for t in pd.date_range(d + pd.Timedelta(hours=9, minutes=30), d + pd.Timedelta(hours=15, minutes=30), freq="30min"):
            o = price
            price *= np.exp(rng.normal(0, 0.003))
            rows.append({"ts": t, "open": o, "high": max(o, price), "low": min(o, price), "close": price,
                         "volume": int(1000 + rng.integers(0, 500))})
    return pd.DataFrame(rows)


def _gamma(bars):
    days = pd.DatetimeIndex(sorted(bars["ts"].dt.normalize().unique()))
    return pd.Series(np.linspace(1e9, 3e9, len(days)), index=days)


def test_aum_is_known_at_prior_close_only():
    s = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]))
    days = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    v = le.prior_close_value(s, pd.DatetimeIndex(days))
    assert np.isnan(v.iloc[0])
    assert list(v.iloc[1:]) == [1.0, 2.0, 3.0]


def test_gamma_uses_l_times_l_minus_one():
    idx = pd.to_datetime(["2020-01-02"])
    aum = {"A": pd.Series([10.0], index=idx), "B": pd.Series([5.0], index=idx), "C": pd.Series([1.0], index=idx)}
    g = le.gamma_dollars({"A": 3, "B": -3, "C": -1}, aum)
    assert g.iloc[0] == pytest.approx(10 * 6 + 5 * 12 + 1 * 2)


def test_signal_ignores_the_traded_bar():
    b = _bars()
    g = _gamma(b)
    t1 = le.signal_table(b, g, 50.0)
    p1 = le.positions(t1)
    d = t1.index[100]
    b2 = b.copy()
    m = (b2["ts"].dt.normalize() == d) & (b2["ts"].dt.strftime("%H:%M") == "15:30")
    b2.loc[m, ["close", "high", "low"]] *= 1.05
    b2.loc[m, "volume"] *= 50
    t2 = le.signal_table(b2, g, 50.0)
    p2 = le.positions(t2)
    for c in ["flow", "phi", "vbar", "gamma_prev"]:
        assert t1.loc[d, c] == pytest.approx(t2.loc[d, c])
    for k in ["L1_flow_top_quintile", "L2_flow_scaled", "bucket"]:
        assert p1[k].loc[d] == p2[k].loc[d]
    assert t1.loc[d, "r_last"] != pytest.approx(t2.loc[d, "r_last"])


def test_vbar_excludes_today_and_refs_are_past_only():
    b = _bars()
    t = le.signal_table(b, _gamma(b), 50.0)
    vol = le.last_bar_volume(b).reindex(t.index) * t["p1600"] * 50
    d = t.index[50]
    assert t.loc[d, "vbar"] == pytest.approx(vol.iloc[30:50].median())
    ref = le.expanding_refs(t["phi"])
    first = t["phi"].notna().cumsum()
    assert ref["p80"][first <= le.MIN_HIST].isna().all()
    i = 100
    past = t["phi"].iloc[:i].dropna()
    assert ref["p80"].iloc[i] == pytest.approx(np.percentile(past, 80))


def test_positions_sign_and_cap():
    b = _bars()
    t = le.signal_table(b, _gamma(b), 50.0)
    p = le.positions(t)
    ok = p["L2_flow_scaled"].notna()
    assert (p["L2_flow_scaled"][ok].abs() <= le.CAP + 1e-12).all()
    nz = p["L1_flow_top_quintile"].fillna(0) != 0
    assert (np.sign(p["L1_flow_top_quintile"][nz]) == np.sign(t["flow"][nz])).all()
    assert set(p["L1_flow_top_quintile"].dropna().unique()) <= {-1.0, 0.0, 1.0}


def test_costs_scale_with_position():
    days = pd.to_datetime(["2020-01-02", "2020-01-03"])
    t = pd.DataFrame({"r_last": [0.001, -0.002]}, index=days)
    tables = {"ES": t, "NQ": t}
    pos = {"ES": pd.Series([2.0, 0.0], index=days), "NQ": pd.Series([-1.0, 0.0], index=days)}
    r = le.book(tables, pos, 0.5e-4, days)
    exp = 0.5 * (2 * 0.001 - 2 * 2 * 0.5e-4) + 0.5 * (-1 * 0.001 - 1 * 2 * 0.5e-4)
    assert r.iloc[0] == pytest.approx(exp)
    assert r.iloc[1] == 0.0


def test_roll_days_cover_thursday_to_monday():
    idx = pd.bdate_range("2020-03-01", "2020-03-31")
    rd = le.roll_days(idx)
    for d in ["2020-03-19", "2020-03-20", "2020-03-23"]:
        assert pd.Timestamp(d) in rd
    assert pd.Timestamp("2020-03-18") not in rd and pd.Timestamp("2020-03-24") not in rd


def test_validation_locked_without_unlock(monkeypatch, tmp_path):
    monkeypatch.setattr(le, "ROOT", tmp_path)
    monkeypatch.setattr(le, "PREREG", tmp_path / "p.jsonl")
    assert le.validation_unlocked() is False
    with pytest.raises(SystemExit):
        le.run("validation")
