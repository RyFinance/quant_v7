"""Unadjusted-for-dividends daily bars (yfinance auto_adjust=False) plus split events for the
options-signal universe. Option strikes are in raw prices, so moneyness and implied volatility need
the raw close: raw = split-adjusted Close x product of split ratios after the date.

Run: PYTHONPATH=. .venv/bin/python -m data.pull_stock_raw
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent
OUT = ROOT / "stocks_raw_2014"
START, END = "2014-05-01", "2026-09-18"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    names = json.loads((ROOT / "lse" / "options_1d" / "universe.json").read_text())["names"]
    raw = yf.download(names, start=START, end=END, auto_adjust=False, actions=True, progress=False,
                      group_by="ticker", threads=True)
    for t in names:
        d = raw[t].dropna(how="all").copy()
        d.index.name = "date"
        splits = d["Stock Splits"].replace(0, 1.0).fillna(1.0)
        # factor on date t = product of split ratios strictly after t
        after = splits[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
        d["split_factor_after"] = after
        d["raw_close"] = d["Close"] * after
        d["raw_volume"] = d["Volume"] / after
        d.reset_index().to_parquet(OUT / f"{t}.parquet", index=False)
    print(len(names), "saved to", OUT)


if __name__ == "__main__":
    main()
