"""Pull the research history the LSE vault adds beyond yfinance, for the traded universe.

What was pulled and why (decided on 2026-09-17 after sampling each dataset's
REAL per-symbol depth, which is not what /reference advertises):

  candles_1d         daily OHLCV from 2003. CAUTION: these are UTC-day bars
                     including pre-market and after-hours, not official session
                     bars (see data/lse_vault.py) -- NOT a drop-in for official
                     closes. research/pead_2004_2014.py uses yfinance official
                     bars instead for exactly this reason.
  financial_reports  quarterly and annual income statements back to ~1996, with
                     SEC acceptance timestamps: enough for an earnings-surprise
                     measure that needs no analyst estimates.
  dividends          vault candles are split-adjusted but NOT dividend-adjusted,
                     so total returns need the dividend stream.
  stock_splits       vault DIVIDEND AMOUNTS are NOT split-adjusted even though its
                     prices are (AAPL 2012-08: $2.65 against a $22.14 split-
                     adjusted close), so dividends must be divided by later splits.
  SPY (yfinance)     the vault's SPY history starts 2026-04; the market series
                     back to 2003 comes from yfinance, labelled as such.

Deliberately NOT pulled:
  insider_trades     /reference says 2003 onward, but US history is mostly one
                     year deep (median first row 2025-08 across a 25-name sample;
                     1 in 25 reaches before 2020). Too short to validate an edge.
  options            the /options/chain and /options/flow endpoints start in 2026, but OPRA
                     trade prints from 2014 exist through /export (see data/pull_options_1d.py).

Resumable: a symbol already on disk is skipped, so an interrupted pull simply
reruns. Everything lands under data/lse/ (gitignored: licensed vendor data).

Run: PYTHONPATH=. .venv/bin/python -m data.pull_lse_history
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from loguru import logger

from bot.earnings_watcher import load_validated_universe
from data.ingestion import fetch_ticker_history
from data.lse_vault import Vault, VaultError

OUT = Path(__file__).parent / "lse"
START = "2003-01-01"
INCOME_FIELDS = ["eps", "epsDiluted", "revenue", "netIncome", "weightedAverageShsOut", "weightedAverageShsOutDil"]
# The vault spells share classes with a dot; the universe (yfinance) uses a dash.
# Files are saved under the universe spelling so every consumer can ignore this.
VAULT_SYMBOL = {"BRK-B": "BRK.B", "BF-B": "BF.B"}


def vault_symbol(symbol: str) -> str:
    return VAULT_SYMBOL.get(symbol, symbol)


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)  # atomic: a crash never leaves a half-written file that resume would trust


def pull_candles(vault: Vault, symbol: str) -> dict:
    df = vault.candles(vault_symbol(symbol), "1d", start=START)
    if df.empty:
        return {"rows": 0}
    _write(df, OUT / "candles_1d" / f"{symbol}.parquet")
    return {"rows": len(df), "first": str(df.ts.min().date()), "last": str(df.ts.max().date())}


def pull_income(vault: Vault, symbol: str) -> dict:
    df = vault.reference("financial_reports", symbol=vault_symbol(symbol), report_type="income")
    if df.empty:
        return {"rows": 0}
    parsed = df["data"].map(lambda s: json.loads(s) if isinstance(s, str) else {})
    for field in INCOME_FIELDS:
        # Some rows carry these as strings or blanks; coerce so one odd filing
        # cannot make the whole column unwritable (it did: pyarrow ArrowTypeError).
        df[field] = pd.to_numeric(parsed.map(lambda d, f=field: d.get(f)), errors="coerce")
    df = df.drop(columns=["data"])
    _write(df, OUT / "financial_reports" / f"{symbol}.parquet")
    return {"rows": len(df), "first": str(df["date"].min()), "last": str(df["date"].max())}


def pull_dividends(vault: Vault, symbol: str) -> dict:
    df = vault.reference("dividends", symbol=vault_symbol(symbol))
    if df.empty:
        return {"rows": 0}
    _write(df, OUT / "dividends" / f"{symbol}.parquet")
    return {"rows": len(df), "first": str(df["effective_date"].min()), "last": str(df["effective_date"].max())}


def pull_splits(vault: Vault, symbol: str) -> dict:
    df = vault.reference("stock_splits", symbol=vault_symbol(symbol))
    if df.empty:
        return {"rows": 0}
    _write(df, OUT / "stock_splits" / f"{symbol}.parquet")
    return {"rows": len(df)}


PULLS = {"candles_1d": pull_candles, "financial_reports": pull_income, "dividends": pull_dividends,
         "stock_splits": pull_splits}


def main() -> dict:
    vault = Vault()
    universe = load_validated_universe()
    before = vault.usage()["bytes_used_month"]
    manifest: dict = {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "start": START, "universe": len(universe),
                      "datasets": {}, "not_pulled": {
                          "insider_trades": "US history mostly starts 2025; too short to validate",
                          "options": "starts 2026"}}

    for name, fn in PULLS.items():
        todo = [s for s in universe if not (OUT / name / f"{s}.parquet").exists()]
        logger.info(f"{name}: {len(universe) - len(todo)} already on disk, {len(todo)} to pull")
        results, failures = {}, {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(fn, vault, s): s for s in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                sym = futures[fut]
                try:
                    results[sym] = fut.result()
                except Exception as e:  # one bad symbol must not end the run; every failure lands in the manifest
                    failures[sym] = f"{type(e).__name__}: {str(e)[:200]}"
                if i % 50 == 0:
                    logger.info(f"{name}: {i}/{len(todo)} done, {len(failures)} failed, "
                                f"{vault.bytes_used / 1e6:.0f} MB this run")
        on_disk = sorted(p.stem for p in (OUT / name).glob("*.parquet"))
        manifest["datasets"][name] = {
            "symbols_on_disk": len(on_disk),
            "empty": sorted(s for s, r in results.items() if r.get("rows") == 0),
            "failed": failures,
            "sha256": {s: hashlib.sha256((OUT / name / f"{s}.parquet").read_bytes()).hexdigest() for s in on_disk},
        }
        logger.info(f"{name}: {len(on_disk)} symbols on disk, {len(failures)} failures")

    spy = fetch_ticker_history("SPY", start=START)
    spy["source"] = "yfinance (auto_adjust=True: split AND dividend adjusted)"
    _write(spy, OUT / "market" / "SPY.parquet")
    manifest["market"] = {"SPY": {"source": "yfinance", "rows": len(spy),
                                  "first": str(pd.Timestamp(spy.timestamp.min()).date())}}

    manifest["vault_bytes_used_this_run"] = vault.usage()["bytes_used_month"] - before
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    logger.info(f"done: {manifest['vault_bytes_used_this_run'] / 1e6:.0f} MB of vault allowance used")
    return manifest


if __name__ == "__main__":
    main()
