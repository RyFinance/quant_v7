"""Point-in-time panel, eligibility, signals and target books for research/etf_hybrids/PLAN.md.

Everything is indexed by month-end sessions ME(k) of the SPY calendar. A signal at ME(k) uses closes on
or before ME(k) only; `load_panel(upto)` truncates every price input before anything is computed.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "etf_hybrids"

SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC"]
SINGLE_COUNTRY = ["EWA", "EWC", "EWG", "EWH", "EWJ", "EWU", "EWS", "EWL", "EWP", "EWQ", "EWI", "EWD",
                  "EWN", "EWT", "EWY", "EWZ", "EWW"]
BROAD = ["EEM", "EFA", "SPY"]
COUNTRY = SINGLE_COUNTRY + BROAD
UNIVERSE = SECTORS + COUNTRY
HALVES = {"sector": SECTORS, "country": COUNTRY}
COST_PER_SIDE = {**{t: 0.0003 for t in SECTORS + BROAD}, **{t: 0.0008 for t in SINGLE_COUNTRY}}

ELIG_MONTHS = 13          # a close at ME(m-13) is required
VOL_TARGET, VOL_WINDOW = 0.12, 126
HIGH_WINDOW, VOL12_WINDOW = 252, 252
SEAS_YEARS, SEAS_MIN = 10, 5
MIN_NAMES = 3


# -- data -------------------------------------------------------------------------------------------
def load_panel(upto: pd.Timestamp | None = None, names: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """adj_open, adj_close (total return) and close (quoted, split-adjusted) on the SPY calendar,
    truncated at `upto` before anything else is done."""
    names = names or UNIVERSE
    spy = pd.read_parquet(DATA / "SPY.parquet")
    cal = pd.DatetimeIndex(pd.to_datetime(spy["date"])).sort_values()
    if upto is not None:
        cal = cal[cal <= upto]
    out = {"adj_open": {}, "adj_close": {}, "close": {}}
    for t in names:
        d = pd.read_parquet(DATA / f"{t}.parquet")
        d = d.set_index(pd.DatetimeIndex(pd.to_datetime(d["date"]))).sort_index()
        if upto is not None:
            d = d.loc[:upto]
        for f in out:
            out[f][t] = d[f].astype(float)
    return {f: pd.DataFrame(v).reindex(cal) for f, v in out.items()}


def month_ends(cal: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(cal, index=cal)
    return pd.DatetimeIndex(s.groupby([cal.year, cal.month]).max().to_numpy())


# -- eligibility and signals -------------------------------------------------------------------------
def eligibility(adj_close: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    """True at ME(k) if the ETF has a close at ME(k-13)."""
    at_me = adj_close.reindex(me).notna()
    return at_me.shift(ELIG_MONTHS, fill_value=False).astype(bool) & at_me


def momentum_12_1(adj_close: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    p = adj_close.reindex(me)
    return p.shift(1) / p.shift(12) - 1.0


def return_12m(adj_close: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    p = adj_close.reindex(me)
    return p / p.shift(12) - 1.0


def rf_12m(rf: pd.Series, me: pd.DatetimeIndex) -> pd.Series:
    """Compounded daily rf over the sessions in (ME(k-12), ME(k)]."""
    growth = np.log1p(rf).cumsum().reindex(me)
    return np.expm1(growth - growth.shift(12))


def high_52w(close: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    """Quoted close over its max across the 252 sessions ending at ME(k)."""
    hi = close.rolling(HIGH_WINDOW, min_periods=HIGH_WINDOW).max()
    return (close / hi).reindex(me)


def vol_12m(adj_close: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    lr = np.log(adj_close).diff()
    return lr.rolling(VOL12_WINDOW, min_periods=VOL12_WINDOW).std(ddof=1).reindex(me)


def monthly_returns(adj_close: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    p = adj_close.reindex(me)
    return p / p.shift(1) - 1.0


def seasonality(adj_close: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    """At ME(k): mean return of the calendar month k+1 over the previous 10 years (month rows
    k+1-12j, j = 1..10), needing at least 5. The month list is contiguous, so row arithmetic is exact."""
    mr = monthly_returns(adj_close, me)
    lags = [mr.shift(12 * j - 1) for j in range(1, SEAS_YEARS + 1)]   # row k-(12j-1) = k+1-12j
    stack = np.stack([x.to_numpy() for x in lags])
    n = np.sum(~np.isnan(stack), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)   # all-NaN slices before inception
        mean = np.nanmean(stack, axis=0)
    mean[n < SEAS_MIN] = np.nan
    return pd.DataFrame(mean, index=mr.index, columns=mr.columns)


def pct_rank(score: pd.DataFrame) -> pd.DataFrame:
    return score.rank(axis=1, pct=True)


# -- books ------------------------------------------------------------------------------------------
def half_weights(score: pd.Series, eligible: pd.Series, names: list[str], half: float = 0.5) -> pd.Series:
    """Top round(N/3) of the valid scores at equal weight (half / n); fewer than 3 valid -> the
    equal-weight benchmark of the eligible names in this half."""
    w = pd.Series(0.0, index=names)
    elig = eligible.reindex(names).fillna(False).astype(bool)
    valid = score.reindex(names)[elig].dropna()
    if len(valid) < MIN_NAMES:
        e = elig[elig].index
        if len(e):
            w[e] = half / len(e)
        return w
    n = max(1, int(round(len(valid) / 3)))
    order = pd.DataFrame({"s": valid.to_numpy(), "t": valid.index}).sort_values(["s", "t"], ascending=[False, True])
    top = order["t"].iloc[:n].to_list()
    w[top] = half / n
    return w


def benchmark_weights(eligible: pd.Series) -> pd.Series:
    parts = []
    for names in HALVES.values():
        elig = eligible.reindex(names).fillna(False).astype(bool)
        w = pd.Series(0.0, index=names)
        e = elig[elig].index
        if len(e):
            w[e] = 0.5 / len(e)
        parts.append(w)
    return pd.concat(parts)


def tercile_book(score: pd.Series, eligible: pd.Series) -> pd.Series:
    return pd.concat([half_weights(score, eligible, names) for names in HALVES.values()])


def dual_momentum_book(r12: pd.Series, rf12: float, eligible: pd.Series) -> pd.Series:
    w = tercile_book(r12, eligible)
    fail = (r12.reindex(w.index) <= rf12).fillna(False) & (w > 0)
    w[fail] = 0.0          # the slot sits in T-bills
    return w


def e4_score(mom: pd.DataFrame, vol: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """Half the percentile rank of MOM plus half that of -VOL, within each cross-section, among the
    eligible names with both."""
    out = []
    for half in HALVES.values():
        names = [t for t in half if t in mom.columns]
        m = mom[names].where(eligible[names])
        v = vol[names].where(eligible[names])
        both = m.notna() & v.notna()
        m, v = m.where(both), v.where(both)
        out.append(0.5 * pct_rank(m) + 0.5 * pct_rank(-v))
    return pd.concat(out, axis=1)[mom.columns]


def signal_panels(panel: dict[str, pd.DataFrame], rf: pd.Series) -> dict:
    ac, cl = panel["adj_close"], panel["close"]
    me = month_ends(ac.index)
    elig = eligibility(ac, me)
    mom = momentum_12_1(ac, me)
    vol = vol_12m(ac, me)
    return {
        "me": me, "eligible": elig, "mom": mom, "r12": return_12m(ac, me), "rf12": rf_12m(rf.reindex(ac.index), me),
        "high52": high_52w(cl, me), "vol": vol, "e4": e4_score(mom, vol, elig), "seas": seasonality(ac, me),
    }


def target_books(sig: dict, dates: pd.DatetimeIndex) -> dict[str, dict[pd.Timestamp, pd.Series]]:
    """Target weights at each signal date for the unscaled momentum book U (= R0), E2..E5 and B.
    E1 = s_k x U is formed in evaluate.py, because s_k needs U's marked returns."""
    books = {k: {} for k in ("R0", "E2", "E3", "E4", "E5", "B")}
    for d in dates:
        el = sig["eligible"].loc[d]
        books["R0"][d] = tercile_book(sig["mom"].loc[d].where(el), el)
        books["E2"][d] = dual_momentum_book(sig["r12"].loc[d].where(el), float(sig["rf12"].loc[d]), el)
        books["E3"][d] = tercile_book(sig["high52"].loc[d].where(el), el)
        books["E4"][d] = tercile_book(sig["e4"].loc[d].where(el), el)
        books["E5"][d] = tercile_book(sig["seas"].loc[d].where(el), el)
        books["B"][d] = benchmark_weights(el)
    return books
