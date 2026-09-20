import numpy as np
import pandas as pd
import pytest

from research.intraday import evaluate as ie


def _bars(days=40, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    price = 100.0
    for d in pd.bdate_range("2019-01-02", periods=days):
        for t in pd.date_range(d + pd.Timedelta(hours=9, minutes=30), d + pd.Timedelta(hours=15, minutes=30), freq="30min"):
            o = price
            price *= np.exp(rng.normal(0, 0.002))
            rows.append({"ts": t, "open": o, "high": max(o, price) * 1.001, "low": min(o, price) * 0.999, "close": price,
                         "volume": 100 + rng.integers(0, 50)})
    return pd.DataFrame(rows)


def test_prices_come_from_left_labelled_bars():
    b = _bars()
    t = ie.daily_table(b)
    d = t.index[5]
    day = b[b["ts"].dt.normalize() == d].set_index(b["ts"].dt.strftime("%H:%M")[b["ts"].dt.normalize() == d])
    assert t.loc[d, "p1530"] == day.loc["15:00", "close"]
    assert t.loc[d, "p1600"] == day.loc["15:30", "close"]
    assert t.loc[d, "p1000"] == day.loc["09:30", "close"]
    assert t.loc[d, "r_last"] == pytest.approx(day.loc["15:30", "close"] / day.loc["15:00", "close"] - 1)


def test_features_do_not_see_the_last_half_hour():
    b = _bars()
    t1 = ie.daily_table(b)
    last = b["ts"].dt.strftime("%H:%M") == "15:30"
    feats = ["r1", "r2", "r4", "r8", "r12", "first_half_hour", "rest_of_day", "rsi14", "bb_pctb", "atr_pct", "vol_z"]
    d = t1.index[30]
    # today's features may not depend on today's 15:30 bar (earlier days' 15:30 bars legitimately feed later features)
    b3 = b.copy()
    today_last = last & (b3["ts"].dt.normalize() == d)
    b3.loc[today_last, "close"] *= 1.05
    t3 = ie.daily_table(b3)
    pd.testing.assert_series_equal(t1.loc[d, feats], t3.loc[d, feats])
    assert t3.loc[d, "r_last"] != t1.loc[d, "r_last"]


def test_roll_days():
    r = ie.roll_days(pd.DatetimeIndex(["2019-01-02", "2019-12-31"]))
    assert pd.Timestamp("2019-03-14") in r and pd.Timestamp("2019-03-15") in r and pd.Timestamp("2019-03-18") in r
    assert pd.Timestamp("2019-03-13") not in r and pd.Timestamp("2019-03-19") not in r


def test_ml_trains_only_on_earlier_years(monkeypatch):
    seen = []

    class Fake:
        def __init__(self, **kw): pass
        def fit(self, X, y):
            seen.append(X.index.max()); return self
        def predict_proba(self, X):
            return np.column_stack([np.full(len(X), 0.4), np.full(len(X), 0.6)])

    import lightgbm
    monkeypatch.setattr(lightgbm, "LGBMClassifier", Fake)
    idx = pd.bdate_range("2016-06-01", "2019-12-31")
    rng = np.random.default_rng(1)
    t = pd.DataFrame({f: rng.normal(size=len(idx)) for f in ie.FEATURES if f not in ("is_nq",)}, index=idx)
    t["r_last"] = rng.normal(size=len(idx))
    pos = ie.ml_positions({"ES": t, "NQ": t.copy()}, pd.Timestamp("2016-06-01"), pd.Timestamp("2019-12-31"))
    assert seen[0] < pd.Timestamp("2018-01-01") and seen[1] < pd.Timestamp("2019-01-01")
    assert pos["ES"].loc["2018-01-02"] == 1.0 and np.isnan(pos["ES"].loc["2017-06-01"])


def test_validation_needs_a_matching_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(ie, "ROOT", tmp_path)
    monkeypatch.setattr(ie, "PREREG", tmp_path / "prereg.jsonl")
    (tmp_path / "prereg.jsonl").write_text("")
    assert ie.validation_unlocked() is False
    (tmp_path / "research" / "intraday").mkdir(parents=True)
    (tmp_path / ie.UNLOCK).write_text("unlock")
    (tmp_path / "prereg.jsonl").write_text('{"file": "%s", "sha256": "wrong"}\n' % ie.UNLOCK)
    assert ie.validation_unlocked() is False
