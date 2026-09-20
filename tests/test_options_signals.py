import numpy as np
import pandas as pd
import pytest

from research.options_signals import evaluate as ev
from research.options_signals import signals as sg


def test_implied_vol_round_trip_calls_and_puts():
    S = np.array([100.0, 100.0, 250.0, 40.0])
    K = np.array([95.0, 105.0, 240.0, 38.0])
    T = np.array([30, 45, 10, 60]) / 365
    r = np.array([0.03, 0.0, 0.05, 0.01])
    sig = np.array([0.25, 0.4, 0.8, 0.15])
    call = np.array([True, False, True, False])
    px = sg.bs_price(S, K, T, r, sig, call)
    assert np.allclose(sg.implied_vol(px, S, K, T, r, call), sig, atol=1e-6)


def test_implied_vol_nan_outside_bounds():
    # below intrinsic value, and above the spot price
    iv = sg.implied_vol(np.array([10.0, 200.0]), np.array([100.0, 100.0]), np.array([50.0, 50.0]),
                        np.array([0.05, 0.05]), np.array([0.0, 0.0]), np.array([True, True]))
    assert np.isnan(iv).all()


def test_split_rule_drops_prelisted_expiries_only():
    D = pd.Timestamp("2020-08-31")
    opt = pd.DataFrame({
        "date": pd.to_datetime(["2020-08-28", "2020-08-31", "2020-08-31", "2020-09-01"]),
        "expiry": pd.to_datetime(["2020-09-18", "2020-09-18", "2020-10-02", "2020-10-02"]),
    })
    kept = sg.drop_split_adjusted(opt, [D])
    assert list(kept["expiry"].dt.strftime("%m-%d")) == ["09-18", "10-02", "10-02"]
    assert kept["date"].iloc[0] == pd.Timestamp("2020-08-28")


def test_pv_dividends_counts_only_ex_dates_before_expiry():
    divs = pd.DataFrame({"ex": pd.to_datetime(["2020-01-10", "2020-03-10"]), "amount": [1.0, 1.0]})
    dates = np.array(["2020-01-02", "2020-01-10"], dtype="datetime64[ns]")
    exp = np.array(["2020-02-01", "2020-02-01"], dtype="datetime64[ns]")
    pv = sg.pv_dividends(dates, exp, np.zeros(2), divs)
    assert pv.tolist() == [1.0, 0.0]  # ex-date must be strictly after the valuation date


def test_rolling_signals_need_three_days():
    idx = pd.bdate_range("2020-01-01", periods=6)
    daily = pd.DataFrame({"opt_shares": [100, 100, np.nan, np.nan, 100, 100],
                          "stock_shares": [1000] * 6, "ivspread": [0.01] * 6, "skew": [np.nan] * 6}, index=idx)
    out = sg.rolling_signals(daily)
    assert np.isnan(out["os"].iloc[3])  # window of days 0-3 holds only 2 observed days
    assert out["os"].iloc[5] == pytest.approx(0.1)  # window of days 1-5 holds days 1, 4, 5
    assert out["skew"].isna().all()


def test_target_weights_quintiles_and_minimum_names():
    s = pd.Series(np.arange(30, dtype=float), index=[f"S{i}" for i in range(30)])
    w = ev.target_weights(s)
    assert w.sum() == pytest.approx(0.0) and w.abs().sum() == pytest.approx(2.0)
    assert (w[w > 0].index == [f"S{i}" for i in range(24, 30)]).all()
    assert ev.target_weights(s.iloc[:24]).abs().sum() == 0.0


def _toy_market(n=30, days=30, seed=0):
    rng = np.random.default_rng(seed)
    cal = pd.bdate_range("2021-01-04", periods=days)
    names = [f"S{i}" for i in range(n)]
    opens = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0, 0.01, (days, n)), axis=0), index=cal, columns=names)
    return cal, names, opens


def test_backtest_costs_reconcile():
    cal, names, opens = _toy_market()
    score = pd.DataFrame(np.tile(np.arange(30.0), (len(cal), 1)), index=cal, columns=names)
    dates = ev.signal_dates(cal, cal[0], cal[-1])
    rf = pd.Series(0.0001, index=cal)
    cost = {"per_side": 0.001, "borrow": 0.02, "proceeds_earn_rf": False}
    bt = ev.backtest(score, opens, opens, dates, cal, rf, cost)
    assert bt["turnover"].iloc[0] == pytest.approx(2.0)  # opening the book from cash
    assert (bt["turnover"].iloc[1:] < 0.2).all()  # same names each week: only drift is traded
    recon = bt["gross"] - bt["turnover"] * 0.001 - bt["borrow"] - bt["proceeds_drag"]
    assert np.allclose(recon, bt["net"])
    e, x = bt["entry"].iloc[0], bt["exit"].iloc[0]
    manual = (opens.loc[x, names[24:]] / opens.loc[e, names[24:]] - 1).mean() - \
             (opens.loc[x, names[:6]] / opens.loc[e, names[:6]] - 1).mean()
    assert bt["gross"].iloc[0] == pytest.approx(manual)


def test_backtest_uses_signal_known_at_t_only():
    cal, names, opens = _toy_market(seed=1)
    base = pd.DataFrame(np.tile(np.arange(30.0), (len(cal), 1)), index=cal, columns=names)
    dates = ev.signal_dates(cal, cal[0], cal[-1])
    rf = pd.Series(0.0, index=cal)
    cost = ev.COSTS["base"]
    a = ev.backtest(base, opens, opens, dates, cal, rf, cost)
    later = base.copy()
    later.loc[later.index > dates[1]] = later.loc[later.index > dates[1]].iloc[:, ::-1].to_numpy()
    b = ev.backtest(later, opens, opens, dates, cal, rf, cost)
    assert np.allclose(a["net"].iloc[:2], b["net"].iloc[:2])


def test_validation_locked_without_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    monkeypatch.setattr(ev, "PREREG", tmp_path / "prereg.jsonl")
    assert ev.validation_unlocked() is False
    (tmp_path / "research" / "options_signals").mkdir(parents=True)
    (tmp_path / ev.UNLOCK).write_text("unlock")
    (tmp_path / "prereg.jsonl").write_text('{"file": "%s", "sha256": "wrong"}\n' % ev.UNLOCK)
    assert ev.validation_unlocked() is False


def test_daily_signals_do_not_read_past_upto(tmp_path, monkeypatch):
    cal = pd.bdate_range("2019-12-02", "2020-01-31")
    spot = pd.DataFrame({"date": cal, "raw_close": 100.0, "raw_volume": 1e6, "Stock Splits": 0.0})
    (tmp_path / "raw").mkdir()
    spot.to_parquet(tmp_path / "raw" / "TT.parquet")
    rows = []
    for d in cal:
        for k in (95.0, 100.0, 105.0):
            for typ in ("C", "P"):
                px = 3.0 if d <= pd.Timestamp("2019-12-31") else 9.0  # later prices differ
                rows.append({"ts": pd.Timestamp(d).tz_localize("UTC"), "expiry": (d + pd.Timedelta(days=30)).date(),
                             "opt_type": typ, "strike": k, "osi": f"O:TT{typ}{k}", "close": px, "volume": 10})
    (tmp_path / "opt").mkdir()
    pd.DataFrame(rows).to_parquet(tmp_path / "opt" / "TT.parquet")
    monkeypatch.setattr(sg, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sg, "OPT_DIR", tmp_path / "opt")
    monkeypatch.setattr(sg, "DIV_DIR", tmp_path / "nodivs")
    rates = pd.Series(0.02, index=cal)
    upto = pd.Timestamp("2019-12-31")
    cut = sg.daily_signals("TT", upto=upto, rates=rates)
    full = sg.daily_signals("TT", rates=rates)
    assert cut.index.max() == upto
    pd.testing.assert_frame_equal(cut, full.loc[:upto], check_freq=False)


def test_dividends_use_raw_amount_on_matching_ex_date(tmp_path, monkeypatch):
    # amendment 3: the vault amount on 2017-06-15 is back-adjusted (x4.79); the raw file holds the cash paid
    cal = pd.bdate_range("2017-06-01", "2017-12-29")
    spot = pd.DataFrame({"date": cal, "raw_close": 30.0, "raw_volume": 1e6, "Stock Splits": 0.0,
                         "Dividends": 0.0, "split_factor_after": 0.2})
    spot.loc[spot["date"] == "2017-06-15", "Dividends"] = 1.2  # split-adjusted: raw = 1.2 * 0.2 = 0.24
    (tmp_path / "raw").mkdir()
    spot.to_parquet(tmp_path / "raw" / "TT.parquet")
    (tmp_path / "div").mkdir()
    pd.DataFrame({"effective_date": ["2017-06-15", "2017-09-15"],
                  "dividend_amount": [1.15019, 0.5]}).to_parquet(tmp_path / "div" / "TT.parquet")
    monkeypatch.setattr(sg, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sg, "DIV_DIR", tmp_path / "div")
    d = sg.load_dividends("TT")
    assert d["amount"].tolist() == pytest.approx([0.24, 0.5])  # matched row replaced, unmatched row kept
    assert list(d["ex"]) == list(pd.to_datetime(["2017-06-15", "2017-09-15"]))


def test_no_signal_date_inside_an_iso_week_that_runs_past_the_window():
    # amendment 3: 2019-12-31 (Tue) is not the last trading day of ISO week 2020-W01
    cal = pd.bdate_range("2019-12-02", "2020-01-14").drop(pd.to_datetime(["2019-12-25", "2020-01-01"]))
    d = ev.window_signal_dates(cal, pd.Timestamp("2019-12-01"), pd.Timestamp("2019-12-31"), pd.Timestamp("2020-01-14"))
    assert list(d.strftime("%m-%d")) == ["12-06", "12-13", "12-20", "12-27", "01-03"]


def test_wrong_underlying_days_flag_only_gross_mismatch():
    days = pd.bdate_range("2019-01-02", periods=4)
    rows = []
    for i, d in enumerate(days):
        true_spot = 100.0
        for k in (60.0, 80.0, 100.0, 120.0):
            call = max(true_spot - k, 0) + 2.0
            put = max(k - true_spot, 0) + 2.0
            recorded = 100.0 if i < 2 else 70.0  # days 3-4: the ticker's price history is another company
            for typ, px in (("C", call), ("P", put)):
                rows.append({"date": d, "expiry": d + pd.Timedelta(days=30), "strike": k, "opt_type": typ,
                             "close": px, "S": recorded, "dte": 30})
    opt = pd.DataFrame(rows)
    flagged = sg.wrong_underlying_days(opt, pd.Series(0.0, index=days), pd.DataFrame(columns=["ex", "amount"]))
    assert list(flagged) == list(days[2:])
