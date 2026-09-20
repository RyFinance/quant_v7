"""yfinance official daily session bars for the insider universe, and the aligned price panel.

  PYTHONPATH=. .venv/bin/python -m research.insider.prices     # pulls every ticker in cik_ticker.parquet

Stored per ticker in data/sec_insider/prices/{T}.parquet: date, open, high, low, close (split-adjusted,
not dividend-adjusted), adj_close, volume (split-adjusted), splits (ratio on the ex-date, 0 = none).

Derived series (PLAN "Prices"):
  open_tr, close_tr : total-return (dividend- and split-adjusted) prices for portfolio returns
  raw_close         : split-adjusted close x product of split ratios strictly AFTER the date, i.e. the
                      price that actually traded that day; used only by the $5 filter
  dollar_vol        : close x volume (both split-adjusted) = raw dollar volume
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PX_DIR = ROOT / "data" / "sec_insider" / "prices"
START = "2005-10-01"
A1_LAST_FILING = pd.Timestamp("2025-01-01")


def available_tickers() -> list[str]:
    return sorted(p.stem for p in PX_DIR.glob("*.parquet") if not p.stem.startswith("_")) if PX_DIR.exists() else []


def _frame(raw: pd.DataFrame) -> pd.DataFrame | None:
    need = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    if raw is None or raw.empty or any(c not in raw.columns for c in need):
        return None
    raw = raw.dropna(subset=["Close"])
    if raw.empty:
        return None
    idx = pd.to_datetime(raw.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    splits = raw["Stock Splits"].fillna(0).to_numpy() if "Stock Splits" in raw.columns else np.zeros(len(raw))
    return pd.DataFrame({"date": idx.normalize(), "open": raw["Open"].to_numpy(), "high": raw["High"].to_numpy(),
                         "low": raw["Low"].to_numpy(), "close": raw["Close"].to_numpy(),
                         "adj_close": raw["Adj Close"].to_numpy(), "volume": raw["Volume"].to_numpy(),
                         "splits": splits})


def universe_tickers() -> list[str]:
    """PLAN_AMENDMENT_1 A1: tickers of issuers with a Form 3/4/5 filed on or after 2025-01-01."""
    ct = pd.read_parquet(ROOT / "data" / "sec_insider" / "cik_ticker.parquet")
    return sorted(ct.loc[ct["last_filing"] >= A1_LAST_FILING, "ticker"].unique())


def pull(tickers: list[str], start: str = START, workers: int = 4, min_interval: float = 0.35) -> dict:
    """One Ticker.history call per ticker, request starts spaced by min_interval across threads,
    exponential back-off on rate limiting. Resumable: stored tickers and known-empty ones are skipped."""
    import logging
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    PX_DIR.mkdir(parents=True, exist_ok=True)
    log_path = PX_DIR / "_pull_status.json"
    status = json.loads(log_path.read_text()) if log_path.exists() else {}
    todo = [t for t in tickers if not (PX_DIR / f"{t}.parquet").exists() and status.get(t) != "empty"]
    lock = threading.Lock()
    nxt = [0.0]

    def slot():
        with lock:
            now = time.monotonic()
            wait = nxt[0] - now
            nxt[0] = max(now, nxt[0]) + min_interval
        if wait > 0:
            time.sleep(wait)

    def one(t):
        for attempt in range(6):
            slot()
            try:
                h = yf.Ticker(t).history(start=start, auto_adjust=False, actions=True)
            except YFRateLimitError:
                time.sleep(min(600, 30 * 2 ** attempt))
                continue
            except Exception as e:  # network hiccup or a malformed symbol
                if attempt < 2:
                    time.sleep(5)
                    continue
                return t, f"error:{type(e).__name__}"
            f = _frame(h)
            if f is None:
                return t, "empty"
            f.to_parquet(PX_DIR / f"{t}.parquet", index=False)
            return t, "ok"
        return t, "rate_limited"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, st in ex.map(one, todo):
            status[t] = st
            done += 1
            if done % 200 == 0 or done == len(todo):
                log_path.write_text(json.dumps(status))
                counts = pd.Series(status).value_counts().to_dict()
                print(f"{done}/{len(todo)} {counts}", flush=True)
    log_path.write_text(json.dumps(status))
    return pd.Series(status).value_counts().to_dict()


def raw_close_series(t: str, upto: pd.Timestamp) -> pd.Series | None:
    """Raw close for one ticker through `upto` (for the A2 price check)."""
    p = PX_DIR / f"{t}.parquet"
    if not p.exists():
        return None
    return derive(pd.read_parquet(p), upto=upto)["raw_close"].dropna()


OPEN_FAR = 2.0     # PLAN_AMENDMENT_2 B1(b)
OPEN_RANGE_TOL = 0.01  # B1(a)
CLOSE_SPIKE = 3.0  # B2


def derive(f: pd.DataFrame, upto: pd.Timestamp | None = None) -> pd.DataFrame:
    """Per-ticker derived columns (see module docstring), truncated at `upto`.

    raw_close / dollar_vol are as reported (the universe filter and cost tiers use them). open_tr /
    close_tr are cleaned per PLAN_AMENDMENT_2: close spikes (B2, judged only on data <= upto) are set
    missing, then bad opens (B1) are set missing. The split factor uses the full history because it
    only rebuilds the price that actually traded on the day."""
    f = f.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
    ratio = f["splits"].where(f["splits"] > 0, 1.0).astype(float)
    after = ratio[::-1].cumprod()[::-1] / ratio  # product of ratios strictly after each date
    if upto is not None:
        keep = f.index <= upto
        f, after = f.loc[keep], after.loc[keep]
    c = f["close"].where(f["close"] > 0)
    factor = (f["adj_close"] / c)
    pc, nc = c.shift(1), c.shift(-1)
    spike = ((c > CLOSE_SPIKE * pc) & (c > CLOSE_SPIKE * nc)) | ((c < pc / CLOSE_SPIKE) & (c < nc / CLOSE_SPIKE))
    c_ref = c.where(~spike, pc)
    o = f["open"]
    hi, lo = f["high"], f["low"]
    out_of_range = (hi > 0) & (lo > 0) & ((o > hi * (1 + OPEN_RANGE_TOL)) | (o < lo * (1 - OPEN_RANGE_TOL)))
    far = (((o / pc) > OPEN_FAR) | ((o / pc) < 1 / OPEN_FAR)) & (((o / c_ref) > OPEN_FAR) | ((o / c_ref) < 1 / OPEN_FAR))
    bad_open = out_of_range | far | ~(o > 0)
    return pd.DataFrame({
        "open_tr": (o * factor).mask(bad_open), "close_tr": f["adj_close"].where(c.notna()).mask(spike),
        "raw_close": f["close"] * after, "dollar_vol": f["close"] * f["volume"],
    })


def bar_quality() -> dict:
    """How often amendment 2 fires across every pulled ticker (no signals, no returns)."""
    out = {"tickers": 0, "bars": 0, "bad_opens_B1": 0, "close_spikes_B2": 0, "tickers_affected": 0}
    for t in available_tickers():
        f = pd.read_parquet(PX_DIR / f"{t}.parquet")
        d = derive(f)
        n_open = int((d["open_tr"].isna() & (f.set_index("date")["open"].reindex(d.index) > 0)).sum())
        n_spike = int((d["close_tr"].isna() & d["raw_close"].notna()).sum())
        out["tickers"] += 1
        out["bars"] += len(d)
        out["bad_opens_B1"] += n_open
        out["close_spikes_B2"] += n_spike
        out["tickers_affected"] += int(n_open + n_spike > 0)
    return out


def load_panel(tickers: list[str], start: pd.Timestamp, upto: pd.Timestamp,
               calendar: pd.DatetimeIndex | None = None) -> dict[str, pd.DataFrame]:
    """Wide panels (dates x tickers) truncated at `upto`; callers enforce the validation lock."""
    cols = {k: {} for k in ("open_tr", "close_tr", "raw_close", "dollar_vol")}
    for t in tickers:
        p = PX_DIR / f"{t}.parquet"
        if not p.exists():
            continue
        d = derive(pd.read_parquet(p), upto=upto)
        d = d.loc[d.index >= start]
        if d.empty:
            continue
        for k in cols:
            cols[k][t] = d[k]
    out = {k: pd.DataFrame(v) for k, v in cols.items()}
    if calendar is not None:
        out = {k: v.reindex(calendar) for k, v in out.items()}
    return out


if __name__ == "__main__":
    print(pull(universe_tickers()))
    sys.exit(0)
