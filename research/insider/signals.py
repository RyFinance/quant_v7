"""Insider events for the registered candidates (research/insider/PLAN.md). No prices, no returns.

Every event is (ticker, signal_date) with signal_date = the FILING_DATE on which the information became
public. Each builder only uses filings with FILING_DATE <= the event's signal date.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

N1_WINDOW_DAYS = 30
N1_MIN_INSIDERS = 2
N1_MIN_VALUE = 50_000.0
N2_MIN_VALUE = 25_000.0
N3_FIRST_YEAR = 2009  # needs trades in each of Y-3..Y-1; the DERA data start in 2006
MAX_LAG_DAYS = 365
A2_BOUNDS = (0.5, 2.0)      # PLAN_AMENDMENT_1 A2: reported price / raw close
A2_MAX_STALE_DAYS = 10

_CEO = re.compile(r"\bCEO\b|CHIEF\s+EXECUTIVE")
_CFO = re.compile(r"\bCFO\b|CHIEF\s+FINANCIAL")
_PRES = re.compile(r"\bPRESIDENT\b|\bPRES\b")
_VICE = re.compile(r"VICE|\bEVP\b|\bSVP\b|\bVP\b|\bV\.P\b")


def is_csuite(title) -> bool:
    if title is None or (isinstance(title, float) and np.isnan(title)) or pd.isna(title):
        return False
    t = str(title).upper()
    if _CEO.search(t) or _CFO.search(t):
        return True
    return bool(_PRES.search(t)) and not _VICE.search(t)


def _cik(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lstrip("0")


def open_market_raw(sub: pd.DataFrame, owners: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Open-market Form 4 trades and their owners, before tickers are attached. It works on one
    quarterly ZIP at a time, because a filing's three tables always sit in the same ZIP.

    trades: accession, sk, issuer_cik, filing_date, trans_date, code (P/S), value
    owners: accession, owner_cik, is_dir, is_off, is_offdir, is_csuite
    """
    s = sub[sub["DOCUMENT_TYPE"].astype(str).str.strip() == "4"][["ACCESSION_NUMBER", "FILING_DATE", "ISSUERCIK"]]
    s = s.rename(columns={"ACCESSION_NUMBER": "accession", "FILING_DATE": "filing_date"})
    s["issuer_cik"] = _cik(s.pop("ISSUERCIK"))
    t = trades.rename(columns={"ACCESSION_NUMBER": "accession", "TRANS_DATE": "trans_date", "TRANS_CODE": "code",
                               "NONDERIV_TRANS_SK": "sk"})
    ad = t["TRANS_ACQUIRED_DISP_CD"].astype(str).str.strip().str.upper()
    ok = ((t["code"] == "P") & (ad == "A")) | ((t["code"] == "S") & (ad == "D"))
    ok &= (t["TRANS_SHARES"] > 0) & (t["TRANS_PRICEPERSHARE"] > 0)
    t = t[ok].assign(value=lambda x: x["TRANS_SHARES"] * x["TRANS_PRICEPERSHARE"],
                     price=lambda x: x["TRANS_PRICEPERSHARE"])
    t = t[["accession", "sk", "trans_date", "code", "value", "price"]].merge(s, on="accession", how="inner")
    lag = (t["filing_date"] - t["trans_date"]).dt.days
    t = t[(lag >= 0) & (lag <= MAX_LAG_DAYS)].reset_index(drop=True)

    o = owners[owners["ACCESSION_NUMBER"].isin(set(t["accession"]))]
    rel = o["RPTOWNER_RELATIONSHIP"].astype(str).str.upper()
    o = pd.DataFrame({
        "accession": o["ACCESSION_NUMBER"].to_numpy(), "owner_cik": _cik(o["RPTOWNERCIK"]).to_numpy(),
        "is_dir": rel.str.contains("DIRECTOR").to_numpy(), "is_off": rel.str.contains("OFFICER").to_numpy(),
        "title": o["RPTOWNER_TITLE"].to_numpy(),
    })
    o["is_offdir"] = o["is_dir"] | o["is_off"]
    o["is_csuite"] = o["is_off"] & o["title"].map(is_csuite)
    return t, o.drop(columns="title")


def price_consistent(om: pd.DataFrame, raw_close_of) -> np.ndarray:
    """PLAN_AMENDMENT_1 A2. True for every S row; a P row is True only if the raw close on the last
    session on/before its trade date (at most A2_MAX_STALE_DAYS earlier) exists and the reported price
    per share is within A2_BOUNDS times it. raw_close_of(ticker) -> date-indexed Series or None."""
    ok = (om["code"] != "P").to_numpy().copy()
    p = om[(om["code"] == "P") & om["ticker"].notna()]
    rows = np.arange(len(om))
    pos_of = pd.Series(rows, index=om.index)
    for tk, g in p.groupby("ticker", sort=False):
        s = raw_close_of(tk)
        if s is None or len(s) == 0:
            continue
        dates, vals = s.index.values, s.to_numpy(dtype=float)
        td = g["trans_date"].to_numpy()
        pos = np.searchsorted(dates, td, side="right") - 1
        pc = np.clip(pos, 0, None)
        near = (pos >= 0) & ((td - dates[pc]) <= np.timedelta64(A2_MAX_STALE_DAYS, "D"))
        with np.errstate(divide="ignore", invalid="ignore"):
            r = g["price"].to_numpy(dtype=float) / vals[pc]
        ok[pos_of.loc[g.index].to_numpy()] = near & (r >= A2_BOUNDS[0]) & (r <= A2_BOUNDS[1])
    return ok


def attach_tickers(om: pd.DataFrame, cik_ticker: pd.DataFrame) -> pd.DataFrame:
    ct = cik_ticker.assign(issuer_cik=_cik(cik_ticker["issuer_cik"]))[["issuer_cik", "ticker"]]
    return om.drop(columns=["ticker"], errors="ignore").merge(ct, on="issuer_cik", how="left")


def open_market(sub: pd.DataFrame, owners: pd.DataFrame, trades: pd.DataFrame,
                cik_ticker: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """open_market_raw plus tickers (see there)."""
    om, own = open_market_raw(sub, owners, trades)
    return attach_tickers(om, cik_ticker), own


def _purchases(om: pd.DataFrame, own: pd.DataFrame, flag: str) -> pd.DataFrame:
    """P trades in accessions with at least one owner carrying `flag`, mapped to a ticker."""
    acc = set(own.loc[own[flag], "accession"])
    p = om[(om["code"] == "P") & om["accession"].isin(acc) & om["ticker"].notna()]
    return p


def events_n1(om: pd.DataFrame, own: pd.DataFrame) -> pd.DataFrame:
    p = _purchases(om, own, "is_offdir")
    ins = own.loc[own["is_offdir"], ["accession", "owner_cik"]]
    gi = p[["ticker", "accession", "filing_date", "trans_date"]].merge(ins, on="accession")
    gi["owner_code"] = pd.factorize(gi["owner_cik"])[0]
    owners_by_ticker = {k: (v["filing_date"].to_numpy(), v["trans_date"].to_numpy(), v["owner_code"].to_numpy())
                        for k, v in gi.groupby("ticker", sort=False)}
    win = np.timedelta64(N1_WINDOW_DAYS, "D")
    rows = []
    for tk, g in p.groupby("ticker", sort=True):
        fd, td, val = g["filing_date"].to_numpy(), g["trans_date"].to_numpy(), g["value"].to_numpy()
        hfd, htd, hc = owners_by_ticker[tk]
        for d in np.unique(fd):
            lo = d - win
            m = (fd <= d) & (td >= lo)       # known by d, traded within the window
            if val[m].sum() < N1_MIN_VALUE:
                continue
            mh = (hfd <= d) & (htd >= lo)
            if mh.any() and hc[mh].min() != hc[mh].max():   # at least two distinct insiders
                rows.append((tk, pd.Timestamp(d)))
    return pd.DataFrame(rows, columns=["ticker", "signal_date"])


def _events_n1_reference(om: pd.DataFrame, own: pd.DataFrame) -> pd.DataFrame:
    """Direct transcription of the PLAN rule (slow); tests check events_n1 against it."""
    p = _purchases(om, own, "is_offdir")
    insiders = own[own["is_offdir"]][["accession", "owner_cik"]]
    rows = []
    for tk, g in p.groupby("ticker", sort=True):
        gi = g[["accession", "filing_date", "trans_date"]].merge(insiders, on="accession")
        for d in sorted(g["filing_date"].unique()):
            lo = d - pd.Timedelta(days=N1_WINDOW_DAYS)
            w = g[(g["filing_date"] <= d) & (g["trans_date"] >= lo)]
            wi = gi[(gi["filing_date"] <= d) & (gi["trans_date"] >= lo)]
            if w["value"].sum() >= N1_MIN_VALUE and wi["owner_cik"].nunique() >= N1_MIN_INSIDERS:
                rows.append((tk, pd.Timestamp(d)))
    return pd.DataFrame(rows, columns=["ticker", "signal_date"])


def events_n2(om: pd.DataFrame, own: pd.DataFrame) -> pd.DataFrame:
    p = _purchases(om, own, "is_csuite")
    v = p.groupby(["ticker", "filing_date"])["value"].sum().reset_index()
    v = v[v["value"] >= N2_MIN_VALUE]
    return v.rename(columns={"filing_date": "signal_date"})[["ticker", "signal_date"]].reset_index(drop=True)


def classify_cmp(om: pd.DataFrame, own: pd.DataFrame, year: int) -> pd.DataFrame:
    """Cohen-Malloy-Pomorski classification at the start of `year`, point in time.

    Uses open-market P/S trades (any role) with trans_date in year-3..year-1 AND filing_date on or
    before 31 Dec of year-1. Returns owner_cik, issuer_cik, kind in {routine, opportunistic}."""
    cut = pd.Timestamp(year - 1, 12, 31)
    t = om[(om["filing_date"] <= cut) & om["trans_date"].dt.year.between(year - 3, year - 1)]
    t = t[["accession", "issuer_cik", "trans_date"]].merge(own[["accession", "owner_cik"]], on="accession")
    t = t.assign(y=t["trans_date"].dt.year, m=t["trans_date"].dt.month)
    years = t.groupby(["owner_cik", "issuer_cik"])["y"].nunique()
    full = years[years == 3].index
    if len(full) == 0:
        return pd.DataFrame(columns=["owner_cik", "issuer_cik", "kind"])
    tm = t.set_index(["owner_cik", "issuer_cik"]).loc[full].reset_index()
    per_month = tm.groupby(["owner_cik", "issuer_cik", "m"])["y"].nunique()
    routine = set(per_month[per_month == 3].reset_index().set_index(["owner_cik", "issuer_cik"]).index)
    out = pd.DataFrame(list(full), columns=["owner_cik", "issuer_cik"])
    out["kind"] = ["routine" if k in routine else "opportunistic" for k in zip(out["owner_cik"], out["issuer_cik"])]
    return out


def events_n3(om: pd.DataFrame, own: pd.DataFrame, trig: pd.DataFrame | None = None) -> pd.DataFrame:
    """Classification history from `om` (all open-market P/S trades); triggering purchases from
    `trig` (defaults to `om`; the A2 price check filters it)."""
    p = _purchases(om if trig is None else trig, own, "is_offdir")
    rows = []
    last_year = int(p["filing_date"].dt.year.max()) if len(p) else N3_FIRST_YEAR - 1
    for y in range(N3_FIRST_YEAR, last_year + 1):
        cls = classify_cmp(om, own, y)
        opp = cls[cls["kind"] == "opportunistic"][["owner_cik", "issuer_cik"]]
        py = p[p["filing_date"].dt.year == y][["accession", "issuer_cik", "ticker", "filing_date"]]
        py = py.merge(own[own["is_offdir"]][["accession", "owner_cik"]], on="accession")
        hit = py.merge(opp, on=["owner_cik", "issuer_cik"])
        rows.append(hit[["ticker", "filing_date"]].drop_duplicates())
    ev = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["ticker", "filing_date"])
    return ev.rename(columns={"filing_date": "signal_date"}).drop_duplicates().reset_index(drop=True)


def all_events(om: pd.DataFrame, own: pd.DataFrame, valid: np.ndarray | None = None) -> dict[str, pd.DataFrame]:
    """valid: PLAN_AMENDMENT_1 A2 flags aligned with om. Purchases failing it never trigger or count
    toward an event; the N3 trading history still uses every open-market trade."""
    trig = om if valid is None else om[valid]
    return {"N1_cluster": events_n1(trig, own), "N2_csuite": events_n2(trig, own),
            "N3_opportunistic": events_n3(om, own, trig)}
