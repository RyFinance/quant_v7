"""Crypto trend (PLAN_CRYPTO.md): BTC and ETH, development through 2021, hold-out 2022-01-01 on.

    PYTHONPATH=. .venv/bin/python -m research.multiasset.crypto dev
    PYTHONPATH=. .venv/bin/python -m research.multiasset.crypto holdout   # once, after registering
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.multiasset import evaluate, panel, sleeves

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/multiasset/crypto"
OUT = ROOT / "reports/multiasset/crypto"
DEV_END = pd.Timestamp("2021-12-31")
HOLDOUT_START = pd.Timestamp("2022-01-01")
HOLDOUT_END = pd.Timestamp("2026-09-17")
PREREG = ROOT / "research/multiasset/PREREGISTRATION_crypto_holdout.md"
COST = 10e-4
BORROW = 0.03
ANN = 365


def unlocked() -> bool:
    if not PREREG.exists():
        return False
    digest = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    rel = str(PREREG.relative_to(ROOT))
    return any(json.loads(l).get("file") == rel and json.loads(l).get("sha256") == digest
               for l in panel.REGISTRY.read_text().splitlines())


def resolve_end(end) -> pd.Timestamp:
    end = pd.Timestamp(end) if end is not None else DEV_END
    if end > DEV_END and not unlocked():
        raise panel.HoldoutLocked(f"crypto dates after {DEV_END.date()} need {PREREG.name} registered")
    return min(end, HOLDOUT_END)


def _vault_close(sym: str) -> pd.Series:
    d = pd.read_parquet(DATA / f"{sym}.parquet")
    s = pd.Series(d["close"].to_numpy(float), index=pd.to_datetime(d["ts"]).dt.normalize()).sort_index()
    return s[~s.index.duplicated(keep="last")]


def returns(end=None) -> pd.DataFrame:
    """Daily UTC close-to-close returns. BTC before the vault's 2017-08-17 start comes from
    yfinance BTC-USD (same UTC-day convention); the two are spliced as returns, not prices."""
    end = resolve_end(end)
    btc_v, eth_v = _vault_close("BTCUSD"), _vault_close("ETHUSD")
    y = pd.read_parquet(DATA / "yf_BTC-USD.parquet")
    btc_y = pd.Series(y["close"].to_numpy(float), index=pd.to_datetime(y["date"]).dt.normalize()).sort_index()
    splice = btc_v.index[0]
    btc_r = pd.concat([btc_y[btc_y.index < splice].pct_change(),
                       pd.Series([btc_v.iloc[0] / btc_y[btc_y.index < splice].iloc[-1] - 1], index=[splice]),
                       btc_v.pct_change().iloc[1:]])
    cal = pd.date_range(btc_r.index[0], end, freq="D")
    out = pd.DataFrame({"BTC": btc_r.reindex(cal), "ETH": eth_v.pct_change().reindex(cal)})
    return out


def risk_free_daily(index: pd.DatetimeIndex) -> pd.Series:
    irx = panel._yf_close("rates", "IRX") / 100.0
    return (irx.reindex(index.union(irx.index)).ffill().reindex(index).shift(1) / 360.0).fillna(0.0)


def _run(signal_dates: pd.DatetimeIndex, signal: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    rf = risk_free_daily(rets.index)
    excess = rets.sub(rf, axis=0)
    vol = np.sqrt((rets ** 2).ewm(com=60, min_periods=60).mean() * ANN)
    raw = (signal * 0.40 / vol).loc[signal_dates]
    n = raw.notna().sum(axis=1).replace(0, np.nan)
    targets = raw.div(n, axis=0).fillna(0.0)
    w = targets.reindex(rets.index).ffill()
    return sleeves.run_weights(w, excess, COST, BORROW)


def trailing(rets: pd.DataFrame, n: int) -> pd.DataFrame:
    return np.exp(np.log1p(rets).rolling(n, min_periods=n).sum()) - 1


def tsmom_1w(end=None) -> pd.DataFrame:
    r = returns(end)
    sundays = r.index[r.index.dayofweek == 6]
    return _run(sundays, np.sign(trailing(r, 7)), r)


def _multi_signal(r: pd.DataFrame) -> pd.DataFrame:
    sig = (np.sign(trailing(r, 30)) + np.sign(trailing(r, 91)) + np.sign(trailing(r, 365))) / 3
    return sig.where(trailing(r, 365).notna())


def tsmom_multi(end=None) -> pd.DataFrame:
    r = returns(end)
    return _run(sleeves.month_ends(r.index), _multi_signal(r), r)


def trend_long_only(end=None) -> pd.DataFrame:
    r = returns(end)
    return _run(sleeves.month_ends(r.index), _multi_signal(r).clip(lower=0), r)


CANDIDATES = {"crypto_tsmom_1w": tsmom_1w, "crypto_tsmom_multi": tsmom_multi,
              "crypto_trend_long_only": trend_long_only}


def stats(x: pd.Series, btc: pd.Series, rf: pd.Series) -> dict:
    x = x.dropna()
    years = len(x) / ANN
    total = (1 + x + rf.reindex(x.index).fillna(0)).cumprod()
    wealth = (1 + x).cumprod()
    b = btc.reindex(x.index)
    ok = b.notna()
    beta = float(np.cov(x[ok], b[ok])[0, 1] / b[ok].var())
    return {"start": str(x.index[0].date()), "end": str(x.index[-1].date()), "years": round(years, 2),
            "sharpe": round(float(x.mean() / x.std() * np.sqrt(ANN)), 3),
            "ann_excess": round(float(x.mean() * ANN), 4), "vol": round(float(x.std() * np.sqrt(ANN)), 4),
            "cagr_total": round(float(total.iloc[-1] ** (1 / years) - 1), 4),
            "max_dd": round(float((wealth / wealth.cummax() - 1).min()), 4),
            "hac_t": round(evaluate.hac_t(x), 2), "beta_btc": round(beta, 3)}


def code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def dev() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    r = returns(DEV_END)
    rf = risk_free_daily(r.index)
    btc = r["BTC"] - rf
    res = {}
    for name, fn in CANDIDATES.items():
        s = stats(evaluate.active(fn(DEV_END)), btc, rf)
        s["passes"] = s["sharpe"] >= 0.30 and s["years"] >= 3
        res[name] = s
        print(name, json.dumps(s))
        with open(OUT / "dev_trials.jsonl", "a") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sleeve": name,
                                "code_sha256": code_hash(), "stats": s}) + "\n")
    passing = [k for k, v in res.items() if v["passes"]]
    chosen = max(passing, key=lambda k: res[k]["sharpe"]) if passing else None
    res["btc_buy_hold"] = stats(btc.dropna(), btc, rf)
    summary = {"chosen_for_holdout": chosen, "candidates": res, "code_sha256": code_hash()}
    (OUT / "dev_results.json").write_text(json.dumps(summary, indent=2))
    print("chosen:", chosen, "| BTC buy-hold dev:", json.dumps(res["btc_buy_hold"]))
    return summary


def holdout() -> dict:
    if not unlocked():
        raise panel.HoldoutLocked(f"register {PREREG.name} first")
    if code_hash() not in PREREG.read_text():
        raise RuntimeError("crypto.py changed since the hold-out pre-registration")
    chosen = json.loads((OUT / "dev_results.json").read_text())["chosen_for_holdout"]
    r = returns(HOLDOUT_END)
    rf = risk_free_daily(r.index)
    btc = r["BTC"] - rf
    cut = lambda s: s[(s.index >= HOLDOUT_START) & (s.index <= HOLDOUT_END)]
    all_c = {k: cut(evaluate.active(fn(HOLDOUT_END))) for k, fn in CANDIDATES.items()}
    primary = stats(all_c[chosen], btc, rf)
    out = {"chosen": chosen, "primary": primary, "passed": primary["hac_t"] >= 2.0,
           "all_candidates": {k: stats(v, btc, rf) for k, v in all_c.items()},
           "btc_buy_hold": stats(cut(btc), btc, rf)}
    # descriptive: the chosen sleeve at 10% vol, summed onto NYSE sessions, blended 50/50 with the
    # multi-asset book's recorded hold-out returns
    full = evaluate.active(CANDIDATES[chosen](HOLDOUT_END))
    vol = full.rolling(365, min_periods=180).std() * np.sqrt(ANN)
    scaled = (full * (0.10 / vol).clip(upper=4.0).shift(2)).dropna()
    book = pd.read_csv(evaluate.OUT / "holdout" / "holdout_returns.csv", index_col=0, parse_dates=True)["book"]
    session = book.index.searchsorted(scaled.index)           # crypto day -> the NYSE session it rolls into
    ok = session < len(book)
    crypto_sessions = np.log1p(scaled[ok]).groupby(book.index[session[ok]]).sum().pipe(np.expm1)
    blend = (0.5 * book + 0.5 * crypto_sessions.reindex(book.index).fillna(0.0)).dropna()
    rf_s = panel.risk_free(HOLDOUT_END)
    spy = panel.etf_returns(HOLDOUT_END)["SPY"] - rf_s
    out["descriptive_blend_with_multiasset_book"] = evaluate.stats(evaluate.vol_scale(blend, 0.10), rf_s, spy)
    out["code_sha256"] = code_hash()
    (OUT / "holdout_results.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    {"dev": dev, "holdout": holdout}[sys.argv[1]]()
