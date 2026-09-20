"""Pull the multi-asset research panel: everything outside US single stocks.

Every earlier study in this project used one universe (US large caps, 2015 on).
This panel is for sleeves that share none of that data:

  yfinance (official session bars, auto_adjust=True, split AND dividend adjusted)
    etf/      liquid ETFs across equity indices, government and credit bonds,
              commodities, currencies and real estate, for cross-asset trend
    vol/      ^VIX, ^VIX3M, VIXY, SVXY, for the VIX futures basis sleeve
    rates/    ^IRX, the 13-week T-bill, as the daily risk-free rate
    fx_yf/    G10 spot from 2003, only for 5-year FX value signals before 2014
  LSE vault (licensed: gitignored, never redistributed)
    fx/       G10 spot vs USD, daily. FX trades around the clock, so the vault's
              UTC-day bar is a legitimate daily bar here (unlike US stocks).
    policy/   G10 central bank policy rates, for FX carry
    cpi/      G10 CPI index levels, for the real exchange rate in FX value
    yields/   10-year government yields, for bond carry
    futures/  ES and NQ 30-minute bars from 2016, for intraday momentum
    crypto/   BTC and ETH daily

Resumable: files already on disk are skipped. Run:
    PYTHONPATH=. .venv/bin/python -m data.pull_multiasset
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

from data.lse_vault import Vault

OUT = Path(__file__).parent / "multiasset"
START = "2003-01-01"

ETFS = {
    "equity": ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "EWG", "EWU", "EWC", "EWA", "EWZ", "FXI", "EWY", "EWT"],
    "bond": ["SHY", "IEF", "TLT", "TIP", "LQD", "HYG", "EMB", "BWX"],
    "commodity": ["GLD", "SLV", "DBC", "USO", "UNG", "DBA", "DBB"],
    "currency": ["FXE", "FXY", "FXB", "FXA", "FXC", "FXF", "UUP"],
    "real_estate": ["VNQ"],
}
VOL = ["^VIX", "^VIX3M", "VIXY", "SVXY"]
RATES = ["^IRX"]

# Quote currency per pair; every series is stored as USD per unit of foreign currency.
FX_PAIRS = {"EUR": "EUR/USD", "GBP": "GBP/USD", "AUD": "AUD/USD", "NZD": "NZD/USD",
            "JPY": "USD/JPY", "CHF": "USD/CHF", "CAD": "USD/CAD", "SEK": "USD/SEK", "NOK": "USD/NOK"}
POLICY = {"USD": "fdtr", "EUR": "eurr002w", "GBP": "ukbrbase", "JPY": "bojdtr", "CHF": "szlttr",
          "AUD": "rbatctr", "NZD": "nzocrs", "CAD": "cclr", "SEK": "swrratei", "NOK": "nobrdep"}
YIELDS = ["US10Y", "DE10Y", "GB10Y", "JP10Y", "CA10Y", "AU10Y", "FR10Y", "IT10Y", "ES10Y", "CH10Y",
          "SE10Y", "NO10Y", "NZ10Y"]
FUTURES = ["ES.F", "NQ.F"]
# CPI index levels (monthly; AU and NZ quarterly), for the real exchange rate in FX value
CPI = {"USD": "unitedstaconpriindcp", "EUR": "euroareaconpriindcp", "GBP": "unitedkinconpriindcp",
       "JPY": "japanconpriindcpi", "CHF": "switzerlanconpriindc", "AUD": "ausquacpi",
       "NZD": "newzealanconpriindcp", "CAD": "canadaconpriindcpi", "SEK": "swedenconpriindcpi",
       "NOK": "norwayconpriindcpi"}
# yfinance spot FX, only to reach back before the vault's 2009 start for 5-year value signals
YF_FX = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "AUD": "AUDUSD=X", "NZD": "NZDUSD=X", "JPY": "JPY=X",
         "CHF": "CHF=X", "CAD": "CAD=X", "SEK": "SEK=X", "NOK": "NOK=X"}
CRYPTO = ["BTC/USD", "ETH/USD"]


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def _fname(symbol: str) -> str:
    return symbol.replace("/", "").replace("^", "").replace(".", "_")


def pull_yf(symbol: str, folder: str) -> dict:
    path = OUT / folder / f"{_fname(symbol)}.parquet"
    if path.exists():
        return {"skipped": True}
    df = yf.download(symbol, start=START, interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower).rename_axis("date").reset_index()
    if df.empty:
        raise RuntimeError(f"{symbol}: yfinance returned nothing")
    df["source"] = "yfinance auto_adjust=True"
    _write(df, path)
    return {"rows": len(df), "first": str(df.date.min().date()), "last": str(df.date.max().date())}


def pull_vault_candles(vault: Vault, symbol: str, folder: str, timeframe: str, start: str) -> dict:
    path = OUT / folder / f"{_fname(symbol)}.parquet"
    if path.exists():
        return {"skipped": True}
    df = vault.candles(symbol, timeframe, start=start)
    if df.empty:
        raise RuntimeError(f"{symbol}: vault returned nothing")
    _write(df, path)
    return {"rows": len(df), "first": str(df.ts.min()), "last": str(df.ts.max())}


def pull_vault_series(vault: Vault, symbol: str, folder: str) -> dict:
    path = OUT / folder / f"{_fname(symbol)}.parquet"
    if path.exists():
        return {"skipped": True}
    df = vault.series(symbol, start="1995-01-01")
    if df.empty:
        raise RuntimeError(f"{symbol}: vault returned nothing")
    _write(df, path)
    return {"rows": len(df), "first": str(df.date.min().date()), "last": str(df.date.max().date())}


def main() -> dict:
    manifest: dict = {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "items": {}, "failed": {}}
    previous = json.loads((OUT / "manifest.json").read_text())["items"] if (OUT / "manifest.json").exists() else {}

    def attempt(key, fn, *args):
        try:
            result = fn(*args)
            # a skipped file keeps the details recorded when it was actually pulled
            manifest["items"][key] = previous.get(key, result) if result.get("skipped") else result
        except Exception as e:  # one bad symbol must not end the run; failures land in the manifest
            manifest["failed"][key] = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning(f"{key}: {manifest['failed'][key]}")

    for cls, symbols in ETFS.items():
        for s in symbols:
            attempt(f"etf/{s}", pull_yf, s, "etf")
    for s in VOL:
        attempt(f"vol/{s}", pull_yf, s, "vol")
    for s in RATES:
        attempt(f"rates/{s}", pull_yf, s, "rates")
    for s in YF_FX.values():
        attempt(f"fx_yf/{s}", pull_yf, s, "fx_yf")
    logger.info("yfinance done")

    vault = Vault()
    before = vault.usage()["bytes_used_month"]
    for ccy, pair in FX_PAIRS.items():
        attempt(f"fx/{pair}", pull_vault_candles, vault, pair, "fx", "1d", "2009-01-01")
    for ccy, sym in POLICY.items():
        attempt(f"policy/{sym}", pull_vault_series, vault, sym, "policy")
    for sym in YIELDS:
        attempt(f"yields/{sym}", pull_vault_series, vault, sym, "yields")
    for sym in CPI.values():
        attempt(f"cpi/{sym}", pull_vault_series, vault, sym, "cpi")
    for sym in CRYPTO:
        attempt(f"crypto/{sym}", pull_vault_candles, vault, sym, "crypto", "1d", "2017-01-01")
    for sym in FUTURES:
        attempt(f"futures/{sym}", pull_vault_candles, vault, sym, "futures", "30m", "2016-01-01")
    manifest["vault_bytes_used_this_run"] = vault.usage()["bytes_used_month"] - before
    manifest["etf_classes"] = ETFS
    manifest["fx_pairs"] = FX_PAIRS
    manifest["policy_rates"] = POLICY
    manifest["cpi"] = CPI
    manifest["yf_fx"] = YF_FX
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    logger.info(f"done: {len(manifest['items'])} ok, {len(manifest['failed'])} failed")
    return manifest


if __name__ == "__main__":
    main()
