"""Development / validation runs for research/putwrite/PLAN.md.

  PYTHONPATH=. .venv/bin/python -m research.putwrite.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.putwrite.evaluate validation   # needs the registered unlock
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.options_signals.signals import french_daily, implied_vol

ROOT = Path(__file__).resolve().parents[2]
OPT = ROOT / "data" / "lse" / "options_etf_1d"
SPOT = ROOT / "data" / "stocks_raw_2014"
OUT = ROOT / "reports" / "putwrite"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/putwrite/VALIDATION_UNLOCK.md"

DEV = (pd.Timestamp("2014-06-01"), pd.Timestamp("2019-12-31"))
VAL = (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-09-17"))
Z, RV_DAYS, MIN_PREMIUM = 1.0, 21, 0.05
HALF_SPREAD = {"SPY": 0.01, "QQQ": 0.01, "IWM": 0.02}
COSTS = {"base": {"hs_mult": 1.0, "commission": 0.65}, "stress": {"hs_mult": 2.0, "commission": 1.00}}
CANDIDATES = ["P1_spy", "P2_spy_vrp", "P3_etf3"]
DEV_GATE, VAL_GATE, ALPHA, BLOCK, DRAWS = 0.5, 0.75, 0.05 / 3, 21, 5000


def validation_unlocked() -> bool:
    path = ROOT / UNLOCK
    if not path.exists():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return any(json.loads(line).get("file") == UNLOCK and json.loads(line).get("sha256") == digest
               for line in PREREG.read_text().splitlines())


def load_spot(t: str, upto: pd.Timestamp) -> pd.DataFrame:
    d = pd.read_parquet(SPOT / f"{t}.parquet")
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    return d.set_index("date").sort_index().loc[:upto]


def load_puts(t: str, upto: pd.Timestamp) -> pd.DataFrame:
    d = pd.read_parquet(OPT / f"{t}.parquet", columns=["ts", "expiry", "opt_type", "strike", "close", "volume"])
    d["date"] = d["ts"].dt.tz_convert(None).dt.normalize()
    d = d[(d["date"] <= upto) & d["opt_type"].str.upper().str.startswith("P") & (d["volume"] >= 1)]
    d["expiry"] = pd.to_datetime(d["expiry"])
    return d[["date", "expiry", "strike", "close"]].reset_index(drop=True)


def trades(t: str, start: pd.Timestamp, end: pd.Timestamp, calendar: pd.DatetimeIndex, rates: pd.Series,
           cost: dict) -> pd.DataFrame:
    """One row per trade: entry date t, settle date t+1, strike, premium, payoff, net excess return."""
    settle_upto = calendar[calendar > end][0] if (calendar > end).any() else end
    spot = load_spot(t, settle_upto).reindex(calendar)
    puts = load_puts(t, end)
    rv = np.log(spot["Adj Close"]).diff().rolling(RV_DAYS).std() * np.sqrt(252)
    hs = HALF_SPREAD[t] * cost["hs_mult"]
    comm = cost["commission"] / 100.0
    by_day = {d: g for d, g in puts.groupby("date")}
    rows = []
    for i, d in enumerate(calendar[:-1]):
        if d < start or d > end:
            continue
        d1 = calendar[i + 1]
        g = by_day.get(d)
        S, S1, sig = spot.at[d, "Close"], spot.at[d1, "Close"], rv.get(d)
        if g is None or not np.isfinite(sig) or not np.isfinite(S) or not np.isfinite(S1):
            continue
        g = g[g["expiry"] == d1]
        if g.empty:
            continue
        kstar = S * np.exp(-Z * sig * np.sqrt(1 / 252))
        g = g.assign(dist=(g["strike"] - kstar).abs()).sort_values(["dist", "strike"])
        pick = g.iloc[0]
        if pick["close"] < MIN_PREMIUM:
            continue
        K, px = float(pick["strike"]), float(pick["close"])
        iv = float(implied_vol(np.array([px]), np.array([S]), np.array([K]), np.array([1 / 252]),
                               np.array([rates.get(d, 0.0)]), np.array([False]))[0])
        payoff = max(K - S1, 0.0)
        exit_cost = (hs + comm) if payoff > 0 else 0.0
        net = (px - hs - comm - payoff - exit_cost) / K
        gross = (px - payoff) / K
        rows.append({"entry": d, "settle": d1, "S": S, "S1": S1, "K": K, "premium": px, "iv": iv, "rv": sig,
                     "payoff": payoff, "gross": gross, "net": net})
    return pd.DataFrame(rows)


def daily_series(tr: pd.DataFrame, calendar: pd.DatetimeIndex, start, end, col="net") -> pd.Series:
    days = calendar[(calendar > start) & (calendar <= end + pd.Timedelta(days=7))]
    s = pd.Series(0.0, index=days)
    if not tr.empty:
        s = s.add(tr.set_index("settle")[col].groupby(level=0).sum(), fill_value=0.0).reindex(days, fill_value=0.0)
    return s


def block_bootstrap_p(x: np.ndarray, block=BLOCK, draws=DRAWS, seed=20260918) -> float:
    n = len(x)
    c = x - x.mean()
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(draws, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)[:, :n] % n
    return float((np.sum(c[idx].mean(axis=1) >= x.mean()) + 1) / (draws + 1))


def max_dd(r: pd.Series) -> float:
    nav = (1 + r).cumprod()
    return float((nav / nav.cummax() - 1).min())


def summarize(r: pd.Series, gross: pd.Series, tr: pd.DataFrame) -> dict:
    years = len(r) / 252
    return {
        "days": int(len(r)), "trades": int(len(tr)),
        "sharpe_net": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else float("nan"),
        "sharpe_gross": float(gross.mean() / gross.std() * np.sqrt(252)) if gross.std() > 0 else float("nan"),
        "ann_mean_net": float(r.mean() * 252), "ann_vol": float(r.std() * np.sqrt(252)),
        "excess_cagr": float((1 + r).prod() ** (1 / years) - 1), "max_drawdown": max_dd(r),
        "worst_day": float(r.min()), "win_rate": float((tr["net"] > 0).mean()) if len(tr) else None,
        "bootstrap_p_one_sided": block_bootstrap_p(r.to_numpy()),
        "by_year_net": {int(k): float((1 + v).prod() - 1) for k, v in r.groupby(r.index.year)},
    }


def run(mode: str) -> dict:
    if mode == "dev":
        start, end = DEV
        selected = CANDIDATES
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} first")
        start, end = VAL
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not selected:
            raise SystemExit("development selected nothing")
    else:
        raise SystemExit("mode must be dev or validation")
    spy = load_spot("SPY", end + pd.Timedelta(days=10))
    calendar = spy.index
    ff = french_daily()
    rf = ff["rf"].reindex(calendar.union(ff.index)).ffill().reindex(calendar)
    rates = np.log1p(rf) * 252
    out = OUT / mode
    out.mkdir(parents=True, exist_ok=True)
    res = {"mode": mode, "window": [str(start.date()), str(end.date())], "candidates": {}}
    spy_ret = spy["Adj Close"].pct_change().reindex(calendar)
    window = calendar[(calendar > start) & (calendar <= end)]
    res["spy_buy_hold_max_drawdown"] = max_dd(spy_ret.reindex(window).fillna(0))
    for label, cost in COSTS.items():
        tr = {t: trades(t, start, end, calendar, rates, cost) for t in HALF_SPREAD}
        for t, df in tr.items():
            df.to_csv(out / f"trades_{t}_{label}.csv", index=False)
        series = {}
        spy_tr = tr["SPY"]
        series["P1_spy"] = (spy_tr, daily_series(spy_tr, calendar, start, end), daily_series(spy_tr, calendar, start, end, "gross"))
        vrp = spy_tr[spy_tr["iv"] > spy_tr["rv"]] if not spy_tr.empty else spy_tr
        series["P2_spy_vrp"] = (vrp, daily_series(vrp, calendar, start, end), daily_series(vrp, calendar, start, end, "gross"))
        all_tr = pd.concat(tr.values(), ignore_index=True)
        net3 = sum(daily_series(df, calendar, start, end) for df in tr.values()) / 3.0
        gross3 = sum(daily_series(df, calendar, start, end, "gross") for df in tr.values()) / 3.0
        series["P3_etf3"] = (all_tr, net3, gross3)
        for name in selected:
            t_, r, g = series[name]
            r = r[r.index <= end + pd.Timedelta(days=7)]
            res["candidates"].setdefault(name, {})[label] = summarize(r, g.reindex(r.index), t_)
            r.to_csv(out / f"{name}_{label}_daily.csv")
    if mode == "dev":
        sel = [n for n in selected if res["candidates"][n]["base"]["sharpe_net"] >= DEV_GATE]
        (out / "selection.json").write_text(json.dumps({"selected": sel, "gate": f"net base Sharpe >= {DEV_GATE}"}, indent=1))
        res["selected"] = sel
    else:
        for n in selected:
            b, s = res["candidates"][n]["base"], res["candidates"][n]["stress"]
            b["passes"] = bool(b["sharpe_net"] >= VAL_GATE and s["ann_mean_net"] > 0 and b["bootstrap_p_one_sided"] < ALPHA
                               and b["max_drawdown"] >= res["spy_buy_hold_max_drawdown"])
    res["code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    for n, v in r["candidates"].items():
        b, s = v["base"], v["stress"]
        print(f"{n:11s} net Sharpe {b['sharpe_net']:+.2f} (gross {b['sharpe_gross']:+.2f}, stress {s['sharpe_net']:+.2f}) "
              f"CAGR {b['excess_cagr']:+.2%} maxDD {b['max_drawdown']:.1%} worst day {b['worst_day']:.2%} trades {b['trades']}")
    print("selected:", r.get("selected"), "| SPY maxDD", f"{r['spy_buy_hold_max_drawdown']:.1%}")
