import numpy as np
import pandas as pd
import pytest

from research.cot import evaluate as ce


def _cot(n_weeks=60):
    rows = []
    dates = pd.date_range("2015-01-06", periods=n_weeks, freq="7D")
    rng = np.random.default_rng(0)
    for sym in ce.MAP:
        for d in dates:
            rows.append({"symbol": sym, "date": d.strftime("%Y-%m-%d"), "release_date": (d + pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
                         "open_interest": 1000, "noncomm_long": int(rng.integers(100, 400)), "noncomm_short": 200,
                         "comm_long": int(rng.integers(100, 400)), "comm_short": 300})
    return pd.DataFrame(rows)


def test_signals_only_use_released_reports():
    cot = _cot()
    upto = pd.Timestamp("2015-06-30")
    sig = ce.cot_signals(cot, upto)
    assert sig["release_date"].max() <= upto
    full = ce.cot_signals(cot, pd.Timestamp("2030-01-01"))
    a = sig.set_index(["release_date", "etf"])["q"]
    b = full.set_index(["release_date", "etf"])["q"].reindex(a.index)
    pd.testing.assert_series_equal(a, b)


def test_q_definition_and_hp52_warmup():
    cot = _cot()
    sig = ce.cot_signals(cot, pd.Timestamp("2030-01-01"))
    g = cot[cot["symbol"] == "ZC"].reset_index(drop=True)
    net = g["noncomm_long"] - g["noncomm_short"]
    s = sig[sig["etf"] == "CORN"].reset_index(drop=True)
    assert s["q"].iloc[5] == pytest.approx((net.iloc[5] - net.iloc[4]) / 1000)
    assert s["hp52"].iloc[38] != s["hp52"].iloc[38] and np.isfinite(s["hp52"].iloc[39])  # needs 40 reports


def test_entry_is_first_trading_day_after_release():
    cal = pd.bdate_range("2015-01-01", "2015-03-31")
    sig = pd.DataFrame({"release_date": [pd.Timestamp("2015-01-09")], "etf": ["GLD"], "q": [0.1], "hp52": [0.2]})
    sc = ce.entry_panel(sig, cal)
    assert sc["C1_liquidity"].index[0] == pd.Timestamp("2015-01-12")


def test_weights_and_cost_accounting():
    s = pd.Series(np.arange(11.0), index=list(ce.COST_BPS))
    w = ce.target_weights(s)
    assert w.sum() == pytest.approx(0) and w.abs().sum() == pytest.approx(2)
    assert ce.target_weights(s.iloc[:7]).abs().sum() == 0
    cal = pd.bdate_range("2016-01-04", periods=30)
    opens = pd.DataFrame(100.0, index=cal, columns=list(ce.COST_BPS))
    score = pd.DataFrame([s.values] * len(cal), index=cal, columns=s.index)
    entries = cal[::5]
    bt = ce.backtest(score, opens, pd.Series(0.0, index=cal), entries, ce.COSTS["base"])
    first = bt.iloc[0]
    expect = sum(ce.COST_BPS[t] / 1e4 / 3 for t in w[w != 0].index)
    assert first["cost"] == pytest.approx(expect)
    assert (bt["turnover"].iloc[1:] == 0).all() and (bt["gross"] == 0).all()


def test_validation_locked():
    assert ce.validation_unlocked() is False
