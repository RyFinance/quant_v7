"""Development / validation runs for research/fx_carry_vol/PLAN.md.

  PYTHONPATH=. .venv/bin/python -m research.fx_carry_vol.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.fx_carry_vol.evaluate validation   # needs the registered unlock
"""
from __future__ import annotations

import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.common.inference import null_kind, sharpe_ci
from research.options_signals.evaluate import block_bootstrap_p

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "lse" / "fx_carry" / "raw.pkl"
OUT = ROOT / "reports" / "fx_carry_vol"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/fx_carry_vol/VALIDATION_UNLOCK.md"
PEAD_BENCH = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "USDSEK", "USDNOK"]
USD_BASE = {"USDJPY", "USDCHF", "USDCAD", "USDSEK", "USDNOK"}
PIP = {p: (0.01 if p == "USDJPY" else 0.0001) for p in PAIRS}
COST_SIDE = {p: (2e-4 if p in ("NZDUSD", "USDSEK", "USDNOK") else 1e-4) for p in PAIRS}
ROLL = 0.2e-4
STRESS_MULT = 3.0
LEG, MIN_PAIRS, TARGET_VOL, MAX_SCALE, CORR_DAYS = 3, 7, 0.08, 3.0, 63
DEV = (pd.Timestamp("2015-01-06"), pd.Timestamp("2019-12-31"))
VAL = (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-09-17"))
CANDIDATES = ["F2_carry_to_vol", "F3_carry_to_vol_targeted"]
BASELINE = "F1_plain_carry"
DEV_GATE, VAL_GATE, ALPHA, BENCHMARK = 0.5, 0.75, 0.05 / 2, 0.70


def validation_unlocked() -> bool:
    p = ROOT / UNLOCK
    if not p.exists():
        return False
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    return any(json.loads(l).get("file") == UNLOCK and json.loads(l).get("sha256") == h
               for l in PREREG.read_text().splitlines())


def load(upto: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(spot, forward points, implied vol) as date × pair frames, nothing after `upto`."""
    raw = pickle.loads(RAW.read_bytes())
    spot, pts, iv = {}, {}, {}
    for p in PAIRS:
        c = raw[(p, "spot")].copy()
        c["d"] = pd.to_datetime(c["ts"]).dt.normalize()
        c = c[c["d"].dt.dayofweek < 5]
        spot[p] = c.set_index("d")["close"]
        pts[p] = raw[(p, "SW_FWD")].assign(date=lambda x: pd.to_datetime(x["date"])).set_index("date")["value"]
        iv[p] = raw[(p, "1M_ATM")].assign(date=lambda x: pd.to_datetime(x["date"])).set_index("date")["value"] / 100.0
    frames = [pd.DataFrame(x).sort_index() for x in (spot, pts, iv)]
    return tuple(f.loc[:upto] for f in frames)


def forward(spot: pd.Series, pts: pd.Series, pair: str) -> pd.Series:
    return spot + pts * PIP[pair]


def carry(S: pd.Series, F: pd.Series) -> pd.Series:
    """Annualised carry of a LONG foreign-currency position, per pair (index = pairs)."""
    out = {}
    for p in S.index:
        out[p] = (F[p] - S[p]) / S[p] * 52 if p in USD_BASE else (S[p] - F[p]) / F[p] * 52
    return pd.Series(out)


def long_foreign_return(p: str, F_entry: float, S_exit: float) -> float:
    return F_entry / S_exit - 1 if p in USD_BASE else S_exit / F_entry - 1


def usd_value_log_returns(spot: pd.DataFrame) -> pd.DataFrame:
    lr = np.log(spot).diff()
    for p in USD_BASE:
        lr[p] = -lr[p]
    return lr


def weights(kind: str, c: pd.Series, iv: pd.Series, corr: pd.DataFrame | None) -> pd.Series:
    ok = c.notna() & iv.notna() & (iv > 0)
    w = pd.Series(0.0, index=PAIRS)
    if ok.sum() < MIN_PAIRS:
        return w
    c, iv = c[ok], iv[ok]
    score = c if kind == BASELINE else c / iv
    order = score.rank(method="first")
    top, bot = order.nlargest(LEG).index, order.nsmallest(LEG).index
    if kind == BASELINE:
        w[top], w[bot] = 1.0 / LEG, -1.0 / LEG
        return w
    inv = 1.0 / iv
    w[top] = inv[top] / inv[top].sum()
    w[bot] = -inv[bot] / inv[bot].sum()
    if kind == "F3_carry_to_vol_targeted" and corr is not None:
        names = list(w.index[w != 0])
        C = corr.reindex(index=names, columns=names).fillna(0.0).to_numpy()
        np.fill_diagonal(C, 1.0)
        sig = iv.reindex(names).to_numpy()
        cov = C * np.outer(sig, sig)
        vol = float(np.sqrt(w[names].to_numpy() @ cov @ w[names].to_numpy()))
        if vol > 0:
            w = w * min(MAX_SCALE, TARGET_VOL / vol)
    return w


def run_book(kind: str, spot, pts, iv, start, end, cost_mult: float) -> pd.DataFrame:
    cal = spot.index[spot["EURUSD"].notna()]
    lr = usd_value_log_returns(spot)
    signal_days = cal[(cal >= start) & (cal <= end) & (cal.dayofweek == 1)]
    rows, prev = [], pd.Series(0.0, index=PAIRS)
    for t in signal_days:
        after = cal[cal > t]
        if len(after) == 0:
            break
        e = after[0]
        x_candidates = cal[cal >= e + pd.Timedelta(days=7)]
        if len(x_candidates) == 0:
            break
        x = x_candidates[0]
        S_t, P_t, V_t = spot.loc[t], pts.loc[:t].iloc[-1] if len(pts.loc[:t]) else None, iv.loc[:t].iloc[-1] if len(iv.loc[:t]) else None
        if P_t is None or V_t is None or (t - pts.loc[:t].index[-1]).days > 5:
            continue
        F_t = pd.Series({p: forward(S_t[p], P_t[p], p) for p in PAIRS})
        c = carry(S_t, F_t)
        hist = lr.loc[:t].tail(CORR_DAYS)
        corr = hist.corr() if len(hist) >= 40 else None
        w = weights(kind, c, V_t, corr)
        P_e = pts.loc[:e].iloc[-1]
        r = pd.Series({p: long_foreign_return(p, forward(spot.at[e, p], P_e[p], p), spot.at[x, p]) for p in PAIRS}).fillna(0.0)
        cost_side = pd.Series(COST_SIDE) * cost_mult
        trade = float(((w - prev).abs() * cost_side).sum())
        roll = float(w.abs().sum() * ROLL * cost_mult)
        gross = float((w * r).sum())
        rows.append({"signal": t, "entry": e, "exit": x, "gross": gross, "cost": trade + roll, "net": gross - trade - roll,
                     "gross_exposure": float(w.abs().sum()), "longs": ",".join(w.index[w > 0]), "shorts": ",".join(w.index[w < 0])})
        prev = w
    return pd.DataFrame(rows).set_index("signal")


def summarize(bt: pd.DataFrame) -> dict:
    x = bt["net"].to_numpy()
    ci = sharpe_ci(x, 52, block=8)
    nav = np.cumprod(1 + x)
    years = len(x) / 52
    return {"weeks": len(x), "sharpe_net": float(x.mean() / x.std(ddof=1) * np.sqrt(52)),
            "sharpe_gross": float(bt["gross"].mean() / bt["gross"].std(ddof=1) * np.sqrt(52)),
            "sharpe_ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5),
            "ann_mean": float(x.mean() * 52), "ann_vol": float(x.std(ddof=1) * np.sqrt(52)),
            "cagr": float(nav[-1] ** (1 / years) - 1), "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
            "cost_drag": float(bt["cost"].mean() * 52), "avg_gross_exposure": float(bt["gross_exposure"].mean()),
            "bootstrap_p_one_sided": block_bootstrap_p(x, block=8),
            "by_year": {int(y): float(np.prod(1 + v) - 1) for y, v in bt["net"].groupby(bt.index.year)}}


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
    spot, pts, iv = load(end + pd.Timedelta(days=12))
    pts, iv = pts.loc[:end], iv.loc[:end]
    out = OUT / mode
    out.mkdir(parents=True, exist_ok=True)
    res = {"mode": mode, "window": [str(start.date()), str(end.date())], "strategies": {}}
    books = {}
    for name in [BASELINE] + selected:
        res["strategies"][name] = {}
        for label, mult in (("base", 1.0), ("stress", STRESS_MULT)):
            bt = run_book(name, spot, pts, iv, start, end, mult)
            bt.to_csv(out / f"{name}_{label}.csv")
            res["strategies"][name][label] = summarize(bt)
            if label == "base":
                books[name] = bt
    for name in selected:
        d = (books[name]["net"] - books[BASELINE]["net"]).dropna()
        res["strategies"][name]["base"]["paired_vs_F1"] = {
            "mean_diff_ann": float(d.mean() * 52), "sharpe_of_diff": float(d.mean() / d.std(ddof=1) * np.sqrt(52)),
            "bootstrap_p_one_sided": block_bootstrap_p(d.to_numpy(), block=8)}
    if PEAD_BENCH.exists():
        c = pd.read_csv(PEAD_BENCH, index_col=0, parse_dates=True)
        bench = (c["mtm_rf"].pct_change() - c["rf_index"].pct_change()).fillna(0)
        for name in [BASELINE] + selected:
            bt = books[name]
            wk = [(float(np.prod(1 + bench.loc[(bench.index > e) & (bench.index <= x)]) - 1)) for e, x in zip(bt["entry"], bt["exit"])]
            s = pd.Series(wk, index=bt.index)
            ok = bench.index.min() <= bt["entry"]
            both = pd.concat([bt.loc[ok.to_numpy(), "net"], s[ok.to_numpy()]], axis=1).dropna()
            res["strategies"][name]["base"]["corr_with_pead_benchmark"] = float(both.corr().iloc[0, 1]) if len(both) > 26 else None
    f1 = res["strategies"][BASELINE]["base"]["sharpe_net"]
    if mode == "dev":
        sel = [n for n in selected if res["strategies"][n]["base"]["sharpe_net"] >= DEV_GATE and res["strategies"][n]["base"]["sharpe_net"] > f1]
        (out / "selection.json").write_text(json.dumps({"selected": sel}, indent=1))
        res["selected"] = sel
    else:
        for n in selected:
            b, s = res["strategies"][n]["base"], res["strategies"][n]["stress"]
            b["passes"] = bool(b["sharpe_net"] >= VAL_GATE and s["ann_mean"] > 0 and b["bootstrap_p_one_sided"] < ALPHA
                               and b["sharpe_net"] > BENCHMARK and b["paired_vs_F1"]["mean_diff_ann"] > 0
                               and b["paired_vs_F1"]["bootstrap_p_one_sided"] < 0.05)
    res["code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    res["raw_sha256"] = hashlib.sha256(RAW.read_bytes()).hexdigest()
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    for n, v in r["strategies"].items():
        b, s = v["base"], v["stress"]
        extra = f" | vs F1: {b['paired_vs_F1']['mean_diff_ann']:+.2%}/yr p={b['paired_vs_F1']['bootstrap_p_one_sided']:.2f}" if "paired_vs_F1" in b else ""
        print(f"{n:26s} net {b['sharpe_net']:+.2f} CI [{b['sharpe_ci95'][0]:+.2f},{b['sharpe_ci95'][1]:+.2f}] gross {b['sharpe_gross']:+.2f} "
              f"stress {s['sharpe_net']:+.2f} | ann {b['ann_mean']:+.2%} vol {b['ann_vol']:.1%} maxDD {b['max_drawdown']:.1%} cost {b['cost_drag']:.2%}{extra}")
    print("selected:", r.get("selected"))
