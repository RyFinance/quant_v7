"""Development / validation runs for research/cot/PLAN.md.

  PYTHONPATH=. .venv/bin/python -m research.cot.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.cot.evaluate validation   # needs the registered unlock
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from research.common.inference import null_kind, sharpe_ci
from research.options_signals.evaluate import block_bootstrap_p, newey_west_t
from research.options_signals.signals import french_daily

ROOT = Path(__file__).resolve().parents[2]
COT = ROOT / "data" / "lse" / "cot" / "cot.parquet"
PRICES = ROOT / "data" / "cot_etf_prices.parquet"
OUT = ROOT / "reports" / "cot"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/cot/VALIDATION_UNLOCK.md"

MAP = {"ZC": "CORN", "ZS": "SOYB", "ZW": "WEAT", "SB": "CANE", "GC": "GLD", "SI": "SLV",
       "HG": "CPER", "PL": "PPLT", "PA": "PALL", "RB": "UGA", "BZ": "BNO"}
COST_BPS = {"GLD": 2, "SLV": 2, "PPLT": 5, "PALL": 5, "BNO": 5,
            "CORN": 15, "SOYB": 15, "WEAT": 15, "CANE": 15, "CPER": 15, "UGA": 15}
COSTS = {"base": {"mult": 1.0, "borrow": 0.01, "proceeds_earn_rf": True},
         "stress": {"mult": 3.0, "borrow": 0.05, "proceeds_earn_rf": False}}
DEV = (pd.Timestamp("2015-01-01"), pd.Timestamp("2019-12-31"))
VAL = (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-09-17"))
LEG, MIN_MARKETS = 3, 8
CANDIDATES = ["C1_liquidity", "C2_hedging_pressure", "C3_two_premiums"]
DEV_GATE, VAL_GATE, ALPHA = 0.5, 0.75, 0.05 / 3


def validation_unlocked() -> bool:
    path = ROOT / UNLOCK
    if not path.exists():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return any(json.loads(l).get("file") == UNLOCK and json.loads(l).get("sha256") == digest
               for l in PREREG.read_text().splitlines())


def pull_prices() -> pd.DataFrame:
    raw = yf.download(list(MAP.values()), start="2014-01-01", end="2026-09-18", auto_adjust=True,
                      progress=False, group_by="ticker")
    rows = []
    for t in MAP.values():
        d = raw[t][["Open", "Close"]].dropna().reset_index()
        d["etf"] = t
        rows.append(d.rename(columns={"Date": "date", "Open": "open", "Close": "close"}))
    df = pd.concat(rows, ignore_index=True)
    df.to_parquet(PRICES, index=False)
    return df


def cot_signals(cot: pd.DataFrame, upto: pd.Timestamp) -> pd.DataFrame:
    """One row per (release_date, etf): Q (speculator net purchase / lagged OI) and 52-report mean HP.
    Only reports released on or before `upto` are read."""
    c = cot[cot["symbol"].isin(MAP)].copy()
    c["date"] = pd.to_datetime(c["date"])
    c["release_date"] = pd.to_datetime(c["release_date"])
    c = c[c["release_date"] <= upto]
    # the vault can carry two contracts under one symbol (e.g. CL); keep the largest open interest per report
    c = c.sort_values("open_interest").drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
    out = []
    for sym, g in c.groupby("symbol"):
        g = g.set_index("date")
        net = g["noncomm_long"] - g["noncomm_short"]
        oi = g["open_interest"].astype(float)
        gap = g.index.to_series().diff().dt.days
        q = (net - net.shift(1)) / oi.shift(1)
        q[gap > 8] = np.nan
        hp = (g["comm_short"] - g["comm_long"]) / oi
        hp52 = hp.rolling(52, min_periods=40).mean()
        out.append(pd.DataFrame({"release_date": g["release_date"], "etf": MAP[sym], "q": q, "hp52": hp52}))
    return pd.concat(out).reset_index(drop=True)


def entry_panel(sig: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    pos = calendar.searchsorted(sig["release_date"].to_numpy(), side="right")
    ok = pos < len(calendar)
    sig = sig[ok].assign(entry=calendar[pos[ok]])
    q = sig.pivot_table(index="entry", columns="etf", values="q", aggfunc="last")
    hp = sig.pivot_table(index="entry", columns="etf", values="hp52", aggfunc="last")
    score = {"C1_liquidity": -q, "C2_hedging_pressure": hp}
    rq, rh = (-q).rank(axis=1, pct=True), hp.rank(axis=1, pct=True)
    both = (rq + rh) / 2
    score["C3_two_premiums"] = both.where(rq.notna() & rh.notna())
    return score


def target_weights(s: pd.Series) -> pd.Series:
    s = s.dropna()
    w = pd.Series(0.0, index=list(COST_BPS))
    if len(s) < MIN_MARKETS:
        return w
    order = s.rank(method="first")
    w[order.nlargest(LEG).index] = 1.0 / LEG
    w[order.nsmallest(LEG).index] = -1.0 / LEG
    return w


def backtest(score: pd.DataFrame, opens: pd.DataFrame, rf_daily: pd.Series, entries: pd.DatetimeIndex,
             cost: dict) -> pd.DataFrame:
    per_side = pd.Series(COST_BPS, dtype=float) / 1e4 * cost["mult"]
    prev_w = pd.Series(0.0, index=list(COST_BPS))
    prev_r = pd.Series(0.0, index=list(COST_BPS))
    rows = []
    for k in range(len(entries) - 1):
        e, x = entries[k], entries[k + 1]
        s = score.loc[e] if e in score.index else pd.Series(dtype=float)
        s = s.reindex(list(COST_BPS)).where(opens.loc[e].notna())
        w = target_weights(s)
        r = (opens.loc[x] / opens.loc[e] - 1.0).reindex(w.index).fillna(0.0)
        g_prev = float((prev_w * prev_r).sum())
        drift = prev_w * (1 + prev_r) / (1 + g_prev) if prev_w.abs().sum() > 0 else prev_w
        trade = (w - drift).abs()
        tcost = float((trade * per_side).sum())
        days = (x - e).days
        short_gross = float(-w[w < 0].sum())
        rf_hold = float((1 + rf_daily.loc[(rf_daily.index > e) & (rf_daily.index <= x)]).prod() - 1)
        borrow = short_gross * cost["borrow"] * days / 365
        proceeds = 0.0 if cost["proceeds_earn_rf"] else short_gross * rf_hold
        gross = float((w * r).sum())
        rows.append({"entry": e, "exit": x, "n_long": int((w > 0).sum()), "turnover": float(trade.sum()),
                     "gross": gross, "cost": tcost, "borrow": borrow, "proceeds_drag": proceeds,
                     "net": gross - tcost - borrow - proceeds})
        prev_w, prev_r = w, r
    return pd.DataFrame(rows).set_index("entry")


def summarize(bt: pd.DataFrame) -> dict:
    net, gross = bt["net"].to_numpy(), bt["gross"].to_numpy()
    years = (bt["exit"].iloc[-1] - bt.index[0]).days / 365.25
    nav = np.cumprod(1 + net)
    ci = sharpe_ci(net, 52, block=8)
    return {"weeks": len(bt), "active_weeks": int((bt["n_long"] > 0).sum()),
            "sharpe_net": float(net.mean() / net.std(ddof=1) * np.sqrt(52)),
            "sharpe_gross": float(gross.mean() / gross.std(ddof=1) * np.sqrt(52)),
            "sharpe_ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5),
            "ann_mean_net": float(net.mean() * 52), "ann_vol": float(net.std(ddof=1) * np.sqrt(52)),
            "excess_cagr": float(nav[-1] ** (1 / years) - 1), "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
            "annual_turnover": float(bt["turnover"].sum() / years),
            "annual_cost_drag": float((bt["cost"] + bt["borrow"] + bt["proceeds_drag"]).sum() / years),
            "nw_t": newey_west_t(net), "bootstrap_p_one_sided": block_bootstrap_p(net),
            "by_year_net": {int(y): float(np.prod(1 + v) - 1) for y, v in bt["net"].groupby(bt.index.year)}}


def run(mode: str) -> dict:
    if mode == "dev":
        start, end, selected = *DEV, CANDIDATES
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} first")
        start, end = VAL
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not selected:
            raise SystemExit("development selected nothing")
    else:
        raise SystemExit("mode must be dev or validation")
    prices = pd.read_parquet(PRICES) if PRICES.exists() else pull_prices()
    prices["date"] = pd.to_datetime(prices["date"]).dt.tz_localize(None)
    opens = prices.pivot(index="date", columns="etf", values="open").sort_index()
    opens = opens.loc[: end + pd.Timedelta(days=14)]
    calendar = opens.index[opens["GLD"].notna()]
    opens = opens.reindex(calendar)
    sig = cot_signals(pd.read_parquet(COT), upto=end)
    scores = entry_panel(sig, calendar)
    ff = french_daily()
    rf_daily = ff["rf"].reindex(calendar.union(ff.index)).ffill().reindex(calendar)
    all_entries = scores["C1_liquidity"].index.union(scores["C2_hedging_pressure"].index)
    entries = all_entries[(all_entries >= start) & (all_entries <= end)]
    after = all_entries[all_entries > end]
    nxt = calendar[calendar > entries[-1] + pd.Timedelta(days=6)]
    entries = entries.append(pd.DatetimeIndex([after[0] if len(after) else nxt[0]]))
    out = OUT / mode
    out.mkdir(parents=True, exist_ok=True)
    res = {"mode": mode, "window": [str(start.date()), str(end.date())], "candidates": {}}
    for name in selected:
        res["candidates"][name] = {}
        for label, cost in COSTS.items():
            bt = backtest(scores[name], opens, rf_daily, entries, cost)
            bt.to_csv(out / f"{name}_{label}.csv")
            res["candidates"][name][label] = summarize(bt)
    if mode == "dev":
        sel = [n for n in selected if res["candidates"][n]["base"]["sharpe_net"] >= DEV_GATE]
        (out / "selection.json").write_text(json.dumps({"selected": sel}, indent=1))
        res["selected"] = sel
    else:
        for n in selected:
            b, s = res["candidates"][n]["base"], res["candidates"][n]["stress"]
            b["passes"] = bool(b["sharpe_net"] >= VAL_GATE and s["ann_mean_net"] > 0 and b["bootstrap_p_one_sided"] < ALPHA)
    res["code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    res["prices_sha256"] = hashlib.sha256(PRICES.read_bytes()).hexdigest()
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    for n, v in r["candidates"].items():
        b, s = v["base"], v["stress"]
        print(f"{n:20s} net Sharpe {b['sharpe_net']:+.2f} CI [{b['sharpe_ci95'][0]:+.2f},{b['sharpe_ci95'][1]:+.2f}] "
              f"(gross {b['sharpe_gross']:+.2f}, stress {s['sharpe_net']:+.2f}) CAGR {b['excess_cagr']:+.2%} "
              f"maxDD {b['max_drawdown']:.1%} cost/yr {b['annual_cost_drag']:.1%}")
    print("selected:", r.get("selected"))
