"""Rebalancing signals of Harvey, Mazzoleni & Melone (NBER w33554), per research/rebalancing/PLAN.md.

All signals at date t use returns through the close of t only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ETF = ROOT / "data" / "multiasset" / "etf"
TARGET = 0.60
DELTAS = np.round(np.arange(0.0, 0.02501, 0.001), 4)  # 0.0% .. 2.5%, 26 values
THRESH_SCALE = 0.015
WEEK4_DAYS = 5
REVERSAL_LAG = 4


def load_returns(upto: pd.Timestamp | None = None) -> pd.DataFrame:
    out = {}
    for t in ("SPY", "IEF"):
        d = pd.read_parquet(ETF / f"{t}.parquet")
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        s = d.set_index("date")["close"].sort_index()
        if upto is not None:
            s = s.loc[:upto]
        out[t] = s
    px = pd.DataFrame(out).dropna()
    return px.pct_change().iloc[1:]


def _drift(w: float, re: float, rb: float) -> float:
    a = w * (1 + re)
    return a / (a + (1 - w) * (1 + rb))


def threshold_signal(re: np.ndarray, rb: np.ndarray, delta: float) -> np.ndarray:
    """Deviation of the drifted equity weight from 60% at each close; reset when |dev| >= delta."""
    n = len(re)
    sig = np.empty(n)
    w = TARGET
    for i in range(n):
        w = _drift(w, re[i], rb[i])
        sig[i] = w - TARGET
        if abs(w - TARGET) >= delta:
            w = TARGET
    return sig


def threshold_avg(ret: pd.DataFrame) -> pd.Series:
    re, rb = ret["SPY"].to_numpy(), ret["IEF"].to_numpy()
    s = np.mean([threshold_signal(re, rb, d) for d in DELTAS], axis=0)
    return pd.Series(s, index=ret.index, name="threshold")


def trading_calendar(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Observed trading days, extended with weekdays to the end of the final (possibly partial) month.
    The exchange calendar is known in advance, so this is not look-ahead."""
    last = dates[-1]
    tail = pd.bdate_range(last + pd.Timedelta(days=1), last + pd.offsets.MonthEnd(0))
    return dates.union(tail)


def month_position(dates: pd.DatetimeIndex) -> pd.DataFrame:
    cal = trading_calendar(dates)
    s = pd.Series(1, index=cal)
    per = cal.to_period("M")
    from_end = s.groupby(per).cumcount(ascending=False)  # 0 = last trading day of month
    from_start = s.groupby(per).cumcount()                # 0 = first trading day
    df = pd.DataFrame({"from_end": from_end.to_numpy(), "from_start": from_start.to_numpy()}, index=cal)
    return df.reindex(dates)


def calendar_signal(ret: pd.DataFrame) -> pd.Series:
    mp = month_position(ret.index)
    re, rb = ret["SPY"].to_numpy(), ret["IEF"].to_numpy()
    last = (mp["from_end"] == 0).to_numpy()
    sig = np.empty(len(re))
    w = TARGET
    for i in range(len(re)):
        w = _drift(w, re[i], rb[i])
        sig[i] = w - TARGET
        if last[i]:
            w = TARGET
    return pd.Series(sig, index=ret.index, name="calendar")


def calendar_position(ret: pd.DataFrame, cal: pd.Series | None = None) -> pd.Series:
    if cal is None:
        cal = calendar_signal(ret)
    mp = month_position(ret.index)
    week4 = mp["from_end"] < WEEK4_DAYS
    first = mp["from_start"] == 0
    pos = pd.Series(0.0, index=ret.index)
    pos[week4] = np.sign(-cal[week4])
    lagged = cal.shift(REVERSAL_LAG)
    pos[first] = np.sign(lagged[first]).fillna(0.0)
    return pos.rename("R1_calendar")


def positions(ret: pd.DataFrame) -> pd.DataFrame:
    thr = threshold_avg(ret)
    cal = calendar_signal(ret)
    r1 = calendar_position(ret, cal)
    r2 = (-thr / THRESH_SCALE).rename("R2_threshold")
    r3 = (0.5 * r1 + 0.5 * r2).rename("R3_combined")
    return pd.concat([r1, r2, r3, thr, cal], axis=1)
