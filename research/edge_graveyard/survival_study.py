"""Phase 1 graveyard study on Open Source Asset Pricing (Chen & Zimmermann, release 2025-10).

Inputs (downloaded once into data/osap/ by research/edge_graveyard/download_osap.sh):
  SignalDoc.csv, ls_op.parquet (original-paper method long-short), ls_q5_ew/ls_q5_vw (quintile
  LS, equal / value weight), ls_me_gt_nyse20 (stocks above NYSE 20th pct size), ls_nyse_only.
Outputs: reports/edge_graveyard/*.csv and tables printed for REPORT.md.

Periods (McLean & Pontiff 2016): IS = SampleStartYear..SampleEndYear; OOS = SampleEndYear+1..Year
(publication year); POST = Year+1..2024; P2015 = 2015..2024.
Meta-evidence only: CRSP universe, gross of costs, microcaps included.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from research.edge_graveyard.tags import tag

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data/osap"
OUT = ROOT / "reports/edge_graveyard"
OUT.mkdir(parents=True, exist_ok=True)

PERIODS = ["IS", "OOS", "POST", "P2015"]


def load_doc():
    doc = pd.read_csv(D / "SignalDoc.csv")
    doc = doc[doc["Cat.Signal"] == "Predictor"].copy()
    return tag(doc).set_index("Acronym")


def load_ls(name):
    x = pd.read_parquet(D / f"ls_{name}.parquet", columns=["signalname", "date", "ret"])
    return x.pivot(index="date", columns="signalname", values="ret")  # % per month


def period_masks(idx, r):
    y = idx.year
    return {"IS": (y >= r.SampleStartYear) & (y <= r.SampleEndYear),
            "OOS": (y > r.SampleEndYear) & (y <= r.Year),
            "POST": y > r.Year,
            "P2015": y >= 2015}


def stats(x):
    x = x.dropna()
    n = len(x)
    if n < 12:
        return dict(n=n, mean=np.nan, t=np.nan, sr=np.nan)
    m, s = x.mean(), x.std()
    return dict(n=n, mean=m, t=m / s * np.sqrt(n), sr=m / s * np.sqrt(12))


def per_predictor(doc, W, tagname):
    rows = []
    for sig, r in doc.iterrows():
        if sig not in W:
            continue
        x = W[sig]
        masks = period_masks(W.index, r)
        rec = {"signal": sig, "version": tagname}
        for p in PERIODS:
            for k, v in stats(x[masks[p]]).items():
                rec[f"{p}_{k}"] = v
        xi = x[masks["IS"]].dropna()
        rec["IS_skew"] = xi.skew()
        rec["IS_worst"] = xi.min()
        rec["IS_worst_z"] = (xi.min() - xi.mean()) / xi.std()
        cum = xi.cumsum()  # additive drawdown in % points (LS not compounded)
        rec["IS_maxdd_pp"] = (cum - cum.cummax()).min()
        rows.append(rec)
    return pd.DataFrame(rows).set_index("signal")


def clustered_ols(y, X, groups):
    """OLS with one-way cluster-robust SE (clusters = months)."""
    X = np.asarray(X, float); y = np.asarray(y, float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.pinv(X.T @ X)
    meat = np.zeros((X.shape[1], X.shape[1]))
    for g in pd.unique(groups):
        i = groups == g
        s = X[i].T @ e[i]
        meat += np.outer(s, s)
    G = len(pd.unique(groups)); n, k = X.shape
    V = XtXi @ meat @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    return b, np.sqrt(np.diag(V))


def hc_ols(y, X):
    X = np.asarray(X, float); y = np.asarray(y, float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.pinv(X.T @ X)
    V = XtXi @ (X.T * e**2) @ X @ XtXi * len(y) / (len(y) - X.shape[1])
    return b, np.sqrt(np.diag(V))


def mp_regression(doc, W, min_is_t=0.0, scaled=True):
    """McLean-Pontiff pooled regression: R_it / mean_IS_i = a_i + b1*OOS + b2*POST, month clusters.
    Returns decay as a fraction of in-sample mean."""
    parts = []
    for sig, r in doc.iterrows():
        if sig not in W:
            continue
        x = W[sig].dropna()
        m = period_masks(x.index, r)
        xi = x[m["IS"]]
        is_mean = xi.mean()
        if not np.isfinite(is_mean) or is_mean <= 0 or len(xi) < 24:
            continue
        if is_mean / xi.std() * np.sqrt(len(xi)) < min_is_t:
            continue
        if not scaled:
            is_mean = 1.0
        keep = m["IS"] | m["OOS"] | m["POST"]
        parts.append(pd.DataFrame({"sig": sig, "date": x.index[keep], "y": (x[keep] / is_mean).values,
                                   "OOS": m["OOS"][keep].astype(float), "POST": m["POST"][keep].astype(float)}))
    P = pd.concat(parts, ignore_index=True)
    # demean y and regressors within predictor (fixed effects)
    for c in ["y", "OOS", "POST"]:
        P[c + "_d"] = P[c] - P.groupby("sig")[c].transform("mean")
    b, se = clustered_ols(P["y_d"], P[["OOS_d", "POST_d"]], P["date"].values)
    return dict(n_pred=P.sig.nunique(), n_obs=len(P), b_oos=b[0], se_oos=se[0], b_post=b[1], se_post=se[1])


def main():
    doc = load_doc()
    versions = {"op": "original-paper method (mostly EW, paper's quantiles)",
                "q5_ew": "quintile LS, equal-weighted", "q5_vw": "quintile LS, value-weighted",
                "me_gt_nyse20": "OP method, stocks above NYSE 20th pct size",
                "nyse_only": "OP method, NYSE stocks only"}
    Ws = {v: load_ls(v) for v in versions}
    res = {v: per_predictor(doc, Ws[v], v) for v in versions}

    base = res["op"].join(doc[["Year", "SampleStartYear", "SampleEndYear", "Cat.Data", "Cat.Economic",
                               "mech", "mech_reason", "data_src", "Portfolio Period", "Stock Weight",
                               "Return", "T-Stat", "Predictability in OP", "LongDescription"]])
    for v in ["q5_ew", "q5_vw", "me_gt_nyse20", "nyse_only"]:
        sub = res[v][[f"{p}_{k}" for p in PERIODS for k in ["mean", "t", "sr"]]]
        base = base.join(sub.add_prefix(v + "__"))
    # decay ratios (relative to own in-sample mean)
    for v, pre in [("op", ""), ("q5_ew", "q5_ew__"), ("q5_vw", "q5_vw__"), ("me_gt_nyse20", "me_gt_nyse20__")]:
        for p in ["OOS", "POST", "P2015"]:
            base[f"{v}_{p}_ratio"] = base[f"{pre}{p}_mean"] / base[f"{pre}IS_mean"]
    # small-cap dependence: share of full-sample IS premium that disappears when microcaps dropped / VW
    base["smallcap_share_screen"] = 1 - base["me_gt_nyse20__IS_mean"] / base["IS_mean"]
    base["smallcap_share_vw"] = 1 - base["q5_vw__IS_mean"] / base["q5_ew__IS_mean"]
    base["monthly_rebal"] = (base["Portfolio Period"] == 1).astype(int)
    base.to_csv(OUT / "predictor_decay.csv", float_format="%.4f")

    # ---- McLean-Pontiff pooled decay by version
    mp = {v: mp_regression(doc, Ws[v]) for v in versions}
    for v in versions:
        mp[v + " (IS t>=2)"] = mp_regression(doc, Ws[v], min_is_t=2.0)
        mp[v + " (raw %/mo)"] = mp_regression(doc, Ws[v], scaled=False)
    pd.DataFrame(mp).T.to_csv(OUT / "mp_regression.csv", float_format="%.4f")
    print("\n## McLean-Pontiff pooled decay (fraction of IS mean; month-clustered SE)")
    for v, r in mp.items():
        print(f"{v:28s} n={r['n_pred']:3d}  OOS {r['b_oos']:+.2f} ({r['se_oos']:.2f})  POST {r['b_post']:+.2f} ({r['se_post']:.2f})")
    return base, mp


if __name__ == "__main__":
    main()
