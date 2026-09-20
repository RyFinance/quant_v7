"""30-day ATM implied volatility per name and day, as registered in research/iv_changes/PLAN.md.

Reuses research/options_signals/signals.py (filters, split rule, IV solver, dividends with amendment 3,
and the wrong-underlying check of amendments 4-5). `upto` truncates every input before computing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.options_signals import signals as sg

DTE_MIN, DTE_MAX, TARGET = 7, 90, 30
MAX_LOG_MONEYNESS = 0.05
DIV_HORIZON_DAYS = 100
WINDOW, MIN_DAYS = 5, 3


def interp_30d(iv1, t1, iv2, t2, target=TARGET / 365.0):
    """Linear interpolation of total variance in T to `target` (T1 <= target < T2)."""
    iv1, t1, iv2, t2 = (np.asarray(x, dtype=float) for x in (iv1, t1, iv2, t2))
    w = (iv1 ** 2 * t1 * (t2 - target) + iv2 ** 2 * t2 * (target - t1)) / ((t2 - t1) * target)
    return np.sqrt(np.where(w > 0, w, np.nan))


def atm_by_expiry(opt: pd.DataFrame) -> pd.DataFrame:
    """Nearest-strike contract per (date, type, expiry); ties go to the lower strike."""
    o = opt.assign(dist=(opt["strike"] - opt["S"]).abs())
    o = o.sort_values(["date", "is_call", "expiry", "dist", "strike"])
    return o.groupby(["date", "is_call", "expiry"], sort=False).head(1).reset_index(drop=True)


def bracket_30d(atm: pd.DataFrame) -> pd.DataFrame:
    """Per (date, is_call): E1 = longest DTE <= 30 with IV, E2 = shortest DTE > 30 with IV; interpolate."""
    a = atm[atm["iv"].notna()]
    near = a[a["dte"] <= TARGET].sort_values("dte").groupby(["date", "is_call"]).last()
    far = a[a["dte"] > TARGET].sort_values("dte").groupby(["date", "is_call"]).first()
    both = near[["iv", "dte"]].join(far[["iv", "dte"]], lsuffix="1", rsuffix="2", how="inner")
    both["iv30"] = interp_30d(both["iv1"], both["dte1"] / 365.0, both["iv2"], both["dte2"] / 365.0)
    return both.reset_index()


def daily_atm_iv(t: str, upto: pd.Timestamp | None = None, rates: pd.Series | None = None) -> pd.DataFrame:
    """Columns call_iv30, put_iv30 on the name's trading calendar (raw spot dates)."""
    spot = sg.load_spot(t, upto)
    cal = spot.index
    out = pd.DataFrame(index=cal, columns=["call_iv30", "put_iv30"], dtype=float)
    opt = sg.drop_split_adjusted(sg.load_options(t, upto), sg.split_dates(spot))
    if rates is None:
        rates = sg.rate_series(cal)
    opt = opt.join(spot["raw_close"].rename("S"), on="date")
    opt = opt[opt["S"].notna()]
    opt["dte"] = (opt["expiry"] - opt["date"]).dt.days
    divs = sg.load_dividends(t, upto, horizon_days=DIV_HORIZON_DAYS)
    flagged = sg.wrong_underlying_days(opt, rates, divs)
    need = opt[(opt["dte"] >= DTE_MIN) & (opt["dte"] <= DTE_MAX)
               & (np.abs(np.log(opt["strike"] / opt["S"])) <= MAX_LOG_MONEYNESS)
               & ~opt["date"].isin(flagged)].copy()
    del opt
    if need.empty:
        return out
    need["is_call"] = need["opt_type"].str.upper().str.startswith("C")
    atm = atm_by_expiry(need)
    atm["r"] = rates.reindex(atm["date"]).fillna(0.0).to_numpy()
    atm["T"] = atm["dte"] / 365.0
    atm["Sx"] = atm["S"] - sg.pv_dividends(atm["date"].to_numpy(), atm["expiry"].to_numpy(), atm["r"].to_numpy(), divs)
    atm["iv"] = np.where(atm["Sx"] > 0,
                         sg.implied_vol(atm["close"], atm["Sx"].clip(lower=1e-9), atm["strike"], atm["T"], atm["r"], atm["is_call"]),
                         np.nan)
    b = bracket_30d(atm)
    for flag, col in ((True, "call_iv30"), (False, "put_iv30")):
        s = b[b["is_call"] == flag].set_index("date")["iv30"]
        out[col] = s.reindex(cal)
    return out


def smoothed(daily: pd.DataFrame) -> pd.DataFrame:
    """5-trading-day mean ending on each date, needing >= 3 observed days."""
    return daily.rolling(WINDOW, min_periods=MIN_DAYS).mean()
