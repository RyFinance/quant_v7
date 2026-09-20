import numpy as np
import pandas as pd
import pytest

from research.putwrite import evaluate as pw


@pytest.fixture
def toy(tmp_path, monkeypatch):
    cal = pd.bdate_range("2019-01-01", periods=40)
    close = np.full(40, 100.0)
    close[31] = 95.0  # a crash day
    spot = pd.DataFrame({"date": cal, "Close": close, "Adj Close": 100 * np.cumprod(1 + np.r_[0, np.random.default_rng(0).normal(0, 0.01, 39)])})
    (tmp_path / "spot").mkdir()
    spot.to_parquet(tmp_path / "spot" / "SPY.parquet")
    rows = []
    for i, d in enumerate(cal[:-1]):
        for k in (97.0, 98.0, 99.0, 100.0):
            rows.append({"ts": pd.Timestamp(d).tz_localize("UTC"), "expiry": cal[i + 1].date(), "opt_type": "P",
                         "strike": k, "close": 0.10 + (k - 97) * 0.1, "volume": 5})
    (tmp_path / "opt").mkdir()
    pd.DataFrame(rows).to_parquet(tmp_path / "opt" / "SPY.parquet")
    monkeypatch.setattr(pw, "SPOT", tmp_path / "spot")
    monkeypatch.setattr(pw, "OPT", tmp_path / "opt")
    return cal


def test_trade_accounting_and_crash_day(toy):
    cal = toy
    rates = pd.Series(0.0, index=cal)
    tr = pw.trades("SPY", cal[0], cal[-2], cal, rates, pw.COSTS["base"])
    assert len(tr) > 0
    comm = 0.65 / 100
    calm = tr[tr["payoff"] == 0].iloc[0]
    assert calm["net"] == pytest.approx((calm["premium"] - 0.01 - comm) / calm["K"])
    crash = tr[tr["settle"] == cal[31]].iloc[0]
    assert crash["payoff"] == pytest.approx(crash["K"] - 95.0)
    assert crash["net"] == pytest.approx((crash["premium"] - 2 * (0.01 + comm) - crash["payoff"]) / crash["K"])


def test_strike_rule_uses_rv_known_at_entry(toy):
    cal = toy
    rates = pd.Series(0.0, index=cal)
    tr = pw.trades("SPY", cal[0], cal[-2], cal, rates, pw.COSTS["base"])
    first = tr.iloc[0]
    assert first["entry"] >= cal[pw.RV_DAYS]  # needs 21 returns before the first trade
    kstar = first["S"] * np.exp(-pw.Z * first["rv"] * np.sqrt(1 / 252))
    assert abs(first["K"] - kstar) <= 0.5 + 1e-9


def test_trades_ignore_option_rows_after_end(toy):
    cal = toy
    rates = pd.Series(0.0, index=cal)
    end = cal[30]
    tr = pw.trades("SPY", cal[0], end, cal, rates, pw.COSTS["base"])
    assert tr["entry"].max() <= end


def test_validation_locked():
    assert pw.validation_unlocked() is False
