"""Option daily bars for SPY, QQQ and IWM plus their raw/adjusted closes (research/putwrite/PLAN.md).

Waits until data/pull_options_1d.py has finished so the two never race for the five hourly
export slots, then chains capped exports exactly as that puller does.
Run: PYTHONPATH=. nohup .venv/bin/python -m research.putwrite.pull &
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

from data.lse_vault import Vault
from data.pull_options_1d import END, START, export_all

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "lse" / "options_etf_1d"
SPOT = ROOT / "data" / "stocks_raw_2014"
NAMES = ["SPY", "QQQ", "IWM"]


def main_pull_running() -> bool:
    return subprocess.run(["pgrep", "-f", "data.pull_options_1d"], capture_output=True).returncode == 0


def pull_spot() -> None:
    raw = yf.download(NAMES, start="2014-05-01", end="2026-09-18", auto_adjust=False, actions=True,
                      progress=False, group_by="ticker")
    for t in NAMES:
        d = raw[t].dropna(how="all").copy()
        d.index.name = "date"
        d.reset_index().to_parquet(SPOT / f"{t}.parquet", index=False)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pull_spot()
    while main_pull_running():
        time.sleep(300)
    v = Vault()
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for t in NAMES:
        path = OUT / f"{t}.parquet"
        if path.exists():
            continue
        try:
            df = export_all(v, t, START, END)
        except Exception as e:
            logger.error(f"{t}: {type(e).__name__}: {e}")
            continue
        df.to_parquet(path, index=False)
        manifest[t] = {"rows": len(df), "first": str(df["ts"].min()), "last": str(df["ts"].max()),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        manifest_path.write_text(json.dumps(manifest, indent=1))
        logger.info(f"{t}: {len(df):,} rows")


if __name__ == "__main__":
    main()
