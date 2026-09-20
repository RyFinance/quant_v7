"""Point-in-time fundamentals signals for the registered F1/F2/F3 test (research/fundamentals/PLAN.md).

F1 net share issuance (Pontiff & Woodgate 2008; OSAP ShareIss1Y): log growth of split-consistent basic
   weighted-average shares from the latest quarter ending <= t-6 months to the quarter ending about
   12 months before it. Low issuance (buybacks) predicts high returns, so score = -F1.
F2 earnings consistency (Alwathainani 2009; OSAP EarningsConsistency): mean of the last five annual
   EPS growth rates g_k = (e_k - e_{k-1}) / (0.5 (|e_{k-1}| + |e_{k-2}|)); missing if |g_last| > 6 or
   g_last and g_prev have opposite signs. High = long.

Point in time: a filing is usable from the first trading day strictly after its SEC acceptance date.
Rows whose acceptance date is on or before the fiscal period end (vault placeholder timestamps) are
treated as available at period end + 45 days (Q1-Q3) or + 90 days (FY, Q4).
Split basis: the vault restates share counts and EPS to the current split basis (checked in the PLAN
coverage section); a residual guard divides a share ratio by any split in the interval whose ratio
it matches (|log obs / log split - 1| < 0.25, |log split| >= log 1.25).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FIN_DIR = ROOT / "data" / "lse" / "financial_reports"
SPLIT_DIR = ROOT / "data" / "lse" / "stock_splits"
STOCK_DIR = ROOT / "data" / "multiasset" / "stocks"

SKIP_MONTHS = 6
MATCH_TOL_DAYS = 45
PLACEHOLDER_LAG = {"Q1": 45, "Q2": 45, "Q3": 45, "Q4": 90, "FY": 90}
MAX_ABS_GROWTH = 6.0
N_GROWTH = 5


def availability(accepted: pd.Series, period_end: pd.Series, period: pd.Series,
                 calendar: pd.DatetimeIndex) -> pd.Series:
    """First trading day strictly after the acceptance date (placeholder rows: after the fallback date)."""
    acc_day = pd.to_datetime(accepted).dt.normalize()
    pe = pd.to_datetime(period_end)
    fallback = pe + pd.to_timedelta(period.map(PLACEHOLDER_LAG).fillna(90), unit="D")
    base = acc_day.where(acc_day > pe, fallback)
    idx = calendar.searchsorted(base.to_numpy(), side="right")
    out = pd.Series(pd.NaT, index=accepted.index, dtype="datetime64[ns]")
    ok = idx < len(calendar)
    out[ok] = calendar[idx[ok]]
    return out


def load_reports(ticker: str, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    d = pd.read_parquet(FIN_DIR / f"{ticker}.parquet")
    d = d[d["report_type"] == "income"].copy()
    d["pe"] = pd.to_datetime(d["date"])
    d["avail"] = availability(d["accepted_date"], d["pe"], d["period"], calendar)
    shs = d["weightedAverageShsOut"].astype(float)
    shs = shs.where(shs > 0, d["weightedAverageShsOutDil"].astype(float))
    d["shs"] = shs.where(shs > 0)
    return d.sort_values("pe").reset_index(drop=True)


def load_splits(ticker: str) -> pd.DataFrame:
    p = SPLIT_DIR / f"{ticker}.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["eff", "ratio"])
    s = pd.read_parquet(p)
    return pd.DataFrame({"eff": pd.to_datetime(s["effective_date"]),
                         "ratio": s["split_to"].astype(float) / s["split_from"].astype(float)})


def split_guard(obs_ratio: float, start: pd.Timestamp, end: pd.Timestamp, splits: pd.DataFrame) -> float:
    """Undo a split that is still visible in a share ratio (raw, not restated, counts)."""
    r = obs_ratio
    for _, s in splits[(splits["eff"] > start) & (splits["eff"] <= end)].iterrows():
        ls = np.log(s["ratio"])
        if abs(ls) >= np.log(1.25) and r > 0 and abs(np.log(r) / ls - 1.0) < 0.25:
            r = r / s["ratio"]
    return r


def issuance_at(q: pd.DataFrame, t: pd.Timestamp, splits: pd.DataFrame) -> float:
    """q: quarterly rows (pe, avail, shs). Returns F1 = log share growth, NaN if unavailable."""
    known = q[(q["avail"] <= t) & q["shs"].notna()]
    recent = known[known["pe"] <= t - pd.DateOffset(months=SKIP_MONTHS)]
    if recent.empty:
        return np.nan
    r1 = recent.iloc[-1]
    target = r1["pe"] - pd.DateOffset(months=12)
    gap = (known["pe"] - target).abs()
    cand = known[gap <= pd.Timedelta(days=MATCH_TOL_DAYS)]
    if cand.empty:
        return np.nan
    r0 = cand.loc[gap[cand.index].idxmin()]
    ratio = split_guard(r1["shs"] / r0["shs"], r0["pe"], r1["pe"], splits)
    return float(np.log(ratio)) if ratio > 0 else np.nan


def consistency_at(fy: pd.DataFrame, t: pd.Timestamp) -> float:
    """fy: annual rows (pe, avail, eps). Needs N_GROWTH + 2 consecutive fiscal years known at t."""
    known = fy[(fy["avail"] <= t) & fy["eps"].notna()]
    need = N_GROWTH + 2
    if len(known) < need:
        return np.nan
    k = known.iloc[-need:]
    gaps = k["pe"].diff().dt.days.iloc[1:]
    if not gaps.between(300, 430).all():
        return np.nan
    e = k["eps"].to_numpy(dtype=float)
    g = []
    for i in range(2, need):
        den = 0.5 * (abs(e[i - 1]) + abs(e[i - 2]))
        if den <= 0:
            return np.nan
        g.append((e[i] - e[i - 1]) / den)
    g = np.array(g)
    if abs(g[-1]) > MAX_ABS_GROWTH or np.sign(g[-1]) * np.sign(g[-2]) < 0:
        return np.nan
    return float(g.mean())


def ticker_signals(ticker: str, dates: pd.DatetimeIndex, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    d = load_reports(ticker, calendar)
    sp = load_splits(ticker)
    q = d[d["period"].isin(["Q1", "Q2", "Q3", "Q4"])]
    fy = d[d["period"] == "FY"]
    rows = [(issuance_at(q, t, sp), consistency_at(fy, t)) for t in dates]
    return pd.DataFrame(rows, index=dates, columns=["f1", "f2"])


def trading_calendar() -> pd.DatetimeIndex:
    spy = pd.read_parquet(ROOT / "data" / "multiasset" / "etf" / "SPY.parquet")
    col = spy["date"] if "date" in spy.columns else spy.index.to_series()
    return pd.DatetimeIndex(pd.to_datetime(col).to_numpy()).sort_values()


def month_end_dates(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(calendar, index=calendar)
    return pd.DatetimeIndex(s.groupby([calendar.year, calendar.month]).max().to_numpy())
