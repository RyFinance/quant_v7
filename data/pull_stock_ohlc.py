"""One consistent yfinance download of official daily OHLC for the S&P 500 universe, 2003 on.

Two earlier caches (data/yf_2003_2015, data/raw) were adjusted on different dates, so
their prices do not chain. Research that needs opens AND closes across 2003-2026 (the
overnight/intraday sleeves in research/multiasset) reads this one instead.

Run: PYTHONPATH=. .venv/bin/python -m data.pull_stock_ohlc
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

from bot.earnings_watcher import load_validated_universe

OUT = Path(__file__).parent / "multiasset" / "stocks"
START = "2003-01-01"


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    tickers = sorted(set(load_validated_universe()))
    todo = [t for t in tickers if not (OUT / f"{t}.parquet").exists()]
    failed = []
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        raw = yf.download(chunk, start=START, auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for t in chunk:
            try:
                d = (raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw).dropna(how="all")
            except KeyError:
                failed.append(t)
                continue
            if d.empty:
                failed.append(t)
                continue
            d = d.copy()
            d.columns = [str(c).lower() for c in d.columns]
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            d.rename_axis("date").reset_index().to_parquet(OUT / f"{t}.parquet", index=False)
        logger.info(f"{min(i + 50, len(todo))}/{len(todo)} downloaded, {len(failed)} failed")
        time.sleep(1)
    manifest = {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "yfinance auto_adjust=True",
                "universe": len(tickers), "on_disk": len(list(OUT.glob("*.parquet"))), "failed": failed}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    print(main())
