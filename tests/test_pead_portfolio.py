"""Tests for research/pead_portfolio: no look-ahead in betas and weights, timing, cost accounting."""
import numpy as np
import pandas as pd
import pytest

from research.pead_portfolio import construct as C
from research.pead_portfolio.evaluate import ceilings, max_dd, paired_test, sharpe


def synth(n=500, seed=1, start="2021-01-04"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    m = rng.normal(0.0004, 0.01, n)
    d = pd.DataFrame({"M": m, "P": 0.35 * m + rng.normal(0.0002, 0.005, n),
                      "tsmom_broad": rng.normal(0.0001, 0.007, n), "fx_carry": rng.normal(0.0001, 0.004, n),
                      "bond_carry": rng.normal(0.0, 0.006, n), "G": 0.8}, index=idx)
    d.loc[idx[:150], "fx_carry"] = np.nan  # late-starting sleeve
    return d


def perturb_after(d, pos, seed=9):
    e = d.copy()
    rng = np.random.default_rng(seed)
    cols = ["M", "P", "tsmom_broad", "fx_carry", "bond_carry"]
    e.iloc[pos + 1:, [e.columns.get_loc(c) for c in cols]] *= rng.normal(3, 2, size=(len(e) - pos - 1, len(cols)))
    return e


BUILDERS = {
    "B1": C.targets_b1,
    "B2": C.targets_b2,
    "B3": lambda d: C.targets_rp(d, ("tsmom_broad",), hedged=False),
    "B4": lambda d: C.targets_rp(d, C.SLEEVES_B4, hedged=False),
    "B5": lambda d: C.targets_rp(d, C.SLEEVES_B4, hedged=True),
}


@pytest.mark.parametrize("name", list(BUILDERS))
def test_targets_use_no_future_data(name):
    d = synth()
    cut = 300
    a, b = BUILDERS[name](d), BUILDERS[name](perturb_after(d, cut))
    past = a.index[a.index <= d.index[cut]]
    assert len(past) > 5
    pd.testing.assert_frame_equal(a.loc[past], b.loc[past])
    assert not a.loc[a.index > d.index[cut]].equals(b.loc[b.index > d.index[cut]])  # the perturbation bites


@pytest.mark.parametrize("name", list(BUILDERS))
def test_construction_returns_use_no_future_data(name):
    d = synth()
    cut = 320
    rets = lambda x: pd.DataFrame({"P": x["P"], "H": x["M"], **{s: x[s] for s in C.SLEEVES_B4}})
    e = perturb_after(d, cut)
    ra = C.simulate(rets(d), BUILDERS[name](d), d["G"])["ret"]
    rb = C.simulate(rets(e), BUILDERS[name](e), e["G"])["ret"]
    np.testing.assert_array_equal(ra.iloc[:cut + 1].to_numpy(), rb.iloc[:cut + 1].to_numpy())


def test_beta_estimate_window_and_clamp():
    rng = np.random.default_rng(3)
    m = rng.normal(0, 0.01, 400)
    p = 0.4 * m + rng.normal(0, 0.001, 400)
    assert C.beta_at(p, m) == pytest.approx(0.4, abs=0.02)
    # only the last 126 observations matter
    p2 = p.copy()
    p2[:-126] = rng.normal(0, 0.05, 400 - 126)
    assert C.beta_at(p2, m) == C.beta_at(p, m)
    assert C.beta_at(-p, m) == 0.0
    assert C.beta_at(5 * m, m) == 1.5


def test_decisions_need_63_obs_and_lag_two():
    d = synth(n=300)
    pos = C.decision_positions(d.index)
    assert pos[0] + 1 >= 63
    assert all(d.index[p].month != d.index[p + 1].month for p in pos)  # month-ends
    assert C.first_effective_date(d.index) == d.index[pos[0] + 2]


def test_warmup_and_lag_equal_pead_until_effective():
    d = synth()
    rets = pd.DataFrame({"P": d["P"], "H": d["M"]})
    tg = C.targets_b1(d)
    sim = C.simulate(rets, tg, d["G"])
    first = d.index.get_loc(tg.index[0]) + 2
    np.testing.assert_allclose(sim["ret"].iloc[:first].to_numpy(), d["P"].iloc[:first].to_numpy())
    assert sim["w_H"].iloc[first - 1] == 0.0 and sim["w_H"].iloc[first] == pytest.approx(tg["H"].iloc[0])


def test_b2_weight_cap_and_normalisation():
    calm_end = np.r_[np.random.default_rng(0).normal(0, 0.01, 200), np.full(30, 1e-6)]
    assert C.b2_weight_at(calm_end) == 2.0
    flat = np.random.default_rng(1).normal(0, 0.01, 5000)
    assert C.b2_weight_at(flat) == pytest.approx(1.0, abs=0.35)


def test_rp_equal_risk_and_vol_match():
    rng = np.random.default_rng(4)
    n = 252
    h = pd.DataFrame({"P": rng.normal(0, 0.01, n), "s": rng.normal(0, 0.02, n), "late": np.r_[np.full(200, np.nan), rng.normal(0, 0.01, 52)]})
    w = C.rp_weights(h, "P")
    assert w["late"] == 0.0  # fewer than 63 observations: does not take part
    sig = h[["P", "s"]].std()
    assert w["P"] * sig["P"] == pytest.approx(w["s"] * sig["s"])
    v = np.array([w["P"], w["s"]])
    ex_ante = np.sqrt(v @ h[["P", "s"]].cov().to_numpy() @ v)
    assert ex_ante == pytest.approx(sig["P"])


def test_cost_accounting_exact():
    idx = pd.bdate_range("2021-01-04", periods=45)  # ends 2021-03-05: no roll day
    rets = pd.DataFrame(0.0, index=idx, columns=["P", "H", "tsmom_broad"])
    tg = pd.DataFrame({"P": [0.5], "H": [-0.4], "tsmom_broad": [0.3]}, index=[idx[40]])
    G = pd.Series(0.8, index=idx)
    sim = C.simulate(rets, tg, G, C.Costs())
    expect = 0.0005 * 0.5 * 0.8 + 0.0001 * 0.4 + 0.0010 * 0.3
    assert sim["cost"].iloc[42] == pytest.approx(expect)
    assert sim["ret"].iloc[42] == pytest.approx(-expect)
    assert sim["cost"].drop(idx[42]).abs().sum() == 0.0
    assert sim["fin"].abs().sum() == 0.0
    stressed = C.simulate(rets, tg, G, C.Costs().stressed())
    assert stressed["cost"].iloc[42] == pytest.approx(3 * expect)


def test_roll_and_financing_costs():
    idx = pd.bdate_range("2021-02-01", periods=60)
    rolls = C.roll_days(idx)
    assert list(idx[rolls]) == [pd.Timestamp("2021-03-10")]
    rets = pd.DataFrame(0.0, index=idx, columns=["P", "H"])
    tg = pd.DataFrame({"P": [1.5], "H": [-0.5]}, index=[idx[2]])
    G = pd.Series(0.9, index=idx)
    sim = C.simulate(rets, tg, G, C.Costs())
    day = idx.get_loc(pd.Timestamp("2021-03-10"))
    trade = sim["cost"].iloc[4]
    assert trade == pytest.approx(0.0005 * 0.5 * 0.9 + 0.0001 * 0.5)
    assert sim["cost"].iloc[day] == pytest.approx(0.0002 * abs(sim["w_H"].iloc[day]))
    assert abs(sim["w_H"].iloc[day]) == pytest.approx(0.5, rel=1e-3)  # drifts only by cost/financing
    assert sim["fin"].iloc[4] == pytest.approx(0.015 / 252 * (1.5 * 0.9 - 1))  # first day at w_P = 1.5
    assert sim["fin"].iloc[5] == pytest.approx(0.015 / 252 * (sim["w_P"].iloc[5] * 0.9 - 1))
    assert sim["fin"].iloc[3] == 0.0  # w_P was still 1 (0.9 gross) before the trade


def test_weights_drift_between_rebalances():
    idx = pd.bdate_range("2021-01-04", periods=10)
    rets = pd.DataFrame({"P": [0.0] * 5 + [0.10] + [0.0] * 4, "H": [0.0] * 10})
    rets.index = idx
    tg = pd.DataFrame({"P": [1.0], "H": [-0.5]}, index=[idx[1]])
    sim = C.simulate(rets, tg, pd.Series(0.0, index=idx), C.Costs(hedge_side=0, stock_side=0))
    r = sim["ret"].iloc[5]
    assert r == pytest.approx(0.10)
    assert sim["w_P"].iloc[6] == pytest.approx(1.10 / 1.10)
    assert sim["w_H"].iloc[6] == pytest.approx(-0.5 / 1.10)


def test_missing_return_for_active_sleeve_raises():
    idx = pd.bdate_range("2021-01-04", periods=10)
    rets = pd.DataFrame({"P": 0.0, "s": np.r_[np.zeros(6), np.nan, np.zeros(3)]}, index=idx)
    tg = pd.DataFrame({"P": [1.0], "s": [0.5]}, index=[idx[1]])
    with pytest.raises(ValueError):
        C.simulate(rets, tg, pd.Series(0.5, index=idx))


def test_paired_test_and_helpers():
    rng = np.random.default_rng(5)
    p = rng.normal(0.0002, 0.01, 1000)
    same = paired_test(p, p, draws=500)
    assert same["delta_sharpe"] == 0.0 and same["p_one_sided"] > 0.5
    better = paired_test(p + 0.002, p, draws=500)
    assert better["p_one_sided"] < 0.01
    assert max_dd(np.array([0.1, -0.5, 0.2])) == pytest.approx(-0.5)
    assert sharpe(np.array([0.01, 0.03])) == pytest.approx(0.02 / np.std([0.01, 0.03], ddof=1) * np.sqrt(252))
    s, R = np.array([0.5, 0.5]), np.eye(2)
    c = ceilings(s, R, [False, False])
    assert c["unconstrained"] == pytest.approx(np.sqrt(0.5))
    assert c["equal_risk"] == pytest.approx(np.sqrt(0.5))
