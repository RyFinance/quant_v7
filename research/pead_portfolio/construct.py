"""PEAD portfolio constructions B1-B5 (rules fixed in research/pead_portfolio/PLAN.md).

Everything here is a pure function of daily excess-return series. It has two parts:
- decision rules: `beta_at`, `b2_weight_at` and `rp_weights`. Each sees only the rows up to and
  including the decision date, so no look-ahead is possible by construction;
- `simulate`: a daily engine. Targets decided at month-end t are traded at the close of t+1 and earn
  from t+2. Positions drift between rebalances. It charges costs, roll and financing.

Component names: 'P' is the PEAD book, 'H' the market hedge (SPY excess return, an ES proxy), and
the sleeves use their own names.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

MIN_OBS = 63        # PEAD observations needed before any estimate
RP_WIN = 252        # risk-parity / vol estimation window
BETA_WIN = 126      # hedge-beta window
VOL_WIN = 21        # B2 trailing vol
LAG = 2             # decided at close t, traded at close t+1, earns from t+2
BETA_CLAMP = (0.0, 1.5)
B2_CAP = 2.0
CAP_P = 1.5
CAP_SLEEVE = 4.0
SLEEVES_B4 = ("fx_carry", "bond_carry", "tsmom_broad")


@dataclass(frozen=True)
class Costs:
    stock_side: float = 0.0005   # per side on |dw_P| * G
    hedge_side: float = 0.0001   # per side on |dh|
    roll: float = 0.0002         # quarterly ES roll, on |h|
    sleeve_unit: float = 0.0010  # per unit |dw_k| (2 bps/side x assumed 5x gross)
    fin_spread: float = 0.015    # per year above RF on max(0, w_P*G - 1)

    def stressed(self) -> "Costs":
        return replace(self, stock_side=3 * self.stock_side, hedge_side=3 * self.hedge_side,
                       roll=3 * self.roll, sleeve_unit=3 * self.sleeve_unit, fin_spread=2 * self.fin_spread)


# ---------------------------------------------------------------- calendar helpers

def month_end_positions(index: pd.DatetimeIndex) -> np.ndarray:
    """Positions of the last trading day of each calendar month in `index`."""
    per = index.to_period("M")
    last = np.r_[per[1:] != per[:-1], True]
    return np.flatnonzero(last)


def decision_positions(index: pd.DatetimeIndex, min_obs: int = MIN_OBS, lag: int = LAG) -> np.ndarray:
    """Month-end decision positions with at least `min_obs` PEAD observations (positions 0..t) whose
    effective day t+lag still lies inside the window."""
    pos = month_end_positions(index)
    return pos[(pos + 1 >= min_obs) & (pos + lag < len(index))]


def roll_days(index: pd.DatetimeIndex) -> np.ndarray:
    """First trading day on or after the 10th of March, June, September and December."""
    flags = np.zeros(len(index), dtype=bool)
    s = pd.Series(np.arange(len(index)), index=index)
    for (y, m), grp in s.groupby([index.year, index.month]):
        if m in (3, 6, 9, 12):
            after = grp[grp.index.day >= 10]
            if len(after):
                flags[after.iloc[0]] = True
    return flags


# ---------------------------------------------------------------- decision rules (past data only)

def beta_at(rp: np.ndarray, rm: np.ndarray, win: int = BETA_WIN, clamp=BETA_CLAMP) -> float:
    """OLS slope of rp on rm over the last min(win, len) observations; clamped."""
    k = min(win, len(rp))
    y, x = np.asarray(rp[-k:], float), np.asarray(rm[-k:], float)
    xc = x - x.mean()
    b = float((xc * (y - y.mean())).sum() / (xc * xc).sum())
    return float(np.clip(b, *clamp))


def b2_weight_at(rp: np.ndarray, win: int = VOL_WIN, cap: float = B2_CAP) -> float:
    """min(cap, expanding-mean(trailing-21d vol) / current trailing-21d vol), from rp[0..t]."""
    s = pd.Series(np.asarray(rp, float)).rolling(win).std(ddof=1).dropna()
    cur = float(s.iloc[-1])
    return float(min(cap, s.mean() / cur)) if cur > 0 else cap


def rp_weights(hist: pd.DataFrame, pead_col: str, win: int = RP_WIN, min_obs: int = MIN_OBS,
               cap_p: float = CAP_P, cap_sleeve: float = CAP_SLEEVE) -> dict[str, float]:
    """Rule RP: inverse-vol weights over participating components, scaled so the ex-ante combined vol
    equals the PEAD component's own trailing vol. `hist` holds rows 0..t only."""
    W = hist.iloc[-min(win, len(hist)):]
    cols = [c for c in W.columns if W[c].notna().sum() >= min_obs]
    if pead_col not in cols:
        raise ValueError("PEAD component lacks history")
    sig = W[cols].std(ddof=1)
    u = (1.0 / sig).to_numpy()
    S = W[cols].cov().to_numpy()  # pairwise complete
    ev, V = np.linalg.eigh(S)
    S = (V * np.clip(ev, 0, None)) @ V.T
    lam = float(sig[pead_col]) / float(np.sqrt(u @ S @ u))
    w = dict(zip(cols, lam * u))
    out = {c: 0.0 for c in hist.columns}
    for c, v in w.items():
        out[c] = float(min(v, cap_p if c == pead_col else cap_sleeve))
    return out


# ---------------------------------------------------------------- construction targets

def targets_b1(data: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for t in decision_positions(data.index):
        h = data.iloc[: t + 1]
        b = beta_at(h["P"].to_numpy(), h["M"].to_numpy())
        rows[data.index[t]] = {"P": 1.0, "H": -b}
    return pd.DataFrame.from_dict(rows, orient="index")


def targets_b2(data: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for t in decision_positions(data.index):
        rows[data.index[t]] = {"P": b2_weight_at(data["P"].to_numpy()[: t + 1])}
    return pd.DataFrame.from_dict(rows, orient="index")


def targets_rp(data: pd.DataFrame, sleeves: tuple[str, ...], hedged: bool) -> pd.DataFrame:
    rows = {}
    for t in decision_positions(data.index):
        h = data.iloc[: t + 1]
        b = beta_at(h["P"].to_numpy(), h["M"].to_numpy()) if hedged else 0.0
        comp = pd.DataFrame({"P": h["P"] - b * h["M"]}, index=h.index)
        for s in sleeves:
            comp[s] = h[s]
        w = rp_weights(comp, "P")
        if hedged:
            w["H"] = -w["P"] * b
        rows[data.index[t]] = w
    return pd.DataFrame.from_dict(rows, orient="index")


def all_targets(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "B1_beta_hedged": targets_b1(data),
        "B2_vol_managed": targets_b2(data),
        "B3_pead_tsmom": targets_rp(data, ("tsmom_broad",), hedged=False),
        "B4_pead_3sleeves": targets_rp(data, SLEEVES_B4, hedged=False),
        "B5_hedged_3sleeves": targets_rp(data, SLEEVES_B4, hedged=True),
    }


# ---------------------------------------------------------------- engine

def simulate(returns: pd.DataFrame, targets: pd.DataFrame, gross: pd.Series, costs: Costs = Costs(),
             lag: int = LAG, initial: dict[str, float] | None = None) -> pd.DataFrame:
    """Daily excess return of a construction.

    returns: component excess returns ('P', 'H' for the hedge, sleeves). NaN allowed where weight is 0.
    targets: target weights indexed by decision date (a subset of returns.index).
    gross:   PEAD book gross exposure / NAV carried into each day.
    """
    comps = list(targets.columns.union(["P"]))
    R = returns.reindex(columns=comps).to_numpy(float)
    G = gross.reindex(returns.index).to_numpy(float)
    n = len(returns)
    pos = returns.index.get_indexer(targets.index)
    if (pos < 0).any():
        raise ValueError("decision date outside the calendar")
    eff = {int(p) + lag: targets.iloc[j].reindex(comps).fillna(0.0).to_numpy(float) for j, p in enumerate(pos)
           if p + lag < n}
    rolls = roll_days(returns.index)
    iP = comps.index("P")
    iH = comps.index("H") if "H" in comps else None
    kinds = np.array(["stock" if c == "P" else "hedge" if c == "H" else "sleeve" for c in comps])
    unit = np.where(kinds == "stock", costs.stock_side, np.where(kinds == "hedge", costs.hedge_side, costs.sleeve_unit))

    w = np.zeros(len(comps))
    for c, v in (initial or {"P": 1.0}).items():
        w[comps.index(c)] = v
    out_ret, out_cost, out_fin, out_turn = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    W = np.zeros((n, len(comps)))
    for i in range(n):
        cost = 0.0
        if i in eff:
            new = eff[i]
            dw = np.abs(new - w)
            mult = np.where(kinds == "stock", G[i], 1.0)
            cost += float((unit * dw * mult).sum())
            out_turn[i] = float(dw.sum())
            w = new.copy()
        if rolls[i] and iH is not None:
            cost += costs.roll * abs(w[iH])
        fin = costs.fin_spread / 252.0 * max(0.0, w[iP] * G[i] - 1.0)
        r = R[i]
        active = w != 0
        if np.isnan(r[active]).any():
            raise ValueError(f"missing return for an active component on {returns.index[i].date()}")
        rr = np.where(active, r, 0.0)
        gross_ret = float((w * rr).sum())
        ret = gross_ret - cost - fin
        W[i] = w
        out_ret[i], out_cost[i], out_fin[i] = ret, cost, fin
        w = w * (1.0 + rr) / (1.0 + ret)
    df = pd.DataFrame({"ret": out_ret, "cost": out_cost, "fin": out_fin, "turnover": out_turn}, index=returns.index)
    for j, c in enumerate(comps):
        df[f"w_{c}"] = W[:, j]
    return df


def first_effective_date(index: pd.DatetimeIndex) -> pd.Timestamp:
    return index[decision_positions(index)[0] + LAG]
