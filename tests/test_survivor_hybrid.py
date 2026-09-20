"""Survivor hybrids (research/survivor_hybrid): selection sees only data through 2014-12, weights use
trailing data only, haircut schedule, registration guard."""
import json
import hashlib

import numpy as np
import pandas as pd
import pytest

from research.survivor_hybrid import core as C
from research.survivor_hybrid import evaluate as E

IDX = pd.date_range("1990-01-31", "2024-12-31", freq="ME")


def _doc(rows):
    d = pd.DataFrame(rows).set_index("Acronym")
    for c, v in {"Cat.Economic": "valuation", "Portfolio Period": 1.0, "Stock Weight": "EW",
                 "LongDescription": "x", "mech": "M6", "data_src": "accounting"}.items():
        if c not in d:
            d[c] = v
    return d


def _panel(seed=0, cols=("A", "B")):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(0.002, 0.02, (len(IDX), len(cols))), index=IDX, columns=list(cols))


def test_selection_rule_synthetic():
    doc = _doc([{"Acronym": "A", "Year": 2000, "SampleEndYear": 1995},
                {"Acronym": "B", "Year": 2011, "SampleEndYear": 2005}])   # published after 2009
    op = pd.DataFrame(0.0, index=IDX, columns=["A", "B"])
    rng = np.random.default_rng(1)
    op[:] = rng.normal(0.01, 0.02, op.shape)     # strong everywhere: t >> 2
    s = C.select_survivors(doc, op, op)
    assert s.loc["A", "selected"] and not s.loc["B", "selected"]
    assert not s.loc["B", "c1_pub"]
    # killing the post-publication mean (2001-2014) removes A
    op2 = op.copy()
    op2.loc["2001":"2014", "A"] = -0.01 + rng.normal(0, 0.001, op2.loc["2001":"2014"].shape[0])
    assert not C.select_survivors(doc, op2, op)["selected"]["A"]
    # a weak large-cap version removes A
    lc = op.copy()
    lc["A"] = rng.normal(0.0, 0.05, len(IDX)) - 0.01
    assert not C.select_survivors(doc, op, lc).loc["A", "c4_lc_ps"]


def test_selection_ignores_post_2014_data_synthetic():
    doc = _doc([{"Acronym": "A", "Year": 2000, "SampleEndYear": 1995},
                {"Acronym": "B", "Year": 1990, "SampleEndYear": 1985}])
    op, lc = _panel(2), _panel(3)
    base = C.select_survivors(doc, op, lc)
    op2, lc2 = op.copy(), lc.copy()
    op2.loc["2015":] = 1.0      # absurd future returns
    lc2.loc["2015":] = -1.0
    pd.testing.assert_frame_equal(base, C.select_survivors(doc, op2, lc2))
    pd.testing.assert_frame_equal(base, C.select_survivors(doc, op.loc[:"2014"], lc.loc[:"2014"]))


def test_selection_ignores_post_2014_data_real():
    doc = C.load_doc()
    op, lc, vw = C.load_ls("op"), C.load_ls("me_gt_nyse20"), C.load_ls("q5_vw")
    ref = C.select_survivors(doc, op.loc[:C.CUTOFF], lc.loc[:C.CUTOFF], vw.loc[:C.CUTOFF])
    def flip(w):   # scramble every post-2014 month
        w = w.copy()
        late = w.index > C.CUTOFF
        w.loc[late] = -10 * w.loc[late] + 0.05
        return w
    got = C.select_survivors(doc, flip(op), flip(lc), flip(vw))
    pd.testing.assert_frame_equal(ref, got)


def test_registered_survivor_list_matches_rule():
    s = pd.read_csv(E.SURVIVORS, index_col=0)
    fresh = E.survivors_table()
    assert fresh["selected"].astype(bool).equals(s["selected"].astype(bool))
    assert int(s["selected"].sum()) == 53


def test_trailing_vol_is_strictly_past():
    r = _panel(4)
    v = C.trailing_vol(r)
    t = 100
    assert v.iloc[t, 0] == pytest.approx(r.iloc[t - 36:t, 0].std())
    r2 = r.copy()
    r2.iloc[t:] = 5.0          # change month t and later
    pd.testing.assert_series_equal(C.trailing_vol(r2).iloc[t], v.iloc[t])


@pytest.mark.parametrize("fn", ["inv_vol", "group"])
def test_weights_use_trailing_data_only(fn):
    r = _panel(5, cols=("A", "B", "C", "D"))
    groups = {"M1": ["A"], "M4": ["B", "C", "D"]}
    make = (lambda x: C.weights_inv_vol(x)) if fn == "inv_vol" else (lambda x: C.weights_group_risk(x, groups))
    w = make(r)
    t = 200
    r2 = r.copy()
    r2.iloc[t:] = r2.iloc[t:] * -7 + 0.3      # new values from month t on, same availability
    w2 = make(r2)
    pd.testing.assert_frame_equal(w.iloc[: t + 1], w2.iloc[: t + 1])
    assert np.allclose(w.iloc[40:].sum(axis=1), 1.0)
    if fn == "group":   # equal risk across groups: group weights ∝ 1/trailing group vol
        g = C.group_returns(r, groups)
        inv = 1 / C.trailing_vol(g).iloc[t]
        assert w.iloc[t]["A"] == pytest.approx(inv["M1"] / inv.sum())
        assert w.iloc[t][["B", "C", "D"]].nunique() == 1


def test_equal_weights_skip_missing():
    r = _panel(6, cols=("A", "B", "C"))
    r.iloc[10, 1] = np.nan
    w = C.weights_equal(r)
    assert w.iloc[10].tolist() == [0.5, 0.0, 0.5]
    assert w.iloc[11].tolist() == pytest.approx([1 / 3] * 3)


def test_haircut_schedule_and_combine():
    assert [C.haircut_multiplier(p) for p in [1, 3, 6, 12, 36, np.nan]] == pytest.approx([1, .5, 1/3, 1/3, 1/3, 1])
    pp = pd.Series({"A": 1.0, "B": 12.0})
    c = C.component_haircut(pp, 30.0)
    assert c["A"] == pytest.approx(0.0030) and c["B"] == pytest.approx(0.0010)
    r = pd.DataFrame({"A": [0.01, 0.02], "B": [0.00, np.nan]}, index=IDX[:2])
    w = pd.DataFrame({"A": [0.5, 1.0], "B": [0.5, 0.0]}, index=IDX[:2])
    out = C.combine(r, w, c)
    assert out["gross"].tolist() == pytest.approx([0.005, 0.02])
    assert out["net"].tolist() == pytest.approx([0.005 - 0.002, 0.02 - 0.003])


def test_plan_guard(tmp_path):
    plan = tmp_path / "PLAN.md"
    plan.write_text("rules")
    reg = tmp_path / "prereg.jsonl"
    reg.write_text(json.dumps({"file": "p/PLAN.md", "sha256": "0" * 64}) + "\n")
    assert not E.plan_registered(plan, reg, "p/PLAN.md")
    reg.write_text(json.dumps({"file": "p/PLAN.md", "sha256": hashlib.sha256(b"rules").hexdigest()}) + "\n")
    assert E.plan_registered(plan, reg, "p/PLAN.md")
    plan.write_text("rules changed")
    assert not E.plan_registered(plan, reg, "p/PLAN.md")
