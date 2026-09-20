import numpy as np
import pandas as pd

from research.pead_streak import streak as st


def _ev(rows):
    return pd.DataFrame(rows, columns=["ticker", "effective", "announced", "surprise_pct"]).assign(
        effective=lambda d: pd.to_datetime(d["effective"]), announced=lambda d: pd.to_datetime(d["announced"]))


def test_previous_surprise_known_before_entry_and_gap_rules():
    ev = _ev([
        ["A", "2020-01-02", "2020-01-01 16:05", 5.0],
        ["A", "2020-04-02", "2020-04-01 16:05", 3.0],    # streak (+,+)
        ["A", "2020-07-02", "2020-07-01 16:05", -1.0],   # breaks
        ["A", "2020-07-03", "2020-07-02 07:00", -2.0],   # previous only 1 day earlier -> unknown
        ["A", "2021-06-01", "2021-06-01 07:00", -2.0],   # previous > 200 days earlier -> unknown
        ["B", "2020-01-02", "2020-01-01 16:05", -1.0],
        ["B", "2020-04-02", "2020-04-02 07:00", -1.0],   # streak (-,-)
    ])
    out = st.add_streak(ev).set_index(["ticker", "announced"])
    assert out["streak"].tolist() == [False, True, False, False, False, False, True]
    known = out.dropna(subset=["prev_sign"])
    assert (known["prev_effective"] < known["effective"]).all()
    assert (known.index.get_level_values(1) > known["prev_announced"]).all()


def test_zero_surprise_never_streaks():
    ev = _ev([["A", "2020-01-02", "2020-01-01 16:05", 0.0], ["A", "2020-04-02", "2020-04-01 16:05", 0.0]])
    assert not st.add_streak(ev)["streak"].any()


def test_event_timing_enters_close_day1_holds_20():
    cal = pd.bdate_range("2020-01-01", periods=60)
    ev = st.add_streak(_ev([["A", "2020-01-06", "2020-01-03 16:05", 1.0]]))
    sch = st.schedule(ev, cal)
    d0 = cal.get_loc(pd.Timestamp("2020-01-06"))
    assert (sch["start"].iloc[0], sch["end"].iloc[0]) == (d0 + 2, d0 + 1 + st.HOLD)
    W = st.weights(sch, cal, ["A"], 1.0, 0.0)
    held = np.flatnonzero(W["A"].to_numpy())
    assert held[0] == d0 + 2 and len(held) == st.HOLD
    # the announcement-day and day+1 returns are never earned
    assert W["A"].iloc[: d0 + 2].eq(0).all()


def test_held_ticker_ignores_new_event():
    cal = pd.bdate_range("2020-01-01", periods=80)
    ev = st.add_streak(_ev([["A", "2020-01-06", "2020-01-03 16:05", 1.0], ["A", "2020-01-20", "2020-01-17 16:05", 1.0]]))
    assert len(st.schedule(ev, cal)) == 1


def test_costs_round_trip_and_borrow():
    cal = pd.bdate_range("2020-01-01", periods=30)
    W = pd.DataFrame(0.0, index=cal, columns=["A", "B"])
    W.iloc[5:15, 0] = 0.5
    W.iloc[5:15, 1] = -0.5
    rets = pd.DataFrame(0.0, index=cal, columns=["A", "B"])
    rf = pd.Series(0.0, index=cal)
    b = st.book_returns(W, rets, rf, per_side=0.0005, borrow=0.005)
    # entry turnover 1.0 and exit turnover 1.0 at 5 bps -> 10 bps of gross 1.0 round trip
    assert np.isclose(b["cost"].sum(), 2 * 1.0 * 0.0005)
    assert np.isclose(b["borrow"].sum(), 10 * 0.5 * 0.005 / 252)
    assert np.isclose(b["excess"].sum(), -(b["cost"].sum() + b["borrow"].sum()))


def test_excess_is_over_rf_and_long_only_has_no_idle_cash():
    cal = pd.bdate_range("2020-01-01", periods=5)
    W = pd.DataFrame(1.0, index=cal, columns=["A"])
    rets = pd.DataFrame(0.001, index=cal, columns=["A"])
    rf = pd.Series(0.0002, index=cal)
    b = st.book_returns(W, rets, rf, 0.0, 0.0)
    assert np.allclose(b["gross_excess"], 0.0008)


def test_validation_locked_without_unlock(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "ROOT", tmp_path)
    assert not st.validation_unlocked()
