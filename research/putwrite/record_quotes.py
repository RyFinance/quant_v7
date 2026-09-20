"""Record live bid/ask on short-dated SPY/QQQ/IWM puts near the close.

The put-writing experiment (research/putwrite/PLAN.md) assumes half-spreads of $0.01 (SPY, QQQ) and
$0.02 (IWM). Neither the historical OPRA prints nor the LSE feed carry quotes, so this records them:
one snapshot per trading day at about 15:45 ET of every put expiring today (0DTE) or on the next
listed expiry, with strikes from 94% to 100% of spot. It is also the data feed a forward paper test
would use. Quotes come from yfinance and may be delayed by up to 15 minutes; `quote_ts` records
when the snapshot was taken, `lastTradeDate` when each contract last traded.

Run: PYTHONPATH=. .venv/bin/python -m research.putwrite.record_quotes
Scheduled by ~/Library/LaunchAgents/com.rytty.quant_v7.option_quotes.plist (weekdays 12:45 local).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path(__file__).resolve().parents[2] / "data" / "option_quotes"
NAMES = ["SPY", "QQQ", "IWM"]


def snapshot() -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    today = now.astimezone().date().isoformat()
    frames = []
    for t in NAMES:
        tk = yf.Ticker(t)
        spot = float(tk.fast_info["last_price"])
        expiries = [e for e in tk.options if e >= today][:2]
        for e in expiries:
            p = tk.option_chain(e).puts
            p = p[(p["strike"] >= 0.94 * spot) & (p["strike"] <= spot)].copy()
            p["underlying"], p["spot"], p["expiry"], p["quote_ts"] = t, spot, e, now
            frames.append(p)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = snapshot()
    if df.empty:
        print("no quotes")
        return
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    df.to_parquet(OUT / f"{stamp}.parquet", index=False)
    live = df[(df["bid"] > 0) & (df["ask"] > 0)]
    half = ((live["ask"] - live["bid"]) / 2).groupby(live["underlying"]).median()
    print(stamp, len(df), "rows; median half-spread:", half.round(4).to_dict())


if __name__ == "__main__":
    main()
