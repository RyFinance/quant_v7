"""Loaders for the two evaluation windows (inputs table of research/pead_portfolio/PLAN.md).

Each returns a DataFrame on the PEAD calendar with columns:
P (PEAD excess), G (gross exposure carried into the day), M (SPY excess, the hedge instrument),
MKT (French mkt_rf), RF, tsmom_broad, fx_carry, bond_carry (sleeve excess; NaN where missing).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research.options_signals.signals import french_daily

ROOT = Path(__file__).resolve().parents[2]
SLEEVES = ["tsmom_broad", "fx_carry", "bond_carry"]


def _rf_on(cal: pd.DatetimeIndex, ff: pd.DataFrame) -> pd.Series:
    return ff["rf"].reindex(cal.union(ff.index)).ffill().reindex(cal)


def _spy(path: Path, col: str) -> pd.Series:
    d = pd.read_parquet(path)
    d["date"] = pd.to_datetime(d["date"])
    if getattr(d["date"].dt, "tz", None) is not None:
        d["date"] = d["date"].dt.tz_localize(None)
    return d.assign(date=d["date"].dt.normalize()).drop_duplicates("date").set_index("date")[col].sort_index()


def _pead_gross_main(cal: pd.DatetimeIndex, rf: pd.Series, curves: pd.DataFrame) -> pd.Series:
    from research.pead_audit import mtm_audit as A
    p = A.positions("wide_5p0")
    px = A.closes(list(p["ticker"].unique()))
    b = A.mtm_book(p, px, cal, rf, A.ONE_WAY, 0.0, cash_earns_rf=True)
    diff = float((b["nav"] / A.START_CAPITAL - curves["mtm_rf"]).abs().max())
    if diff > 1e-9:
        raise AssertionError(f"rebuilt PEAD NAV differs from wide_5p0_curves.csv by {diff}")
    return (b["long_mv"] + b["short_mv"]) / b["nav"].shift(1).fillna(A.START_CAPITAL)


def load_main() -> pd.DataFrame:
    curves = pd.read_csv(ROOT / "reports/pead_audit/wide_5p0_curves.csv", index_col=0, parse_dates=True)
    ff = french_daily()
    full_cal = curves.index
    G = _pead_gross_main(full_cal, _rf_on(full_cal, ff), curves)
    P = (curves["mtm_rf"].pct_change() - curves["rf_index"].pct_change()).dropna()
    cal = P.index
    rf = _rf_on(cal, ff)
    spy = _spy(ROOT / "data/stocks_raw_2014/SPY.parquet", "Adj Close")
    M = spy.pct_change().reindex(cal) - rf
    sl = pd.read_csv(ROOT / "reports/multiasset/holdout/holdout_returns.csv", index_col=0, parse_dates=True)
    out = pd.DataFrame({"P": P, "G": G.reindex(cal), "M": M, "MKT": ff["mkt_rf"].reindex(cal), "RF": rf}, index=cal)
    for s in SLEEVES:
        out[s] = sl[s].reindex(cal)
    _check(out)
    return out


def load_old() -> pd.DataFrame:
    m = pd.read_csv(ROOT / "reports/pead_2004_2014/model.csv", index_col=0, parse_dates=True)
    cal = m.index
    ff = french_daily()
    rf = _rf_on(cal, ff)
    spy = _spy(ROOT / "data/yf_2003_2015/SPY.parquet", "close")
    M = spy.pct_change().reindex(cal) - rf
    dev = pd.read_csv(ROOT / "reports/multiasset/dev_sleeve_returns.csv", index_col=0, parse_dates=True)
    out = pd.DataFrame({"P": m["return"] - rf, "G": m["gross"].shift(1).fillna(0.0), "M": M,
                        "MKT": ff["mkt_rf"].reindex(cal), "RF": rf}, index=cal)
    for s in SLEEVES:
        out[s] = dev[s].reindex(cal)
    _check(out)
    return out


def _check(d: pd.DataFrame) -> None:
    for c in ["P", "G", "M", "MKT", "RF"]:
        if d[c].isna().any():
            raise ValueError(f"{c} has {int(d[c].isna().sum())} missing days")
    for s in SLEEVES:  # after its first valid day a sleeve must be complete
        x = d[s].loc[d[s].first_valid_index():] if d[s].notna().any() else d[s]
        if x.isna().any():
            raise ValueError(f"{s} has gaps after its start")
