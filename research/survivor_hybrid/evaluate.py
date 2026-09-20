"""Survivor hybrids H1-H4 of OSAP predictors (rules: research/survivor_hybrid/PLAN.md).

  select : selection on data through 2014-12 only -> reports/survivor_hybrid/survivors.csv
           (allowed before registration; loads nothing after CUTOFF)
  run    : builds H1-H4 and the controls and evaluates 2015-01 .. last OSAP month. Refuses to run
           unless PLAN.md's sha256 is registered in research/preregistrations.jsonl.

Reproduce: PYTHONPATH=. .venv/bin/python research/survivor_hybrid/evaluate.py select|run
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.survivor_hybrid import core as C

ROOT = C.ROOT
PLAN = "research/survivor_hybrid/PLAN.md"
PREREG = ROOT / "research/preregistrations.jsonl"
OUT = ROOT / "reports/survivor_hybrid"
SURVIVORS = OUT / "survivors.csv"

N_TRIALS = 84                 # about 80 project trials before this study + these 4 hybrids
TRIAL_SR_VAR = 0.25 / 12      # per-month Sharpe variance = annual cross-trial SD 0.5 (letf convention)
BLOCK, DRAWS = 6, 5000        # months per bootstrap block
GATE_SR, GATE_DSR = 0.75, 0.95
CONSEQUENTIAL = 0.5
HYBRIDS = ["H1", "H2", "H3", "H4"]
CONTROLS = ["C0", "C0_LC"]
IS_START = pd.Timestamp("2005-01-31")  # selection-period context window (in-sample)


def plan_registered(plan: Path = ROOT / PLAN, prereg: Path = PREREG, rel: str = PLAN) -> bool:
    if not plan.exists() or not prereg.exists():
        return False
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    for line in prereg.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("file") == rel and rec.get("sha256") == digest:
                return True
    return False


# -- selection (pre-2015 only) -------------------------------------------------------------------
def survivors_table() -> pd.DataFrame:
    doc = C.load_doc()
    return C.select_survivors(doc, C.load_ls("op", C.CUTOFF), C.load_ls("me_gt_nyse20", C.CUTOFF),
                              C.load_ls("q5_vw", C.CUTOFF))


def cmd_select() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    s = survivors_table()
    s.to_csv(SURVIVORS, float_format="%.4f")
    sel = s[s.selected]
    print(f"{len(sel)} survivors of {len(s)}; eligible by publication year: {int(s.c1_pub.sum())}")
    print(sel.mech.value_counts().to_dict())
    print("sha256", hashlib.sha256(SURVIVORS.read_bytes()).hexdigest())
    return s


# -- construction --------------------------------------------------------------------------------
def lc_panel(names: list[str], lc_version: pd.Series, w_vw: pd.DataFrame, w_lc: pd.DataFrame) -> pd.DataFrame:
    cols = {n: (w_vw[n] if lc_version[n] == C.LC_PRIMARY else w_lc[n]) for n in names}
    return pd.DataFrame(cols)


def build(s: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame]]:
    """{portfolio: {cost level: frame(gross, haircut, net, n_comp)}}, full history (weights trailing)."""
    w_op, w_vw, w_lc = C.load_ls("op"), C.load_ls("q5_vw"), C.load_ls("me_gt_nyse20")
    idx = w_op.index
    w_vw, w_lc = w_vw.reindex(idx), w_lc.reindex(idx)
    surv = s.index[s.selected].tolist()
    elig = s.index[s.c1_pub & s.index.isin(w_op.columns)].tolist()
    r_op, r_op_all = w_op[surv], w_op[elig]
    r_lc = lc_panel(surv, s.lc_version, w_vw, w_lc)
    r_lc_all = lc_panel(elig, s.lc_version, w_vw, w_lc)
    groups = {g: list(v) for g, v in s.loc[surv].groupby("mech").groups.items()}
    spec = {"H1": (r_op, C.weights_equal(r_op)),
            "H2": (r_op, C.weights_inv_vol(r_op)),
            "H3": (r_lc, C.weights_equal(r_lc)),
            "H4": (r_op, C.weights_group_risk(r_op, groups)),
            "C0": (r_op_all, C.weights_equal(r_op_all)),
            "C0_LC": (r_lc_all, C.weights_equal(r_lc_all))}
    out = {}
    for name, (r, w) in spec.items():
        out[name] = {lvl: C.combine(r, w, C.component_haircut(s.loc[r.columns, "pp"], rb))
                     for lvl, rb in C.HAIRCUT_R.items()}
        out[name]["_weights"] = w
    return out


def market_monthly() -> pd.Series:
    from research.options_signals.signals import french_daily
    f = french_daily()
    g = f.groupby(f.index + pd.offsets.MonthEnd(0))
    return (g.apply(lambda d: np.prod(1 + d.mkt_rf + d.rf) - np.prod(1 + d.rf))).rename("mkt_rf")


# -- statistics ----------------------------------------------------------------------------------
def max_drawdown(x: pd.Series) -> float:
    eq = (1 + x).cumprod()
    return float((eq / eq.cummax() - 1).min())


def sr(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std() * np.sqrt(12)) if len(x) > 2 and x.std() > 0 else float("nan")


def ols(y: pd.Series, x: pd.Series) -> dict:
    d = pd.concat([y, x], axis=1).dropna()
    X = np.column_stack([np.ones(len(d)), d.iloc[:, 1]])
    b, *_ = np.linalg.lstsq(X, d.iloc[:, 0], rcond=None)
    e = d.iloc[:, 0] - X @ b
    V = np.linalg.inv(X.T @ X) * (e @ e) / (len(d) - 2)
    return {"alpha_ann": float(b[0] * 12), "alpha_t": float(b[0] / np.sqrt(V[0, 0])), "beta": float(b[1]),
            "corr": float(np.corrcoef(d.iloc[:, 0], d.iloc[:, 1])[0, 1])}


def breakeven_r(fr: dict[str, pd.DataFrame], target: float) -> float:
    """Monthly-rebalance haircut R (bps) at which the net Sharpe equals target (linear in R)."""
    g = fr["base"]["gross"]
    h = fr["base"]["haircut"] / C.HAIRCUT_R["base"]    # decimal per 1 bp of R
    lo, hi = 0.0, 400.0
    f = lambda R: sr(g - R * h) - target
    if f(lo) < 0:
        return 0.0
    if f(hi) > 0:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def summarize(fr: dict[str, pd.DataFrame], mkt: pd.Series, lo: pd.Timestamp, hi: pd.Timestamp) -> dict:
    b = fr["base"].loc[lo:hi]
    net, gross = b["net"].dropna(), b["gross"].dropna()
    ci = sharpe_ci(net.to_numpy(), periods=12, block=BLOCK, draws=DRAWS)
    reg = ols(net, mkt)
    x = net.to_numpy()
    return {
        "months": int(len(net)), "start": str(net.index.min().date()), "end": str(net.index.max().date()),
        "n_components_avg": float(b["n_comp"].mean()), "haircut_bps_avg": float(b["haircut"].mean() * 1e4),
        "sharpe_gross": sr(gross), "sharpe_net": sr(net),
        "sharpe_net_low": sr(fr["low"].loc[lo:hi, "net"]), "sharpe_net_high": sr(fr["high"].loc[lo:hi, "net"]),
        "ann_mean_gross": float(gross.mean() * 12), "ann_mean_net": float(net.mean() * 12),
        "ann_vol": float(net.std() * np.sqrt(12)),
        "ci95": list(ci), "null_kind_0.5": null_kind(ci, CONSEQUENTIAL), "null_kind_0.75": null_kind(ci, GATE_SR),
        "dsr": deflated_sharpe(x, N_TRIALS, TRIAL_SR_VAR),
        "maxdd_net": max_drawdown(net), "maxdd_gross": max_drawdown(gross),
        "worst_month": float(net.min()), "skew": float(net.skew()), "exkurt": float(net.kurt()),
        "corr_mkt": reg["corr"], "beta_mkt": reg["beta"], "alpha_ann": reg["alpha_ann"], "alpha_t": reg["alpha_t"],
        "sharpe_net_2015_2019": sr(net.loc[:"2019-12-31"]), "sharpe_net_2020_end": sr(net.loc["2020-01-01":]),
        "breakeven_R_bps_sr0.75": breakeven_r({k: v.loc[lo:hi] for k, v in fr.items() if k != "_weights"}, GATE_SR),
        "breakeven_R_bps_sr0": breakeven_r({k: v.loc[lo:hi] for k, v in fr.items() if k != "_weights"}, 0.0),
        "net_by_year": {int(y): float((1 + v).prod() - 1) for y, v in net.groupby(net.index.year)},
    }


def cmd_run() -> dict:
    if not plan_registered():
        raise SystemExit(f"{PLAN} is not registered (sha256 not in {PREREG.name}); refusing to evaluate.")
    s = pd.read_csv(SURVIVORS, index_col=0)
    fresh = survivors_table()
    assert fresh["selected"].equals(s["selected"].astype(bool)), "selection differs from the registered list"
    res = build(s)
    mkt = market_monthly()
    last = max(v["base"]["net"].last_valid_index() for k, v in res.items())
    lo, hi = C.OOS_START, last
    out = {"window": [str(lo.date()), str(hi.date())], "n_trials": N_TRIALS, "trial_sr_var": TRIAL_SR_VAR,
           "portfolios": {}}
    for k in HYBRIDS + CONTROLS:
        out["portfolios"][k] = summarize(res[k], mkt, lo, hi)
        out["portfolios"][k]["in_sample_2005_2014_sharpe_gross"] = sr(res[k]["base"].loc[IS_START:C.CUTOFF, "gross"])
        out["portfolios"][k]["in_sample_2005_2014_sharpe_net"] = sr(res[k]["base"].loc[IS_START:C.CUTOFF, "net"])
    m = mkt.loc[lo:hi]
    out["market"] = {"sharpe": sr(m), "ann_mean": float(m.mean() * 12), "maxdd": max_drawdown(m)}
    # sensitivity (not gated): other trial-variance choices and N = 80
    nets = {k: res[k]["base"]["net"].loc[lo:hi].dropna() for k in HYBRIDS}
    per_month_sr = [v.mean() / v.std() for v in nets.values()]
    v_run = float(np.var(per_month_sr, ddof=1))
    T = len(next(iter(nets.values())))
    out["dsr_sensitivity"] = {k: {"n80_var0.25/12": deflated_sharpe(v.to_numpy(), 80, TRIAL_SR_VAR),
                                  "n84_within_run_var": deflated_sharpe(v.to_numpy(), N_TRIALS, v_run),
                                  "n84_sampling_var_1/(T-1)": deflated_sharpe(v.to_numpy(), N_TRIALS, 1 / (T - 1))}
                              for k, v in nets.items()}
    out["within_run_trial_sr_var"] = v_run
    # gates
    for k in HYBRIDS:
        p = out["portfolios"][k]
        p["gate"] = {"sharpe_net>=0.75": bool(p["sharpe_net"] >= GATE_SR), "ci_low>0": bool(p["ci95"][0] > 0),
                     "dsr>=0.95": bool(p["dsr"] >= GATE_DSR)}
        p["pass"] = bool(all(p["gate"].values()))
    out["any_pass"] = any(out["portfolios"][k]["pass"] for k in HYBRIDS)
    # correlations (net, OOS)
    frame = pd.DataFrame({k: res[k]["base"]["net"].loc[lo:hi] for k in HYBRIDS + CONTROLS}).join(m)
    out["corr"] = frame.corr().round(3).to_dict()
    # weights diagnostics
    for k in ["H2", "H4"]:
        w = res[k]["_weights"].loc[lo:hi]
        out["portfolios"][k]["avg_weights_top"] = w.mean().sort_values(ascending=False).head(10).round(4).to_dict()
    groups = s[s.selected].groupby("mech")
    w4 = res["H4"]["_weights"].loc[lo:hi]
    out["portfolios"]["H4"]["avg_group_weight"] = {g: float(w4[list(v.index)].sum(axis=1).mean()) for g, v in groups}
    # outputs
    OUT.mkdir(parents=True, exist_ok=True)
    rets = pd.concat({k: res[k]["base"].loc[lo:hi, ["gross", "net"]] for k in HYBRIDS + CONTROLS}, axis=1)
    rets.columns = [f"{a}_{b}" for a, b in rets.columns]
    rets.join(m).to_csv(OUT / "returns_oos.csv", float_format="%.6f")
    comp = component_table(s, lo, hi)
    comp.to_csv(OUT / "components_oos.csv", float_format="%.4f")
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def component_table(s: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
    """Descriptive only (computed after the hybrids): each survivor's own 2015+ statistics."""
    w_op, w_vw, w_lc = C.load_ls("op"), C.load_ls("q5_vw"), C.load_ls("me_gt_nyse20")
    sel = s[s.selected]
    rows = []
    for n, r in sel.iterrows():
        x = w_op[n].loc[lo:hi]
        z = (w_vw[n] if r.lc_version == C.LC_PRIMARY else w_lc[n]).loc[lo:hi]
        hc = C.haircut_multiplier(r.pp) * C.HAIRCUT_R["base"] / 1e4
        rows.append({"signal": n, "mech": r.mech, "data_src": r.data_src, "pp": r.pp,
                     "mean_pct_mo": x.mean() * 100, "sr_gross": sr(x), "sr_net_base": sr(x - hc),
                     "sr_lc_gross": sr(z), "lc_version": r.lc_version, "months": int(x.notna().sum())})
    return pd.DataFrame(rows).set_index("signal")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "run"])
    a = ap.parse_args()
    cmd_select() if a.cmd == "select" else cmd_run()
