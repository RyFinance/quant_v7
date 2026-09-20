"""SEC DERA Insider Transactions Data Sets: download, parse, coverage (no returns).

  PYTHONPATH=. SEC_USER_AGENT="quant_v7-research <your name> <your e-mail>" \
      .venv/bin/python -m research.insider.sec_data download
  PYTHONPATH=. .venv/bin/python -m research.insider.sec_data parse
  PYTHONPATH=. .venv/bin/python -m research.insider.prices          # yfinance bars for mapped tickers
  PYTHONPATH=. .venv/bin/python -m research.insider.sec_data coverage

Access policy. SEC's fair-access rules ask for at most 10 requests per second and a User-Agent that
declares who is calling, normally with a contact e-mail. This script sends at most 2 requests per
second and reads the User-Agent from SEC_USER_AGENT. The default, DEFAULT_UA, contains no e-mail.
On 2026-09-18 SEC answered every request that used DEFAULT_UA with HTTP 403: the Akamai "Request Rate
Threshold Exceeded" page, which is also the page it serves undeclared tools. The script never invents
a contact address. Whoever runs it supplies their own in SEC_USER_AGENT, or downloads the ZIPs by hand
into data/sec_insider/raw/, which `parse` accepts as they are.

`coverage` reports counts by year, filing lags, ticker-matching rates and event counts. It never
touches a return, so it may be run before the PLAN is registered.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "sec_insider"
RAW = DATA / "raw"
INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
DEFAULT_UA = "quant_v7-research personal-research-script"
MIN_INTERVAL = 0.5  # seconds between requests: 2/s, well under SEC's limit and the 5/s asked for here

SUB_COLS = ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL"]
OWN_COLS = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]
TRN_COLS = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
            "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"]


class SecRefused(RuntimeError):
    pass


# -- download ---------------------------------------------------------------------------------------
class _Client:
    def __init__(self, user_agent: str | None = None):
        self.ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_UA
        self._last = 0.0

    def get(self, url: str) -> bytes:
        wait = self._last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise SecRefused(
                    f"SEC refused {url} with HTTP 403 for User-Agent {self.ua!r}. SEC requires a declared "
                    "User-Agent with a contact e-mail. Set SEC_USER_AGENT to one you own; this script will "
                    "not invent one. Or download the ZIPs by hand into data/sec_insider/raw/.") from None
            raise


def zip_links(index_html: str) -> list[str]:
    hrefs = re.findall(r'href="([^"]+?_form345\.zip)"', index_html, flags=re.I)
    urls = sorted({urllib.parse.urljoin("https://www.sec.gov/", h) for h in hrefs})
    return urls


def download(user_agent: str | None = None) -> list[Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    client = _Client(user_agent)
    html = client.get(INDEX_URL).decode("utf-8", "replace")
    urls = zip_links(html)
    if not urls:
        raise RuntimeError("no *_form345.zip links on the SEC index page; the page layout may have changed")
    manifest_path = DATA / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    out = []
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        path = RAW / name
        if path.exists() and name in manifest and manifest[name]["bytes"] == path.stat().st_size:
            out.append(path)
            continue
        blob = client.get(url)
        zipfile.ZipFile(io.BytesIO(blob)).testzip()
        path.write_bytes(blob)
        manifest[name] = {"url": url, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                          "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
        print(f"{name}: {len(blob) / 1e6:.1f} MB")
        out.append(path)
    return out


# -- parse ------------------------------------------------------------------------------------------
def parse_sec_date(s: pd.Series) -> pd.Series:
    """DERA dates are DD-MON-YYYY (e.g. 03-JAN-2006); a few files use ISO dates."""
    s = s.astype("string").str.strip().str.upper()
    out = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    miss = out.isna() & s.notna() & (s != "")
    if miss.any():
        out[miss] = pd.to_datetime(s[miss], format="%Y-%m-%d", errors="coerce")
    return out


def _read_table(z: zipfile.ZipFile, table: str, cols: list[str]) -> pd.DataFrame:
    names = [n for n in z.namelist() if Path(n).name.upper() == f"{table}.TSV"]
    if not names:
        raise KeyError(f"{table}.tsv not in {z.filename}: {z.namelist()}")
    with z.open(names[0]) as f:
        header = [c.strip().upper() for c in f.readline().decode("utf-8", "replace").rstrip("\r\n").split("\t")]
    missing = [c for c in cols if c not in header]
    if missing:
        raise KeyError(f"{table} in {z.filename} lacks {missing}; has {header}")
    with z.open(names[0]) as f:
        df = pd.read_csv(f, sep="\t", dtype=str, quoting=3, keep_default_na=False, na_values=[""],
                         encoding="utf-8", encoding_errors="replace", on_bad_lines="warn",
                         usecols=lambda c: c.strip().upper() in cols)
    df.columns = [c.strip().upper() for c in df.columns]
    return df[cols]


def parse_zip(path: Path) -> dict[str, pd.DataFrame]:
    """The three tables of one quarterly ZIP, trades reduced to open-market codes P and S."""
    with zipfile.ZipFile(path) as z:
        sub = _read_table(z, "SUBMISSION", SUB_COLS)
        own = _read_table(z, "REPORTINGOWNER", OWN_COLS)
        trn = _read_table(z, "NONDERIV_TRANS", TRN_COLS)
    sub["FILING_DATE"] = parse_sec_date(sub["FILING_DATE"])
    trn["TRANS_DATE"] = parse_sec_date(trn["TRANS_DATE"])
    trn["TRANS_CODE"] = trn["TRANS_CODE"].str.strip().str.upper()
    code_counts = trn["TRANS_CODE"].value_counts().rename_axis("code").reset_index(name="n")
    code_counts["source"] = path.name
    trn = trn[trn["TRANS_CODE"].isin(["P", "S"])].copy()
    for c in ("TRANS_SHARES", "TRANS_PRICEPERSHARE"):
        trn[c] = pd.to_numeric(trn[c].str.replace(",", "", regex=False), errors="coerce")
    return {"submissions": sub, "owners": own, "trades": trn, "code_counts": code_counts}


def reduce_quarter(path: Path) -> dict[str, pd.DataFrame]:
    """One ZIP -> the small tables the study needs (see parse_all)."""
    from research.insider import signals as sg

    t = parse_zip(path)
    sub = t["submissions"]
    om, own = sg.open_market_raw(sub, t["owners"], t["trades"])
    sym = sub[["ISSUERCIK", "FILING_DATE", "ISSUERTRADINGSYMBOL"]].copy()
    sym["ticker"] = sym["ISSUERTRADINGSYMBOL"].map(clean_symbol)
    sym["issuer_cik"] = sym["ISSUERCIK"].astype(str).str.strip().str.lstrip("0")
    n_all = sym.groupby("issuer_cik").size().rename("n_filings")
    sym = sym.dropna(subset=["ticker", "FILING_DATE"]).sort_values(["issuer_cik", "FILING_DATE"], kind="stable")
    sym = (sym.groupby("issuer_cik").agg(ticker=("ticker", "last"), last_filing=("FILING_DATE", "max"))
              .join(n_all).reset_index())
    filings = (sub.assign(year=sub["FILING_DATE"].dt.year, doc=sub["DOCUMENT_TYPE"].astype(str).str.strip())
                  .groupby(["year", "doc"]).size().rename("n").reset_index())
    filings["raw_symbol_missing"] = int(sub["ISSUERTRADINGSYMBOL"].map(clean_symbol).isna().sum())
    filings["source"] = path.name
    unparsed = {"filing_date": int(sub["FILING_DATE"].isna().sum()), "trans_date": int(t["trades"]["TRANS_DATE"].isna().sum())}
    return {"om": om, "own": own, "sym": sym, "filings": filings, "codes": t["code_counts"],
            "unparsed": pd.DataFrame([{**unparsed, "source": path.name}])}


PARSED = DATA / "parsed"
PARTS = ("om", "own", "sym", "filings", "codes", "unparsed")


def parse_all() -> dict[str, int]:
    """Quarter by quarter (one ZIP in memory at a time), cached in data/sec_insider/parsed/; then
    combined into om.parquet (open-market Form 4 trades), own.parquet (their owners), cik_ticker.parquet,
    filing_counts.parquet, code_counts.parquet, unparsed.parquet."""
    zips = sorted(RAW.glob("*_form345.zip"))
    if not zips:
        raise SystemExit(f"no ZIPs in {RAW}; run `download` first (see the module docstring)")
    PARSED.mkdir(parents=True, exist_ok=True)
    for p in zips:
        if all((PARSED / f"{p.stem}_{k}.parquet").exists() for k in PARTS):
            continue
        red = reduce_quarter(p)
        for k in PARTS:
            red[k].to_parquet(PARSED / f"{p.stem}_{k}.parquet", index=False)
        print(f"{p.stem}: {len(red['om']):,} open-market trades, {len(red['own']):,} owners", flush=True)
        del red
    stems = [p.stem for p in zips]

    def cat(k):
        return pd.concat([pd.read_parquet(PARSED / f"{s}_{k}.parquet") for s in stems], ignore_index=True)

    om = cat("om").drop_duplicates(["accession", "sk"], keep="last")
    own = cat("own").drop_duplicates(["accession", "owner_cik"], keep="last")
    om.to_parquet(DATA / "om.parquet", index=False)
    own.to_parquet(DATA / "own.parquet", index=False)
    sym = cat("sym")
    ct = (sym.sort_values(["issuer_cik", "last_filing"], kind="stable")
             .groupby("issuer_cik").agg(ticker=("ticker", "last"), last_filing=("last_filing", "max"),
                                        n_filings=("n_filings", "sum")).reset_index())
    ct = ct.sort_values("last_filing", kind="stable").drop_duplicates("ticker", keep="last").reset_index(drop=True)
    ct.to_parquet(DATA / "cik_ticker.parquet", index=False)
    cat("filings").to_parquet(DATA / "filing_counts.parquet", index=False)
    cat("codes").to_parquet(DATA / "code_counts.parquet", index=False)
    cat("unparsed").to_parquet(DATA / "unparsed.parquet", index=False)
    out = {"om": len(om), "own": len(own), "cik_ticker": len(ct)}
    print(out)
    return out


# -- tickers ----------------------------------------------------------------------------------------
BAD_SYMBOLS = {"", "NONE", "NA", "N-A", "NULL", "NIL", "PRIVATE", "NOTICKER", "UNKNOWN", "TBD"}


def clean_symbol(s) -> str | None:
    if s is None or (isinstance(s, float) and np.isnan(s)) or pd.isna(s):
        return None
    s = str(s).upper().strip()
    if ":" in s:  # "NYSE: ABC"
        s = s.split(":")[-1].strip()
    s = re.split(r"[\s,;]+", s)[0] if s else ""
    s = re.sub(r"[^A-Z0-9.\-/]", "", s).replace(".", "-").replace("/", "-").strip("-")
    if s in BAD_SYMBOLS or len(s) > 8 or not re.match(r"[A-Z]", s):
        return None
    return s


def cik_ticker_map(sub: pd.DataFrame) -> pd.DataFrame:
    """One current ticker per issuer CIK (symbol on its latest filing); a symbol claimed by several
    CIKs goes to the CIK that filed most recently, the rest stay unmatched."""
    s = sub[["ISSUERCIK", "FILING_DATE", "ISSUERTRADINGSYMBOL"]].copy()
    s["ticker"] = s["ISSUERTRADINGSYMBOL"].map(clean_symbol)
    s = s.dropna(subset=["ticker", "FILING_DATE"])
    s["ISSUERCIK"] = s["ISSUERCIK"].astype(str).str.lstrip("0")
    last = (s.sort_values(["ISSUERCIK", "FILING_DATE"])
              .groupby("ISSUERCIK").agg(ticker=("ticker", "last"), last_filing=("FILING_DATE", "max"),
                                        n_filings=("ticker", "size"))
              .reset_index())
    last = last.sort_values("last_filing").drop_duplicates("ticker", keep="last")
    return last.rename(columns={"ISSUERCIK": "issuer_cik"}).reset_index(drop=True)


def load_open_market(upto: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(open-market trades with tickers, their owners), truncated at FILING_DATE <= upto. The
    development lock goes through here."""
    from research.insider import signals as sg

    missing = [k for k in ("om", "own", "cik_ticker") if not (DATA / f"{k}.parquet").exists()]
    if missing:
        raise SystemExit(f"parsed SEC tables missing in {DATA} ({missing}); run `download` (needs SEC_USER_AGENT "
                         "with your own contact e-mail, or ZIPs placed by hand in data/sec_insider/raw/) and `parse`")
    om = pd.read_parquet(DATA / "om.parquet")
    own = pd.read_parquet(DATA / "own.parquet")
    if upto is not None:
        om = om[om["filing_date"] <= upto]
        own = own[own["accession"].isin(set(om["accession"]))]
    om = sg.attach_tickers(om, pd.read_parquet(DATA / "cik_ticker.parquet"))
    return om.reset_index(drop=True), own.reset_index(drop=True)


# -- coverage (no returns) --------------------------------------------------------------------------
def coverage(with_prices: bool = True) -> dict:
    """Counts, lags, ticker matching and event counts. Never touches a return."""
    from research.insider import prices as px
    from research.insider import signals as sg

    om, own = load_open_market()
    fc = pd.read_parquet(DATA / "filing_counts.parquet")
    rep: dict = {}
    rep["filings_by_year"] = fc.groupby(["year", "doc"])["n"].sum().unstack(fill_value=0).astype(int).to_dict(orient="index")
    rep["raw_trans_codes"] = pd.read_parquet(DATA / "code_counts.parquet").groupby("code")["n"].sum().nlargest(12).to_dict()
    rep["unparsed_dates"] = pd.read_parquet(DATA / "unparsed.parquet")[["filing_date", "trans_date"]].sum().to_dict()
    p = om[om["code"] == "P"]
    s_ = om[om["code"] == "S"]
    fy = p["filing_date"].dt.year
    rep["open_market_by_year"] = pd.DataFrame({
        "P_trades": p.groupby(fy).size(), "P_accessions": p.groupby(fy)["accession"].nunique(),
        "P_value_musd": (p.groupby(fy)["value"].sum() / 1e6).round(1),
        "P_issuers": p.groupby(fy)["issuer_cik"].nunique(),
        "S_trades": s_.groupby(s_["filing_date"].dt.year).size(),
    }).fillna(0).to_dict(orient="index")
    lag = (p["filing_date"] - p["trans_date"]).dt.days
    rep["P_filing_lag_days"] = {f"q{int(q * 100)}": float(lag.quantile(q)) for q in (0.5, 0.75, 0.9, 0.95, 0.99)}
    bd = np.busday_count(p["trans_date"].values.astype("datetime64[D]"), p["filing_date"].values.astype("datetime64[D]"))
    rep["P_filing_lag_share_le_2_business_days"] = float((bd <= 2).mean())
    rep["P_filing_lag_share_le_2bd_by_year"] = pd.Series(bd <= 2, index=p.index).groupby(fy).mean().round(3).to_dict()
    pa = p.drop_duplicates("accession")
    pay = pa["filing_date"].dt.year
    match = {"accessions": pa.groupby(pay).size(), "share_ticker_mapped": pa["ticker"].notna().groupby(pay).mean().round(3)}
    if with_prices:
        have_px = set(px.available_tickers())
        match["share_with_yf_prices"] = pa["ticker"].isin(have_px).groupby(pay).mean().round(3)
        rep["P_value_share_with_yf_prices"] = float(p.loc[p["ticker"].isin(have_px), "value"].sum() / p["value"].sum())
        rep["tickers_with_yf_prices"] = len(have_px & set(pa["ticker"].dropna()))
    rep["P_accession_matching_by_year"] = pd.DataFrame(match).to_dict(orient="index")
    rep["P_value_share_ticker_mapped"] = float(p.loc[p["ticker"].notna(), "value"].sum() / p["value"].sum())
    rep["issuers_with_P"] = int(pa["issuer_cik"].nunique())
    rep["tickers_mapped_with_P"] = int(pa["ticker"].nunique())
    rep["owner_roles_on_P_accessions"] = {
        "officer_or_director": float(own[own["accession"].isin(set(pa["accession"]))].groupby("accession")["is_offdir"].any().mean()),
        "csuite": float(own[own["accession"].isin(set(pa["accession"]))].groupby("accession")["is_csuite"].any().mean()),
    }
    ev = sg.all_events(om, own)
    rep["events_by_year"] = {k: v.groupby(v["signal_date"].dt.year).size().to_dict() for k, v in ev.items()}
    rep["event_tickers"] = {k: int(v["ticker"].nunique()) for k, v in ev.items()}
    if with_prices:
        # amendment 1 A2 (reported price vs raw close) and amendment 2 B1/B2 (bad prints); no returns
        a2 = sg.price_consistent(om, lambda t: px.raw_close_series(t, pd.Timestamp.max))
        pp = (om["code"] == "P").to_numpy()
        with_px = pp & om["ticker"].isin(have_px).to_numpy()
        yr = om["filing_date"].dt.year
        rep["A2_pass_share_of_priced_P_by_year"] = (pd.Series(a2[with_px], index=om.index[with_px])
                                                    .groupby(yr[with_px]).mean().round(3).to_dict())
        rep["A2_pass_share_of_priced_P"] = float(a2[with_px].mean())
        ev2 = sg.all_events(om, own, valid=a2)
        rep["events_by_year_after_A2"] = {k: v.groupby(v["signal_date"].dt.year).size().to_dict() for k, v in ev2.items()}
        rep["bar_cleaning"] = px.bar_quality()
    name = "coverage.json" if with_prices else "coverage_pre_prices.json"
    (DATA / name).write_text(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "download"
    if cmd == "download":
        try:
            files = download()
        except SecRefused as e:
            raise SystemExit(str(e))
        print(f"{len(files)} ZIPs in {RAW}")
    elif cmd == "parse":
        parse_all()
    elif cmd == "coverage":
        print(json.dumps(coverage(with_prices="--no-prices" not in sys.argv), indent=1, default=str))
    else:
        raise SystemExit("usage: download | parse | coverage")
