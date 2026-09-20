"""Summary tables and the cross-sectional survival model from reports/edge_graveyard/predictor_decay.csv."""
import numpy as np
import pandas as pd
from pathlib import Path
from research.edge_graveyard.survival_study import hc_ols

OUT = Path(__file__).resolve().parents[2] / "reports/edge_graveyard"
b = pd.read_csv(OUT / "predictor_decay.csv", index_col=0)
CLIP = (-1.5, 2.5)
for v in ["op", "q5_ew", "q5_vw", "me_gt_nyse20"]:
    for p in ["OOS", "POST", "P2015"]:
        b[f"{v}_{p}_ratio_c"] = b[f"{v}_{p}_ratio"].clip(*CLIP)
b["alive_2015"] = (b["P2015_t"] >= 1.5).astype(int)       # still visibly positive 2015-2024
b["alive_2015_big"] = (b["me_gt_nyse20__P2015_t"] >= 1.5).astype(int)
b["sc_terc"] = pd.qcut(b["smallcap_share_screen"].clip(-1, 2), 3, labels=["low (big-cap ok)", "mid", "high (microcap)"])
b["skew_terc"] = pd.qcut(b["IS_skew"], 3, labels=["neg skew", "mid", "pos skew"])
b["pub_era"] = pd.cut(b["Year"], [0, 1995, 2005, 2010, 2020], labels=["<=1995", "1996-2005", "2006-2010", "2011-2016"])
out = []


def P(s=""):
    out.append(s); print(s)


def md(df, fmt="{:.2f}"):
    df = df.copy()
    cols = list(df.columns)
    P("| " + " | ".join([df.index.name or ""] + cols) + " |")
    P("|" + "---|" * (len(cols) + 1))
    for i, r in df.iterrows():
        P("| " + " | ".join([str(i)] + [(fmt.format(x) if isinstance(x, (float, np.floating)) and np.isfinite(x) else str(x)) for x in r]) + " |")
    P()


# 1. period table
P("### Table 1. Average predictor, by period (original-paper method, % per month; Sharpe annualised)")
t1 = pd.DataFrame({p: {"mean %/mo": b[f"{p}_mean"].mean(), "median %/mo": b[f"{p}_mean"].median(),
                       "mean t": b[f"{p}_t"].mean(), "mean Sharpe": b[f"{p}_sr"].mean(),
                       "median Sharpe": b[f"{p}_sr"].median(), "share t>=2": (b[f"{p}_t"] >= 2).mean(),
                       "avg months": b[f"{p}_n"].mean(), "N": b[f"{p}_mean"].notna().sum()} for p in ["IS", "OOS", "POST", "P2015"]})
t1.index.name = "stat"; md(t1)

P("### Table 2. Same, by portfolio construction (mean Sharpe; median ratio of period mean to own IS mean)")
rows = {}
for v, pre, lab in [("op", "", "original paper (mostly EW)"), ("q5_ew", "q5_ew__", "quintile EW"),
                    ("q5_vw", "q5_vw__", "quintile VW"), ("me_gt_nyse20", "me_gt_nyse20__", "ex-microcap (ME>NYSE p20)"),
                    ("nyse_only", "nyse_only__", "NYSE only")]:
    r = {f"SR {p}": b[f"{pre}{p}_sr"].mean() for p in ["IS", "OOS", "POST", "P2015"]}
    if v != "nyse_only":
        r.update({f"ratio {p}": b[f"{v}_{p}_ratio_c"].median() for p in ["OOS", "POST", "P2015"]})
    r["N"] = b[f"{pre}IS_sr"].notna().sum()
    rows[lab] = r
t2 = pd.DataFrame(rows).T; t2.index.name = "version"; md(t2)


def grp(col, label):
    g = b.groupby(col, observed=True)
    t = pd.DataFrame({
        "N": g.size(),
        "IS Sharpe": g["IS_sr"].mean(),
        "POST Sharpe": g["POST_sr"].mean(),
        "2015+ Sharpe": g["P2015_sr"].mean(),
        "POST/IS (median)": g["op_POST_ratio_c"].median(),
        "2015+/IS (median)": g["op_P2015_ratio_c"].median(),
        "alive 2015+ (t>=1.5)": g["alive_2015"].mean(),
        "2015+ Sharpe ex-micro": g["me_gt_nyse20__P2015_sr"].mean(),
        "2015+ Sharpe VW": g["q5_vw__P2015_sr"].mean(),
        "smallcap share": g["smallcap_share_screen"].median(),
    })
    t.index.name = label
    return t


P("### Table 3. Survival by mechanism"); md(grp("mech", "mechanism"))
P("### Table 4. Survival by data source"); md(grp("data_src", "data source"))
P("### Table 5. Survival by small-cap dependence (tercile of IS premium lost when microcaps removed)"); md(grp("sc_terc", "small-cap tercile"))
P("### Table 6. Survival by rebalance frequency (portfolio holding period, months)"); md(grp("Portfolio Period", "holding months"))
P("### Table 7. Survival by in-sample skewness"); md(grp("skew_terc", "IS skew tercile"))
P("### Table 8. Survival by publication era"); md(grp("pub_era", "published"))
P("### Table 9. Survival by Chen-Zimmermann economic category (N>=6)")
t9 = grp("Cat.Economic", "category"); md(t9[t9.N >= 6].sort_values("2015+ Sharpe", ascending=False))

# cross-sectional survival model
P("### Table 10. Survival model: cross-sectional OLS, HC1 SE")
X = pd.DataFrame(index=b.index)
for m in ["M1", "M2", "M3", "M4", "M5"]:
    X[m] = (b.mech == m).astype(float)          # base = M6 risk premia
for dsrc in ["price", "volume", "analyst", "options", "flows_holdings", "event", "alt_other"]:
    X["d_" + dsrc] = (b.data_src == dsrc).astype(float)  # base = accounting
X["log IS t"] = np.log(b["IS_t"].clip(lower=0.5))
X["smallcap share"] = b["smallcap_share_screen"].clip(-1, 2)
X["monthly rebal"] = b["monthly_rebal"]
X["IS skew"] = b["IS_skew"].clip(-3, 3)
X["pub year-2000"] = (b["Year"] - 2000) / 10
X["const"] = 1.0
res = {}
for y in ["op_POST_ratio_c", "op_P2015_ratio_c", "P2015_sr", "me_gt_nyse20__P2015_sr"]:
    ok = X.notna().all(1) & b[y].notna()
    coef, se = hc_ols(b.loc[ok, y], X[ok])
    yy = b.loc[ok, y].values; e = yy - X[ok].values @ coef
    r2 = 1 - (e**2).sum() / ((yy - yy.mean())**2).sum()
    res[f"{y} (N={ok.sum()})"] = [f"{c:+.2f} ({s:.2f}){'*' if abs(c/s)>=1.96 else ''}" for c, s in zip(coef, se)] + [f"{r2:.2f}"]
t10 = pd.DataFrame(res, index=list(X.columns) + ["R2"]); t10.index.name = "regressor"
md(t10, fmt="{}")
P("Base category: M6 risk premia, accounting data. * = |t|>=1.96. smallcap share = 1 - IS mean(ex-microcap)/IS mean(all). pub year scaled per decade.")
P()

# survivors
P("### Table 11. Strongest 2015-2024 survivors (original method t>=2 in 2015+), with ex-microcap and VW versions")
s = b[b["P2015_t"] >= 2].sort_values("P2015_sr", ascending=False)
t11 = s[["mech", "data_src", "Year", "IS_sr", "POST_sr", "P2015_sr", "me_gt_nyse20__P2015_sr", "q5_vw__P2015_sr", "smallcap_share_screen", "LongDescription"]]
t11.columns = ["mech", "data", "pub", "IS SR", "POST SR", "2015+ SR", "2015+ SR ex-micro", "2015+ SR VW", "smallcap share", "description"]
t11.index.name = "signal"; md(t11)
P("### Table 12. Survivors in big stocks: ex-microcap 2015+ t>=2")
s = b[b["me_gt_nyse20__P2015_t"] >= 2].sort_values("me_gt_nyse20__P2015_sr", ascending=False)
t12 = s[["mech", "data_src", "Year", "me_gt_nyse20__IS_sr", "me_gt_nyse20__P2015_sr", "q5_vw__P2015_sr", "P2015_sr", "LongDescription"]]
t12.columns = ["mech", "data", "pub", "ex-micro IS SR", "ex-micro 2015+ SR", "VW 2015+ SR", "all 2015+ SR", "description"]
t12.index.name = "signal"; md(t12)
(OUT / "tables.md").write_text("\n".join(out))
b.to_csv(OUT / "predictor_decay.csv", float_format="%.4f")
