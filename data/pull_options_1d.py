"""Pull daily per-contract option candles (OPRA trade prints aggregated by the vault)
for a universe fixed with 2014 information only.

Universe rule (fixed 2026-09-18, before any option-derived number was computed):
  current S&P 500 members in data/multiasset/stocks whose LSE options history starts
  on or before 2014-06-30, ranked by mean official daily dollar volume over
  2014-01-01..2014-06-30; one share class per company (GOOG, FOX, NWS dropped);
  the top 100. Current membership is still survivorship-biased; the ranking itself
  uses no post-2014 information.

The vault serves pre-2026 options only through /export, one underlying per job,
five jobs per hour. Each job covers 2014-06-01..2026-09-17 at timeframe 1d:
one row per contract per day with open/high/low/close/volume of trade prints.
No bid/ask quotes exist in this table.

Resumable: an underlying already on disk is skipped. Runs for about 20 hours.
Run: PYTHONPATH=. nohup .venv/bin/python -m data.pull_options_1d &
"""
from __future__ import annotations

import glob
import hashlib
import http.client
import io
import json
import os
import time
from pathlib import Path

import pandas as pd
from loguru import logger

from data.lse_vault import Vault, VaultError

ROOT = Path(__file__).parent
OUT = ROOT / "lse" / "options_1d"
CATALOG = ROOT / "lse_catalog_20260917.json"
START, END = "2014-06-01", "2026-09-17"
N_NAMES = 100
DROP_DUAL_CLASS = {"GOOG", "FOX", "NWS"}


def universe() -> list[str]:
    cat = json.loads(CATALOG.read_text())
    opt = {x["symbol"]: x for x in cat if x["dataset"] == "options"}
    rows = []
    for f in glob.glob(str(ROOT / "multiasset" / "stocks" / "*.parquet")):
        t = os.path.basename(f)[:-8]
        if t in DROP_DUAL_CLASS:
            continue
        o = opt.get(t) or opt.get(t.replace("-", "."))
        if not o or not o["first_tick"] or o["first_tick"] > "2014-06-30":
            continue
        d = pd.read_parquet(f)
        d.index = pd.to_datetime(d["date"])
        w = d.loc["2014-01-01":"2014-06-30"]
        if len(w) < 100:
            continue
        rows.append((t, float((w["close"] * w["volume"]).mean())))
    rows.sort(key=lambda r: -r[1])
    return [t for t, _ in rows[:N_NAMES]]


def wait_for_export_slot(v: Vault) -> None:
    while True:
        u = v.usage()
        if u["exports_this_hour"] < u["exports_cap_hour"]:
            return
        logger.info(f"export cap reached ({u['exports_this_hour']}/{u['exports_cap_hour']}); sleeping 5 min")
        time.sleep(300)


EXPORT_ROW_CAP = 2_500_000  # an export silently stops at this many rows (AAPL ended 2024-09-12)


def export_all(v: Vault, symbol: str, start: str, end: str, have: pd.DataFrame | None = None) -> pd.DataFrame:
    """Chain exports until one comes back under the row cap. Rows are ordered by ts, so the next
    export restarts on the last day seen and the duplicate rows of that day are dropped."""
    parts = [] if have is None else [have]
    cursor = start if have is None else str(have["ts"].max().date())
    while True:
        df = export_one(v, symbol, cursor, end)
        parts.append(df)
        if len(df) < EXPORT_ROW_CAP:
            break
        cursor = str(df["ts"].max().date())
        logger.info(f"{symbol}: export hit the {EXPORT_ROW_CAP:,}-row cap at {cursor}; continuing")
    out = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["ts", "osi"], keep="last")
    return out.sort_values(["ts", "osi"]).reset_index(drop=True)


def export_one(v: Vault, symbol: str, start: str, end: str) -> pd.DataFrame:
    wait_for_export_slot(v)
    job = v._call("POST", "/export", body={"dataset": "options", "symbol": symbol.replace("-", "."),
                                          "timeframe": "1d", "start": start, "end": end})
    jid = job["job_id"]
    for _ in range(360):
        s = v._call("GET", f"/export/{jid}")
        if s["status"] == "ready":
            break
        if s["status"] not in ("queued", "running"):
            raise VaultError(f"{symbol} export {jid} ended {s['status']}: {s.get('error')}")
        time.sleep(10)
    else:
        raise VaultError(f"{symbol} export {jid} did not finish in an hour")
    # A finished job stays downloadable until it expires, so a dropped connection (IncompleteRead
    # took the first pull down at name 23) is retried without spending another export slot.
    for attempt in range(6):
        try:
            raw = v._call("GET", f"/export/{jid}/download", raw=True)
            if hashlib.sha256(raw).hexdigest() == s["sha256"]:
                return pd.read_parquet(io.BytesIO(raw))
            logger.warning(f"{symbol} export {jid}: sha256 mismatch on attempt {attempt + 1}")
        except (http.client.HTTPException, OSError) as e:
            logger.warning(f"{symbol} export {jid}: download failed ({type(e).__name__}); retry {attempt + 1}/6")
        time.sleep(15 * (attempt + 1))
    raise VaultError(f"{symbol} export {jid}: download failed after retries")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    names = universe()
    (OUT / "universe.json").write_text(json.dumps({"rule": __doc__.split("Universe rule")[1].split("The vault")[0].strip(),
                                                    "names": names}, indent=1))
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    v = Vault()
    for i, t in enumerate(names):
        path = OUT / f"{t}.parquet"
        have = None
        if path.exists():
            done = t in manifest and "error" not in manifest[t]
            if done:  # finished (possibly over several chained exports): never re-export it
                continue
            have = pd.read_parquet(path)
            if len(have) != EXPORT_ROW_CAP:
                continue
            logger.info(f"{t}: file on disk stopped at the row cap; resuming from {have['ts'].max().date()}")
        try:
            df = export_all(v, t, START, END, have)
        except Exception as e:  # one bad name must not stop the other 99; rerun to retry it
            logger.error(f"{t}: {type(e).__name__}: {e}")
            manifest[t] = {"error": str(e)[:300]}
            manifest_path.write_text(json.dumps(manifest, indent=1))
            continue
        tmp = path.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
        manifest[t] = {"rows": len(df), "first": str(df["ts"].min()), "last": str(df["ts"].max()),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        manifest_path.write_text(json.dumps(manifest, indent=1))
        logger.info(f"[{i + 1}/{len(names)}] {t}: {len(df):,} rows {manifest[t]['first'][:10]}..{manifest[t]['last'][:10]}")


if __name__ == "__main__":
    main()
