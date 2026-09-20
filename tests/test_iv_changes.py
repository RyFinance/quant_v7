import numpy as np
import pandas as pd
import pytest

from research.iv_changes import atm_iv
from research.iv_changes import evaluate as ivev
from research.options_signals import evaluate as oev
from research.options_signals import signals as sg


# -- synthetic market ---------------------------------------------------------------------------
def _write_market(tmp_path, monkeypatch, vol_fn, days, S=100.0, r=0.0):
    opt_dir, raw_dir, div_dir = tmp_path / "opt", tmp_path / "raw", tmp_path / "div"
    for p in (opt_dir, raw_dir, div_dir):
        p.mkdir()
    pd.DataFrame({"date": days, "raw_close": S, "raw_volume": 1e6, "Stock Splits": 0.0}).to_parquet(raw_dir / "XYZ.parquet")
    expiries = pd.date_range(days[0], days[-1] + pd.Timedelta(days=120), freq="W-FRI")
    rows = []
    for d in days:
        for e in expiries:
            dte = (e - d).days
            if not 7 <= dte <= 90:
                continue
            for K in (95.0, 100.0, 105.0):
                for typ in ("C", "P"):
                    px = float(sg.bs_price(S, K, dte / 365, r, vol_fn(d, dte), typ == "C"))
                    rows.append({"ts": d.tz_localize("UTC"), "expiry": e, "opt_type": typ, "strike": K,
                                 "osi": "XYZ", "close": px, "volume": 10})
    pd.DataFrame(rows).to_parquet(opt_dir / "XYZ.parquet")
    monkeypatch.setattr(sg, "OPT_DIR", opt_dir)
    monkeypatch.setattr(sg, "RAW_DIR", raw_dir)
    monkeypatch.setattr(sg, "DIV_DIR", div_dir)
    return pd.Series(r, index=pd.DatetimeIndex(days))


def test_atm_iv_recovers_flat_and_interpolated_vol(tmp_path, monkeypatch):
    days = pd.bdate_range("2019-01-02", "2019-02-28")
    rates = _write_market(tmp_path, monkeypatch, lambda d, dte: 0.20 + 0.001 * dte, days)
    out = atm_iv.daily_atm_iv("XYZ", rates=rates)
    # total variance is interpolated, so the result lies between the bracketing vols near 0.23
    assert out["call_iv30"].notna().mean() > 0.9
    assert out["call_iv30"].dropna().between(0.225, 0.236).all()
    assert np.allclose(out["call_iv30"].dropna(), out["put_iv30"].dropna(), atol=1e-4)


def test_no_look_ahead_future_prints_do_not_change_past(tmp_path, monkeypatch):
    days = pd.bdate_range("2019-01-02", "2019-03-29")
    cut = pd.Timestamp("2019-02-15")
    rates = _write_market(tmp_path, monkeypatch, lambda d, dte: 0.25 if d <= cut else 0.60, days)
    a = atm_iv.daily_atm_iv("XYZ", upto=cut, rates=rates)
    assert a.index.max() <= cut
    assert np.allclose(a["call_iv30"].dropna(), 0.25, atol=1e-4)
    full = atm_iv.daily_atm_iv("XYZ", rates=rates)
    pd.testing.assert_frame_equal(a, full.loc[:cut])


def test_interp_exact_at_near_expiry_and_flat():
    assert np.isclose(atm_iv.interp_30d(0.3, 30 / 365, 0.5, 60 / 365), 0.3)
    assert np.isclose(atm_iv.interp_30d(0.2, 10 / 365, 0.2, 45 / 365), 0.2)


def test_atm_pick_nearest_strike_lower_on_tie_and_bracket_needs_both():
    d = pd.Timestamp("2019-01-02")
    opt = pd.DataFrame({"date": d, "is_call": True, "expiry": pd.Timestamp("2019-01-18"),
                        "strike": [99.0, 101.0, 103.0], "S": 100.0, "dte": 16})
    assert atm_iv.atm_by_expiry(opt)["strike"].tolist() == [99.0]
    atm = pd.DataFrame({"date": d, "is_call": True, "dte": [16, 23], "iv": [0.2, 0.2]})
    assert atm_iv.bracket_30d(atm).empty  # no expiry beyond 30 days


# -- month alignment ------------------------------------------------------------------------------
def test_month_end_signal_dates_and_partial_month():
    cal = pd.bdate_range("2019-10-01", "2020-01-15").drop(pd.Timestamp("2019-11-29"))
    d = ivev.complete_month_ends(cal, cal[0], cal[-1])
    assert list(d.strftime("%Y-%m-%d")) == ["2019-10-31", "2019-11-28", "2019-12-31"]  # Jan 2020 is partial


def test_changes_use_previous_month_end():
    idx = pd.DatetimeIndex(["2019-10-31", "2019-11-29", "2019-12-31"])
    lv = {"call": pd.DataFrame({"A": [0.2, 0.25, 0.22]}, index=idx),
          "put": pd.DataFrame({"A": [0.2, 0.21, 0.30]}, index=idx)}
    s = ivev.scores_from_levels(lv)
    assert np.isnan(s["V1_dcall"].iloc[0, 0])
    assert np.isclose(s["V1_dcall"].loc["2019-11-29", "A"], 0.05)
    assert np.isclose(s["V2_dput"].loc["2019-12-31", "A"], -0.09)
    assert np.isclose(s["V3_dspread"].loc["2019-12-31", "A"], -0.03 - 0.09)


def test_monthly_book_enters_next_open_and_charges_costs():
    cal = pd.bdate_range("2019-01-01", "2019-04-30")
    names = [f"N{i}" for i in range(30)]
    opens = pd.DataFrame(100.0, index=cal, columns=names)
    closes = opens.copy()
    dates = ivev.complete_month_ends(cal, cal[0], pd.Timestamp("2019-03-31")).append(pd.DatetimeIndex(["2019-04-30"]))
    score = pd.DataFrame(np.tile(np.arange(30.0), (len(cal), 1)), index=cal, columns=names)
    rf = pd.Series(0.0, index=cal)
    bt = oev.backtest(score, opens, closes, dates, cal, rf, ivev.COSTS["base"])
    assert bt["entry"].iloc[0] == pd.Timestamp("2019-02-01")
    assert bt["exit"].iloc[0] == pd.Timestamp("2019-03-01")
    first = bt.iloc[0]
    assert np.isclose(first["turnover"], 2.0) and np.isclose(first["cost"], 2.0 * 0.0005)
    assert np.isclose(first["borrow"], 0.005 * (first["exit"] - first["entry"]).days / 365)
    assert np.isclose(bt["turnover"].iloc[1], 0.0)  # unchanged book, flat prices
    st = oev.backtest(score, opens, closes, dates, cal, pd.Series(0.001, index=cal), ivev.COSTS["stress"])
    assert (st["proceeds_drag"] > 0).all() and np.isclose(st["cost"].iloc[0], 2.0 * 0.0015)


def test_summary_annualises_monthly():
    idx = pd.date_range("2015-01-30", periods=24, freq="BME")
    net = np.tile([0.01, 0.0], 12)
    bt = pd.DataFrame({"entry": idx, "exit": idx + pd.Timedelta(days=30), "names_long": 20, "names_short": 20,
                       "gross": net, "turnover": 0.5, "cost": 0.0, "borrow": 0.0, "proceeds_drag": 0.0, "net": net},
                      index=idx)
    s = ivev.summarize(bt)
    assert np.isclose(s["sharpe_net"], net.mean() / net.std(ddof=1) * np.sqrt(12))


# -- validation lock ------------------------------------------------------------------------------
def test_validation_locked_without_registered_unlock(tmp_path, monkeypatch):
    monkeypatch.setattr(ivev, "PREREG", tmp_path / "prereg.jsonl")
    (tmp_path / "prereg.jsonl").write_text("")
    assert not ivev.validation_unlocked()
    monkeypatch.setattr(oev, "universe", lambda: [])
    with pytest.raises(SystemExit, match="locked"):
        ivev.run("validation")


def test_dev_refuses_incomplete_pull(monkeypatch):
    monkeypatch.setattr(oev, "universe", lambda: ["NOT_A_REAL_NAME_ZZ"])
    with pytest.raises(SystemExit, match="incomplete"):
        ivev.run("dev")
