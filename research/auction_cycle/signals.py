"""Auction dates, event windows and positions for research/auction_cycle/PLAN.md."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LSE_CAL = ROOT / "data" / "lse" / "econ_calendar_us.parquet"
FISCAL = ROOT / "data" / "treasury" / "auctions_fiscaldata_raw.json"
ETF = ROOT / "data" / "multiasset" / "etf"
TENORS = {"2-Year Note Auction": 2, "3-Year Note Auction": 3, "5-Year Note Auction": 5,
          "7-Year Note Auction": 7, "10-Year Note Auction": 10, "30-Year Bond Auction": 30}
PRE, POST = 4, 3  # pre: return days a-4..a ; post: a+1..a+3


def lse_auctions() -> pd.DataFrame:
    d = pd.read_parquet(LSE_CAL, columns=["date", "region_code", "event"])
    d = d[(d.region_code == "US") & d.event.isin(TENORS)]
    return pd.DataFrame({"date": pd.to_datetime(d.date), "tenor": d.event.map(TENORS), "src": "lse"})


TERM_MAP = {"2-Year": 2, "3-Year": 3, "5-Year": 5, "7-Year": 7, "10-Year": 10, "9-Year 10-Month": 10,
            "9-Year 11-Month": 10, "30-Year": 30, "29-Year 10-Month": 30, "29-Year 11-Month": 30}


def fiscal_auctions() -> pd.DataFrame:
    """Treasury fiscaldata nominal coupon auctions (amendment 1: tenor from security_term; drop
    auctions announced on the auction day)."""
    f = pd.DataFrame(json.loads(FISCAL.read_text())["data"])
    f = f[f.security_type.isin(["Note", "Bond"]) & (f.inflation_index_security == "No") & (f.floating_rate == "No")]
    f = f[f.security_term.isin(TERM_MAP)]
    lead = (pd.to_datetime(f.auction_date) - pd.to_datetime(f.announcemt_date)).dt.days
    f = f[lead >= 1]
    return pd.DataFrame({"date": pd.to_datetime(f.auction_date), "tenor": f.security_term.map(TERM_MAP).astype(int),
                         "src": "fiscal"})


def auctions() -> pd.DataFrame:
    a = pd.concat([lse_auctions(), fiscal_auctions()], ignore_index=True)
    return a.drop_duplicates(["date", "tenor"]).sort_values(["date", "tenor"]).reset_index(drop=True)


def load_prices(sym: str = "IEF", upto: pd.Timestamp | None = None) -> pd.Series:
    x = pd.read_parquet(ETF / f"{sym}.parquet")
    s = pd.Series(x["close"].to_numpy(float), index=pd.to_datetime(x["date"]), name=sym).sort_index()
    if upto is not None:
        s = s[s.index <= upto]
    return s


def auction_index(dates: pd.DatetimeIndex, trading: pd.DatetimeIndex) -> np.ndarray:
    """Position in `trading` of each auction date (next trading day if not one). Dates beyond the
    calendar end are dropped."""
    pos = trading.searchsorted(pd.DatetimeIndex(dates), side="left")
    return np.unique(pos[pos < len(trading)])


def windows(trading: pd.DatetimeIndex, adates: pd.DatetimeIndex) -> pd.DataFrame:
    """Boolean pre/post flags per return day. An auction on index a marks return days a-PRE..a as pre
    and a+1..a+POST as post. Auctions after the last trading day still mark earlier pre days via their
    calendar position (they are pre-announced)."""
    n = len(trading)
    pre = np.zeros(n, bool)
    post = np.zeros(n, bool)
    # auctions after the price calendar end: approximate their index with business days past the end
    ad = pd.DatetimeIndex(adates).sort_values()
    inside = ad[ad <= trading[-1]]
    beyond = ad[ad > trading[-1]]
    idx = list(auction_index(inside, trading))
    idx += [n - 1 + len(pd.bdate_range(trading[-1], d)) - 1 for d in beyond]
    for a in idx:
        lo, hi = max(a - PRE, 0), min(a, n - 1)
        if lo <= hi:
            pre[lo:hi + 1] = True
        if a + 1 < n:
            post[a + 1:min(a + POST, n - 1) + 1] = True
    return pd.DataFrame({"pre": pre, "post": post}, index=trading)


def positions(trading: pd.DatetimeIndex, adates: pd.DatetimeIndex) -> pd.DataFrame:
    """Held weight on each return day (w_i earns r_i; chosen at close i-1)."""
    w = windows(trading, adates)
    a1 = -w["pre"].astype(float)
    a2 = (w["post"] & ~w["pre"]).astype(float)
    return pd.DataFrame({"A1_pre_short": a1, "A2_post_long": a2, "A3_combined": a1 + a2}, index=trading)
