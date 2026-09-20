"""Compute F1/F2 at every month-end signal date for all names; writes reports/fundamentals/signals.parquet.
Signals only (no returns). Run: PYTHONPATH=. .venv/bin/python -m research.fundamentals.build_signals"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from research.fundamentals import signals as sg

OUT = sg.ROOT / "reports" / "fundamentals"


def names() -> list[str]:
    fin = {p.stem for p in sg.FIN_DIR.glob("*.parquet")}
    px = {p.stem for p in sg.STOCK_DIR.glob("*.parquet")}
    return sorted(fin & px)


def _one(t):
    cal = sg.trading_calendar()
    return t, sg.ticker_signals(t, sg.month_end_dates(cal), cal)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=6) as ex:
        res = dict(ex.map(_one, names(), chunksize=8))
    panel = pd.concat({t: df for t, df in res.items()}, names=["ticker", "date"]).reset_index()
    panel.to_parquet(OUT / "signals.parquet")
    print(panel.shape)


if __name__ == "__main__":
    main()
