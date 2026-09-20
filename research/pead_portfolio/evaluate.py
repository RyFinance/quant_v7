"""Run the registered PEAD portfolio-construction test (research/pead_portfolio/PLAN.md).

Run: PYTHONPATH=. .venv/bin/python -m research.pead_portfolio.evaluate
Refuses to run if PLAN.md differs from its registered sha256.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from research.common.inference import null_kind, sharpe_ci
from research.options_signals.signals import french_daily
from research.pead_audit.mtm_audit import ols_hac
from research.pead_portfolio import construct as C
from research.pead_portfolio import data as D

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "research/pead_portfolio/PLAN.md"
OUT = ROOT / "reports/pead_portfolio"
N_CONSTRUCTIONS = 5
ALPHA = 0.05 / N_CONSTRUCTIONS
BLOCK, DRAWS, SEED = 21, 5000, 20260918
SLEEVES = ["tsmom_broad", "fx_carry", "bond_carry"]
NAMES = ["B1_beta_hedged", "B2_vol_managed", "B3_pead_tsmom", "B4_pead_3sleeves", "B5_hedged_3sleeves"]
FORWARD_PRIOR = {"P": 0.60, "tsmom_broad": 0.21, "fx_carry": 0.25, "bond_carry": 0.13}


def registered_at() -> str:
    reg = [json.loads(l) for l in (ROOT / "research/preregistrations.jsonl").read_text().splitlines() if l.strip()]
    rec = [r for r in reg if r["file"] == "research/pead_portfolio/PLAN.md"]
    if not rec or rec[-1]["sha256"] != hashlib.sha256(PLAN.read_bytes()).hexdigest():
        raise SystemExit("PLAN.md is unregistered or changed since registration; register an amendment instead")
    return rec[-1]["registered_at"]


# ---------------------------------------------------------------- statistics

def sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * np.sqrt(252))


def max_dd(x: np.ndarray) -> float:
    wealth = np.r_[1.0, np.cumprod(1 + np.asarray(x, float))]
    return float((wealth / np.maximum.accumulate(wealth) - 1).min())


def cagr(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    return float(np.prod(1 + x) ** (252 / len(x)) - 1)


def paired_test(c: np.ndarray, p: np.ndarray, block: int = BLOCK, draws: int = DRAWS, seed: int = SEED) -> dict:
    """Paired circular block bootstrap. Primary: dSR = SR_c - SR_p (equal-risk comparison).
    Secondary: raw mean of c - p. One-sided centred p-values."""
    c, p = np.asarray(c, float), np.asarray(p, float)
    n = len(c)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    dsr, dm = np.empty(draws), np.empty(draws)
    for a in range(0, draws, 500):
        k = min(500, draws - a)
        starts = rng.integers(0, n, size=(k, nb))
        idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(k, -1)[:, :n] % n
        cc, pp = c[idx], p[idx]
        dsr[a:a + k] = (cc.mean(1) / cc.std(1, ddof=1) - pp.mean(1) / pp.std(1, ddof=1)) * np.sqrt(252)
        dm[a:a + k] = (cc - pp).mean(1)
    D0 = sharpe(c) - sharpe(p)
    M0 = float((c - p).mean())
    return {"delta_sharpe": D0, "p_one_sided": float((1 + np.sum(dsr - D0 >= D0)) / (draws + 1)),
            "delta_sharpe_ci95": [float(np.quantile(dsr, .025)), float(np.quantile(dsr, .975))],
            "raw_mean_diff_ann": M0 * 252, "p_raw_mean_diff": float((1 + np.sum(dm - M0 >= M0)) / (draws + 1))}


def describe(x: pd.Series, d: pd.DataFrame, pead: pd.Series | None = None) -> dict:
    v = x.to_numpy()
    b, t = ols_hac(v, d["MKT"].reindex(x.index).to_numpy())
    out = {"days": len(v), "start": str(x.index[0].date()), "end": str(x.index[-1].date()),
           "sharpe": sharpe(v), "sharpe_ci95": list(sharpe_ci(v, 252, BLOCK, DRAWS)),
           "excess_cagr": cagr(v), "vol": float(v.std(ddof=1) * np.sqrt(252)), "max_dd": max_dd(v),
           "beta_mkt": float(b[1]), "alpha_ann": float(b[0] * 252), "alpha_t": float(t[0])}
    if pead is not None:
        pv = pead.reindex(x.index).to_numpy()
        out["corr_with_pead"] = float(np.corrcoef(v, pv)[0, 1])
        k = pv.std(ddof=1) / v.std(ddof=1)
        out["max_dd_vol_matched"] = max_dd(v * k)
        out["vol_match_scale"] = float(k)
    return out


def usage(sim: pd.DataFrame, start: pd.Timestamp) -> dict:
    s = sim.loc[start:]
    yrs = len(sim) / 252
    w = {c[2:]: float(s[c].mean()) for c in s.columns if c.startswith("w_")}
    return {"avg_weights_after_warmup": w, "turnover_per_year": float(sim["turnover"].sum() / yrs),
            "cost_drag_per_year": float(sim["cost"].sum() / yrs), "financing_drag_per_year": float(sim["fin"].sum() / yrs)}


# ---------------------------------------------------------------- ceiling

def _risk_sharpe(v, s, R):
    return float(v @ s / np.sqrt(v @ R @ v))


def ceilings(s: np.ndarray, R: np.ndarray, free: list[bool]) -> dict:
    """Max Sharpe of a combination of assets with Sharpes s and correlation R (risk weights v)."""
    unc = float(np.sqrt(s @ np.linalg.solve(R, s)))
    k = len(s)
    bounds = [(None, None) if f else (0.0, None) for f in free]
    best = -np.inf
    rng = np.random.default_rng(0)
    for trial in range(30):
        v0 = np.abs(rng.normal(size=k)) + 0.1
        r = minimize(lambda v: -_risk_sharpe(v, s, R) if np.linalg.norm(v) > 1e-9 else 0.0, v0,
                     bounds=bounds, method="L-BFGS-B")
        if r.success or r.status == 0:
            best = max(best, -r.fun)
    eq = float(s.sum() / np.sqrt(np.ones(k) @ R @ np.ones(k)))
    tang = np.linalg.solve(R, s)
    return {"unconstrained": unc, "constrained_long_only": float(best), "equal_risk": eq,
            "tangency_risk_weights": (tang / np.abs(tang).sum()).round(3).tolist()}


def ceiling_block(d: pd.DataFrame, cols: list[str], label: str) -> dict:
    X = d[cols].dropna()
    s = np.array([sharpe(X[c]) for c in cols])
    R = X.corr().to_numpy()
    idx = [i for i, c in enumerate(cols) if c != "M"]
    out = {"window": [str(X.index[0].date()), str(X.index[-1].date())], "days": len(X),
           "sharpes": dict(zip(cols, s.round(3).tolist())), "corr": X.corr().round(3).to_dict(),
           "set_A_no_market": ceilings(s[idx], R[np.ix_(idx, idx)], [False] * len(idx))}
    if "M" in cols:
        out["set_B_with_market_free_sign"] = ceilings(s, R, [c == "M" for c in cols])
        y, x = X["P"].to_numpy(), X["M"].to_numpy()
        b = np.polyfit(x, y, 1)
        resid = y - np.polyval(b, x)
        out["pead_appraisal_ratio_vs_spy"] = float(b[1] / resid.std(ddof=1) * np.sqrt(252))
        out["pead_beta_to_spy"] = float(b[0])
    out["label"] = label
    return out


# ---------------------------------------------------------------- main

def run_window(d: pd.DataFrame, costs: C.Costs) -> dict[str, pd.DataFrame]:
    rets = pd.DataFrame({"P": d["P"], "H": d["M"], **{s: d[s] for s in SLEEVES}}, index=d.index)
    return {name: C.simulate(rets, tg, d["G"], costs) for name, tg in C.all_targets(d).items()}


def evaluate_window(d: pd.DataFrame, sims: dict, stress: dict) -> dict:
    start = C.first_effective_date(d.index)
    res = {"PEAD": describe(d["P"], d), "first_effective_date": str(start.date()),
           "PEAD_after_warmup": describe(d["P"].loc[start:], d)}
    for name, sim in sims.items():
        x = sim["ret"]
        r = describe(x, d, d["P"])
        r["paired"] = paired_test(x.to_numpy(), d["P"].to_numpy())
        r["paired"]["null_kind_dSR_at_0.3"] = null_kind(tuple(r["paired"]["delta_sharpe_ci95"]), 0.3)
        r["after_warmup"] = {"sharpe": sharpe(x.loc[start:]), "pead_sharpe": sharpe(d["P"].loc[start:]),
                             "paired": paired_test(x.loc[start:].to_numpy(), d["P"].loc[start:].to_numpy())}
        r["stress_costs_x3"] = {"sharpe": sharpe(stress[name]["ret"])}
        r.update(usage(sim, start))
        res[name] = r
    return res


def main() -> dict:
    reg = registered_at()
    OUT.mkdir(parents=True, exist_ok=True)
    main_d, old_d = D.load_main(), D.load_old()
    out = {"plan_registered_at": reg, "alpha_bonferroni": ALPHA, "windows": {}}
    for wname, d in (("main", main_d), ("old", old_d)):
        sims = run_window(d, C.Costs())
        stress = run_window(d, C.Costs().stressed())
        out["windows"][wname] = evaluate_window(d, sims, stress)
        daily = pd.DataFrame({"PEAD": d["P"], **{k: v["ret"] for k, v in sims.items()}})
        daily.to_csv(OUT / f"daily_excess_{wname}.csv")
        pd.concat({k: v.filter(like="w_") for k, v in sims.items()}, axis=1).to_csv(OUT / f"weights_{wname}.csv")
    # verdicts
    verdict = {}
    for name in NAMES:
        m, o = out["windows"]["main"], out["windows"]["old"]
        c1 = m[name]["sharpe"] > m["PEAD"]["sharpe"]
        c2 = m[name]["paired"]["p_one_sided"] < ALPHA
        c3 = m[name]["max_dd_vol_matched"] >= m["PEAD"]["max_dd"]
        c4 = o[name]["sharpe"] > o["PEAD"]["sharpe"]
        verdict[name] = {"C1_beats_pead_sharpe": bool(c1), "C2_paired_p": bool(c2), "C3_drawdown": bool(c3),
                         "C4_old_window": bool(c4), "PASS": bool(c1 and c2 and c3 and c4)}
    out["verdict"] = verdict
    # ceiling
    ff = french_daily()
    pre = ff.loc["1927-01-01":"2021-07-31"]
    mkt_prior = float(pre["mkt_rf"].mean() / pre["mkt_rf"].std(ddof=1) * np.sqrt(252))
    cols = ["P", "tsmom_broad", "fx_carry", "bond_carry", "M"]
    ceil_main = ceiling_block(main_d, cols, "main window, in-sample")
    X = main_d[cols].dropna()
    R = X.corr().to_numpy()
    s_prior = np.array([FORWARD_PRIOR["P"], FORWARD_PRIOR["tsmom_broad"], FORWARD_PRIOR["fx_carry"],
                        FORWARD_PRIOR["bond_carry"], mkt_prior])
    ceil_main["forward_prior"] = {"inputs": dict(zip(cols, s_prior.round(3).tolist())),
                                  "set_A_no_market": ceilings(s_prior[:4], R[:4, :4], [False] * 4),
                                  "set_B_with_market_free_sign": ceilings(s_prior, R, [False] * 4 + [True])}
    out["ceiling"] = {"main": ceil_main,
                      "old_without_fx": ceiling_block(old_d, ["P", "tsmom_broad", "bond_carry", "M"], "old, 2004-02+"),
                      "old_with_fx": ceiling_block(old_d, cols, "old, fx overlap 2009-02+")}
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    res = main()
    for w in ("main", "old"):
        W = res["windows"][w]
        print(f"[{w}] PEAD SR {W['PEAD']['sharpe']:.3f} DD {W['PEAD']['max_dd']:.3f} first eff {W['first_effective_date']}")
        for k, v in W.items():
            if k.startswith("B"):
                print(f"  {k:20s} SR {v['sharpe']:.3f} CI[{v['sharpe_ci95'][0]:.2f},{v['sharpe_ci95'][1]:.2f}] "
                      f"dSR {v['paired']['delta_sharpe']:+.3f} p {v['paired']['p_one_sided']:.3f} "
                      f"DDvm {v['max_dd_vol_matched']:.3f} DD {v['max_dd']:.3f} beta {v['beta_mkt']:.2f} rho {v['corr_with_pead']:.2f}")
    print(json.dumps(res["verdict"], indent=1))
