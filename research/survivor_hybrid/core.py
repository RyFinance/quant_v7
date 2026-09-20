"""Survivor hybrids of Chen-Zimmermann (OSAP) predictors. Rules: research/survivor_hybrid/PLAN.md.

Selection uses only OSAP returns through 2014-12: every series is truncated at CUTOFF before any
statistic is computed. Hybrid weights for month t use returns from months strictly before t (and
whether a component portfolio exists in month t, which is known when it is formed). OSAP files
hold % per month; everything here is in decimals per month.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research.edge_graveyard.tags import tag

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data/osap"

CUTOFF = pd.Timestamp("2014-12-31")      # last month selection may see
OOS_START = pd.Timestamp("2015-01-31")   # first evaluated month
MAX_PUB_YEAR = 2009                      # published before 2010
T_OP_MIN = 2.0                           # op post-sample t-stat
T_LC_MIN = 1.0                           # ex-microcap post-sample t-stat
MIN_MONTHS = 36                          # minimum months in each selection window
VOL_WINDOW, VOL_MIN_OBS = 36, 24         # trailing volatility for H2 / H4
HAIRCUT_R = {"low": 20.0, "base": 30.0, "high": 40.0}  # bps/month, monthly-rebalanced component
LC_PRIMARY, LC_FALLBACK = "q5_vw", "me_gt_nyse20"


def load_doc() -> pd.DataFrame:
    doc = pd.read_csv(D / "SignalDoc.csv")
    doc = doc[doc["Cat.Signal"] == "Predictor"].copy()
    return tag(doc).set_index("Acronym")


def load_ls(version: str, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Wide monthly long-short returns (decimal), index = calendar month end."""
    x = pd.read_parquet(D / f"ls_{version}.parquet", columns=["signalname", "date", "ret"])
    x["date"] = pd.to_datetime(x["date"]) + pd.offsets.MonthEnd(0)
    w = x.pivot_table(index="date", columns="signalname", values="ret", aggfunc="last") / 100.0
    w = w.sort_index()
    return w.loc[:end] if end is not None else w


def tstat(x: pd.Series) -> tuple[float, int]:
    x = x.dropna()
    n = len(x)
    if n < 2 or x.std() == 0:
        return float("nan"), n
    return float(x.mean() / x.std() * np.sqrt(n)), n


def select_survivors(doc: pd.DataFrame, w_op: pd.DataFrame, w_lc: pd.DataFrame,
                     w_vw: pd.DataFrame | None = None) -> pd.DataFrame:
    """Apply the fixed selection rule. Inputs are truncated at CUTOFF here, whatever is passed in."""
    w_op, w_lc = w_op.loc[:CUTOFF], w_lc.loc[:CUTOFF]
    w_vw = None if w_vw is None else w_vw.loc[:CUTOFF]
    rows = []
    for sig, r in doc.iterrows():
        rec = {"signal": sig, "Year": r["Year"], "SampleEndYear": r["SampleEndYear"], "mech": r["mech"],
               "data_src": r["data_src"], "cat_econ": r["Cat.Economic"], "pp": r["Portfolio Period"],
               "stock_weight": r["Stock Weight"], "desc": r["LongDescription"]}
        x = w_op[sig] if sig in w_op else pd.Series(dtype=float)
        yx = x.index.year
        rec["t_ps"], rec["n_ps"] = tstat(x[yx > r["SampleEndYear"]])
        post = x[yx > r["Year"]].dropna()
        rec["mean_pub"], rec["n_pub"] = (float(post.mean()) if len(post) else float("nan")), len(post)
        z = w_lc[sig] if sig in w_lc else pd.Series(dtype=float)
        rec["t_ps_lc"], rec["n_ps_lc"] = tstat(z[z.index.year > r["SampleEndYear"]])
        rec["has_vw"] = bool(w_vw is not None and sig in w_vw and w_vw[sig].notna().sum() >= MIN_MONTHS)
        rec["c1_pub"] = bool(r["Year"] <= MAX_PUB_YEAR)
        rec["c2_op_ps"] = bool(rec["n_ps"] >= MIN_MONTHS and rec["t_ps"] >= T_OP_MIN)
        rec["c3_pub_pos"] = bool(rec["n_pub"] >= MIN_MONTHS and rec["mean_pub"] > 0)
        rec["c4_lc_ps"] = bool(rec["n_ps_lc"] >= MIN_MONTHS and rec["t_ps_lc"] >= T_LC_MIN)
        rec["selected"] = rec["c1_pub"] and rec["c2_op_ps"] and rec["c3_pub_pos"] and rec["c4_lc_ps"]
        rows.append(rec)
    out = pd.DataFrame(rows).set_index("signal")
    out["lc_version"] = np.where(out["has_vw"], LC_PRIMARY, LC_FALLBACK)
    return out


def haircut_multiplier(pp: float) -> float:
    """Share of the monthly-rebalance haircut charged to a component held pp months."""
    if pd.isna(pp) or pp <= 1:
        return 1.0
    if pp <= 3:
        return 0.5
    return 1.0 / 3.0


def component_haircut(pp: pd.Series, r_bps: float) -> pd.Series:
    """Haircut per component in decimal per month."""
    return pp.map(haircut_multiplier) * r_bps / 1e4


# -- weights (rows = months, columns = components; each row sums to 1 over available components) --
def trailing_vol(r: pd.DataFrame, window: int = VOL_WINDOW, min_obs: int = VOL_MIN_OBS) -> pd.DataFrame:
    """Volatility known at the start of month t: months t-window .. t-1 only."""
    r = r.asfreq("ME") if isinstance(r.index, pd.DatetimeIndex) else r
    return r.rolling(window, min_periods=min_obs).std().shift(1)


def _normalise(w: pd.DataFrame) -> pd.DataFrame:
    s = w.sum(axis=1)
    return w.div(s.where(s > 0), axis=0)


def weights_equal(r: pd.DataFrame) -> pd.DataFrame:
    return _normalise(r.notna().astype(float))


def weights_inv_vol(r: pd.DataFrame, window: int = VOL_WINDOW, min_obs: int = VOL_MIN_OBS) -> pd.DataFrame:
    sig = trailing_vol(r, window, min_obs).reindex(r.index)
    inv = (1.0 / sig).where(r.notna() & (sig > 0))
    return _normalise(inv.fillna(0.0))


def group_returns(r: pd.DataFrame, groups: dict[str, list[str]]) -> pd.DataFrame:
    return pd.DataFrame({g: r[c].mean(axis=1, skipna=True) for g, c in groups.items()})


def weights_group_risk(r: pd.DataFrame, groups: dict[str, list[str]], window: int = VOL_WINDOW,
                       min_obs: int = VOL_MIN_OBS) -> pd.DataFrame:
    """Equal weight within a mechanism group; inverse trailing volatility across groups."""
    wg = weights_inv_vol(group_returns(r, groups), window, min_obs)
    w = pd.DataFrame(0.0, index=r.index, columns=r.columns)
    for g, cols in groups.items():
        within = weights_equal(r[cols]).fillna(0.0)
        w[cols] = within.mul(wg[g].fillna(0.0), axis=0)
    return _normalise(w)


def combine(r: pd.DataFrame, w: pd.DataFrame, cost: pd.Series) -> pd.DataFrame:
    """Gross and net hybrid returns; months with no available component are NaN."""
    w = w.reindex(index=r.index, columns=r.columns).fillna(0.0)
    has = w.sum(axis=1) > 0
    gross = (w * r.fillna(0.0)).sum(axis=1)
    hc = (w * cost.reindex(r.columns).fillna(0.0)).sum(axis=1)
    out = pd.DataFrame({"gross": gross, "haircut": hc, "net": gross - hc,
                        "n_comp": (w > 0).sum(axis=1)})
    return out.where(has)
