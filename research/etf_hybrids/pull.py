"""Pull daily bars for the ETF-hybrid universe (research/etf_hybrids/PLAN.md).

yfinance Ticker.history(auto_adjust=False, actions=True), from each fund's first bar to 2026-09-18:
  open/high/low/close   split-adjusted, not dividend-adjusted (quoted prices)
  adj_close             split- and distribution-adjusted (total return)
  adj_open              open * adj_close / close (same factor yfinance's auto_adjust applies)
Delisted single-country ETFs in PROBES are requested only to record whether yfinance still serves them;
they are not part of the registered universe.

    PYTHONPATH=. .venv/bin/python -m research.etf_hybrids.pull
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "etf_hybrids"
START, END = "1993-01-01", "2026-09-19"   # end is exclusive in yfinance: last bar 2026-09-18

SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC"]
COUNTRIES = ["EWA", "EWC", "EWG", "EWH", "EWJ", "EWU", "EWS", "EWL", "EWP", "EWQ", "EWI", "EWD", "EWN",
             "EWT", "EWY", "EWZ", "EWW"]
BROAD = ["EEM", "EFA", "SPY"]
PROBES = ["ERUS", "RSX"]   # delisted 2022 (Russia); availability check only


def pull(t: str) -> dict:
    h = yf.Ticker(t).history(start=START, end=END, auto_adjust=False, actions=True)
    if h is None or h.empty:
        return {"ticker": t, "rows": 0}
    h = h.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close",
                          "Adj Close": "adj_close", "Volume": "volume", "Dividends": "dividends",
                          "Stock Splits": "splits", "Capital Gains": "capital_gains"})
    idx = pd.DatetimeIndex(h.index).tz_localize(None).normalize()
    d = h.reset_index(drop=True)
    d.insert(0, "date", idx)
    factor = d["adj_close"] / d["close"]
    for c in ("open", "high", "low"):
        d[f"adj_{c}"] = d[c] * factor
    d["source"] = "yfinance history auto_adjust=False actions=True"
    path = OUT / f"{t}.parquet"
    d.to_parquet(path, index=False)
    return {"ticker": t, "rows": int(len(d)), "first": str(d["date"].min().date()),
            "last": str(d["date"].max().date()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "yfinance": yf.__version__,
                "start": START, "end_exclusive": END, "items": {}, "probes": {}}
    for t in SECTORS + COUNTRIES + BROAD:
        manifest["items"][t] = pull(t)
        time.sleep(0.5)
    for t in PROBES:
        try:
            manifest["probes"][t] = pull(t)
        except Exception as e:  # noqa: BLE001 - a delisted symbol may raise inside yfinance
            manifest["probes"][t] = {"ticker": t, "rows": 0, "error": repr(e)[:200]}
        time.sleep(0.5)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    for k, v in {**manifest["items"], **manifest["probes"]}.items():
        print(k, v.get("rows"), v.get("first"), v.get("last"))


if __name__ == "__main__":
    main()
