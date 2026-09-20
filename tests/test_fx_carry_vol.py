import numpy as np
import pandas as pd
import pytest

from research.fx_carry_vol import evaluate as fx


def test_carry_sign_conventions():
    S = pd.Series({"AUDUSD": 0.70, "USDJPY": 150.0})
    F = pd.Series({"AUDUSD": 0.70 - 0.0002, "USDJPY": 150.0 - 0.16})
    c = fx.carry(S, F)
    assert c["AUDUSD"] > 0  # AUD forward at a discount: AUD pays more than USD, long AUD earns carry
    assert c["USDJPY"] < 0  # USDJPY forward below spot: USD pays more than JPY, long JPY loses carry


def test_long_foreign_return():
    assert fx.long_foreign_return("EURUSD", 1.10, 1.21) == pytest.approx(0.10)
    assert fx.long_foreign_return("USDJPY", 150.0, 125.0) == pytest.approx(0.20)  # yen appreciates


def test_forward_uses_pip_size():
    assert fx.forward(150.0, -16.0, "USDJPY") == pytest.approx(149.84)
    assert fx.forward(1.10, 3.0, "EURUSD") == pytest.approx(1.1003)


def test_weights_legs_and_vol_target():
    c = pd.Series(np.linspace(-0.05, 0.05, 9), index=fx.PAIRS)
    iv = pd.Series(np.linspace(0.06, 0.14, 9), index=fx.PAIRS)
    w1 = fx.weights(fx.BASELINE, c, iv, None)
    assert w1[w1 > 0].sum() == pytest.approx(1) and w1[w1 < 0].sum() == pytest.approx(-1)
    w2 = fx.weights("F2_carry_to_vol", c, iv, None)
    assert w2[w2 > 0].sum() == pytest.approx(1)
    longs = w2[w2 > 0]
    assert np.allclose(longs * iv[longs.index], (longs * iv[longs.index]).iloc[0])  # weight x vol is equal within a leg
    corr = pd.DataFrame(np.eye(9), index=fx.PAIRS, columns=fx.PAIRS)
    w3 = fx.weights("F3_carry_to_vol_targeted", c, iv, corr)
    names = w3.index[w3 != 0]
    vol = np.sqrt(((w3[names] * iv[names]) ** 2).sum())
    assert vol == pytest.approx(fx.TARGET_VOL) or abs(w3).sum() == pytest.approx(abs(w2).sum() * fx.MAX_SCALE)
    assert fx.weights(fx.BASELINE, c.iloc[:6].reindex(fx.PAIRS), iv, None).abs().sum() == 0


def test_validation_needs_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "ROOT", tmp_path)
    monkeypatch.setattr(fx, "PREREG", tmp_path / "p.jsonl")
    (tmp_path / "p.jsonl").write_text("")
    assert fx.validation_unlocked() is False


def _synthetic(days=200, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-04", periods=days)
    spot = pd.DataFrame({p: (150.0 if p == "USDJPY" else 1.0) * np.exp(np.cumsum(rng.normal(0, 0.005, days))) for p in fx.PAIRS}, index=idx)
    pts = pd.DataFrame({p: rng.normal(0, 3, days) for p in fx.PAIRS}, index=idx)
    iv = pd.DataFrame({p: 0.08 + 0.02 * rng.random(days) for p in fx.PAIRS}, index=idx)
    return spot, pts, iv


def test_book_does_not_use_later_data():
    spot, pts, iv = _synthetic()
    cut = spot.index[120]
    a = fx.run_book("F2_carry_to_vol", spot, pts, iv, spot.index[0], spot.index[-1], 1.0)
    spot2, pts2, iv2 = spot.copy(), pts.copy(), iv.copy()
    later = spot2.index > cut + pd.Timedelta(days=10)
    spot2.loc[later] *= 1.5
    pts2.loc[later] *= -1
    iv2.loc[later] *= 2
    b = fx.run_book("F2_carry_to_vol", spot2, pts2, iv2, spot.index[0], spot.index[-1], 1.0)
    early = a.index[a["exit"] <= cut + pd.Timedelta(days=10)]
    pd.testing.assert_frame_equal(a.loc[early], b.loc[early])
