"""Registered test of earnings-surprise streaks (research/pead_streak/PLAN.md).

  PYTHONPATH=. .venv/bin/python -m research.pead_streak.streak dev
  PYTHONPATH=. .venv/bin/python -m research.pead_streak.streak validation   # needs the unlock

Refuses to run if PLAN.md no longer matches its registered sha256; validation also needs
research/pead_streak/VALIDATION_UNLOCK.md registered, and only evaluates candidates the development
run selected.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.options_signals.evaluate import block_bootstrap_p
from research.options_signals.signals import french_daily
from research.pead_audit.mtm_audit import ols_hac

ROOT = Path(__file__).resolve().parents[2]
PLAN = "research/pead_streak/PLAN.md"
UNLOCK = "research/pead_streak/VALIDATION_UNLOCK.md"
PREREG = ROOT / "research" / "preregistrations.jsonl"
OUT = ROOT / "reports" / "pead_streak"
STOCKS = ROOT / "data" / "multiasset" / "stocks"
BENCH = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

DEV = (pd.Timestamp("2015-04-01"), pd.Timestamp("2021-06-30"))
VAL = (pd.Timestamp("2021-07-01"), pd.Timestamp("2025-06-30"))
HOLD = 20            # sessions; returns of days +2..+21
PREV_MIN_DAYS, PREV_MAX_DAYS = 30, 200
COSTS = {"base": {"per_side": 0.0005, "borrow": 0.005}, "stress": {"per_side": 0.0015, "borrow": 0.015}}
# name: (event filter, long gross, short gross)
BOOKS = {
    "S1_streak_ls": ("streak", 0.5, 0.5),
    "S2_streak_long": ("streak", 1.0, 0.0),
    "C1_all_ls": ("all", 0.5, 0.5),
    "C2_all_long": ("all", 1.0, 0.0),
}
CANDIDATES = {"S1_streak_ls": "C1_all_ls", "S2_streak_long": "C2_all_long"}
DEV_GATE, VAL_GATE, BENCHMARK = 0.5, 0.75, 0.70
ALPHA = 0.05 / len(CANDIDATES)
N_TRIALS, BLOCK = 65, 21


# -- guards -----------------------------------------------------------------------------------------
def _registered(rel: str) -> bool:
    path = ROOT / rel
    if not path.exists() or not PREREG.exists():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return any(json.loads(l).get("file") == rel and json.loads(l).get("sha256") == digest
               for l in PREREG.read_text().splitlines() if l.strip())


def validation_unlocked() -> bool:
    return _registered(UNLOCK)


# -- events -----------------------------------------------------------------------------------------
def load_events() -> pd.DataFrame:
    sig = pd.read_parquet(ROOT / "data" / "pead_signal_expanded.parquet")
    ev = sig[["ticker", "date", "earnings_date_raw", "surprise_pct"]].rename(
        columns={"date": "effective", "earnings_date_raw": "announced"})
    return ev


def add_streak(ev: pd.DataFrame) -> pd.DataFrame:
    """Previous surprise = the ticker's immediately preceding announcement, only if it was announced
    30-200 days earlier and became tradable strictly before the current effective date."""
    ev = ev.sort_values(["ticker", "announced"]).reset_index(drop=True).copy()
    ev["sign"] = np.sign(ev["surprise_pct"]).fillna(0.0)
    g = ev.groupby("ticker")
    ev["prev_sign"] = g["sign"].shift(1)
    ev["prev_announced"] = g["announced"].shift(1)
    ev["prev_effective"] = g["effective"].shift(1)
    gap = (ev["announced"] - ev["prev_announced"]).dt.days
    ok = gap.between(PREV_MIN_DAYS, PREV_MAX_DAYS) & (ev["prev_effective"] < ev["effective"])
    ev.loc[~ok, "prev_sign"] = np.nan
    ev["streak"] = (ev["sign"] != 0) & (ev["sign"] == ev["prev_sign"])
    return ev


# -- prices -----------------------------------------------------------------------------------------
def load_closes(tickers, upto: pd.Timestamp) -> pd.DataFrame:
    out = {}
    for t in sorted(set(tickers)):
        p = STOCKS / f"{t}.parquet"
        if p.exists():
            d = pd.read_parquet(p, columns=["date", "close"])
            d["date"] = pd.to_datetime(d["date"]).dt.normalize()
            out[t] = d.drop_duplicates("date").set_index("date")["close"]
    px = pd.DataFrame(out).sort_index().loc[:upto]
    return px[px.notna().sum(axis=1) > px.shape[1] // 2]


# -- book -------------------------------------------------------------------------------------------
def schedule(ev: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Return-day window [start, end] (calendar indices) per event: day 0 = first session >= effective,
    entry at close of day +1, returns of days +2..+1+HOLD. A held ticker ignores new events."""
    d0 = cal.searchsorted(ev["effective"].to_numpy(), side="left")
    ev = ev.assign(d0=d0, start=d0 + 2, end=d0 + 1 + HOLD).sort_values(["d0", "ticker"])
    ev = ev[ev["d0"] + 1 < len(cal)]
    keep, busy = [], {}
    for r in ev.itertuples():
        if busy.get(r.ticker, -1) >= r.d0 + 1:
            continue
        busy[r.ticker] = r.end
        keep.append(r.Index)
    return ev.loc[keep]


def weights(sched: pd.DataFrame, cal: pd.DatetimeIndex, cols, long_g: float, short_g: float) -> pd.DataFrame:
    """W[t] = weight held over return day t (set at the close of t-1); equal weight within each leg."""
    n = len(cal)
    col = {c: i for i, c in enumerate(cols)}
    L = np.zeros((n, len(cols)))
    S = np.zeros((n, len(cols)))
    for r in sched.itertuples():
        if r.ticker not in col or r.start >= n:
            continue
        a, b = r.start, min(r.end, n - 1) + 1
        if r.sign > 0 and long_g > 0:
            L[a:b, col[r.ticker]] = 1.0
        elif r.sign < 0 and short_g > 0:
            S[a:b, col[r.ticker]] = 1.0
    nl, ns = L.sum(1, keepdims=True), S.sum(1, keepdims=True)
    W = np.where(nl > 0, L / np.maximum(nl, 1) * long_g, 0) - np.where(ns > 0, S / np.maximum(ns, 1) * short_g, 0)
    return pd.DataFrame(W, index=cal, columns=cols)


def book_returns(W: pd.DataFrame, rets: pd.DataFrame, rf: pd.Series, per_side: float, borrow: float) -> pd.DataFrame:
    r = rets.reindex(index=W.index, columns=W.columns)
    held = W.to_numpy() != 0
    missing = int((held & r.isna().to_numpy()).sum())
    R = r.fillna(0.0).to_numpy()
    w = W.to_numpy()
    rfv = rf.reindex(W.index).to_numpy()
    gross_ex = (w * (R - rfv[:, None])).sum(1)
    port = (w * R).sum(1)
    prev = np.vstack([np.zeros(w.shape[1]), w[:-1]])
    prev_r = np.vstack([np.zeros(w.shape[1]), R[:-1]])
    prev_port = np.concatenate([[0.0], port[:-1]])
    drifted = prev * (1 + prev_r) / (1 + prev_port)[:, None]
    turnover = np.abs(w - drifted).sum(1)
    cost = turnover * per_side
    short = -np.clip(w, None, 0).sum(1)
    borrow_cost = short * borrow / 252
    out = pd.DataFrame({"gross_excess": gross_ex, "cost": cost, "borrow": borrow_cost, "turnover": turnover,
                        "long_gross": np.clip(w, 0, None).sum(1), "short_gross": short,
                        "names": (w != 0).sum(1)}, index=W.index)
    out["excess"] = out["gross_excess"] - out["cost"] - out["borrow"]
    out.attrs["missing_marks"] = missing
    return out


# -- statistics -------------------------------------------------------------------------------------
def stats(ex: pd.Series, mkt: pd.Series) -> dict:
    x = ex.to_numpy()
    sr = float(x.mean() / x.std(ddof=1) * np.sqrt(252))
    ci = sharpe_ci(x, 252, block=BLOCK)
    b, t = ols_hac(x, mkt.reindex(ex.index).fillna(0.0).to_numpy())
    nav = np.cumprod(1 + x)
    by_year = {int(y): {"excess_return": float(np.prod(1 + s) - 1),
                        "sharpe": float(s.mean() / s.std(ddof=1) * np.sqrt(252)) if s.std() > 0 else None}
               for y, s in ex.groupby(ex.index.year)}
    return {"sharpe": sr, "ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5),
            "ann_excess": float(x.mean() * 252), "ann_vol": float(x.std(ddof=1) * np.sqrt(252)),
            "max_dd": float((nav / np.maximum.accumulate(nav) - 1).min()),
            "p_one_sided": block_bootstrap_p(x, block=BLOCK), "beta": float(b[1]),
            "alpha_ann": float(b[0] * 252), "alpha_t": float(t[0]), "by_year": by_year}


def benchmark_excess() -> pd.Series:
    c = pd.read_csv(BENCH, index_col=0, parse_dates=True)
    return (c["mtm_rf"].pct_change() - c["rf_index"].pct_change()).dropna()


# -- run --------------------------------------------------------------------------------------------
def run(mode: str) -> dict:
    if not _registered(PLAN):
        raise SystemExit(f"{PLAN} changed since registration")
    if mode == "dev":
        (start, end), selected = DEV, list(CANDIDATES)
        price_end = end
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} first")
        (start, end) = VAL
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not selected:
            raise SystemExit("development selected nothing; validation is not run")
        price_end = end + pd.Timedelta(days=45)  # exits of the last events
    else:
        raise SystemExit("mode must be dev or validation")

    ev = add_streak(load_events())
    ev = ev[(ev["effective"] >= start) & (ev["effective"] <= end) & (ev["sign"] != 0)]
    px = load_closes(ev["ticker"].unique(), price_end)
    rets = px.pct_change(fill_method=None)
    cal = px.index[px.index >= start]
    rets = rets.reindex(cal)
    ff = french_daily()
    rf = ff["rf"].reindex(cal.union(ff.index)).ffill().reindex(cal)
    mkt = ff["mkt_rf"].reindex(cal)
    last = cal.searchsorted(end, side="right") if mode == "dev" else len(cal)

    books = {n: BOOKS[n] for n in (list(BOOKS) if mode == "dev" else selected + [CANDIDATES[s] for s in selected])}
    outdir = OUT / mode
    outdir.mkdir(parents=True, exist_ok=True)
    res = {"mode": mode, "window": [str(start.date()), str(end.date())],
           "events": {"all_nonzero": int(len(ev)), "with_known_prev": int(ev["prev_sign"].notna().sum()),
                      "streak": int(ev["streak"].sum()),
                      "streak_pos": int((ev["streak"] & (ev["sign"] > 0)).sum()),
                      "streak_neg": int((ev["streak"] & (ev["sign"] < 0)).sum())},
           "tickers_with_prices": int(px.shape[1]), "books": {}}
    series = {}
    for name, (filt, lg, sg) in books.items():
        e = ev[ev["streak"]] if filt == "streak" else ev
        if sg == 0:  # long-only: negative events are never held, so they must not block a ticker
            e = e[e["sign"] > 0]
        sch = schedule(e, cal)
        W = weights(sch, cal, px.columns, lg, sg)
        res["books"][name] = {"events_traded": int(len(sch))}
        for label, c in COSTS.items():
            b = book_returns(W, rets, rf, c["per_side"], c["borrow"]).iloc[:last]
            b = b.loc[b.index[b["names"].cumsum() > 0][0]:]  # from the first held position
            b.to_csv(outdir / f"{name}_{label}.csv")
            s = stats(b["excess"], mkt)
            s.update({"gross_sharpe": float(b["gross_excess"].mean() / b["gross_excess"].std() * np.sqrt(252)),
                      "annual_turnover": float(b["turnover"].mean() * 252),
                      "annual_cost_drag": float((b["cost"] + b["borrow"]).mean() * 252),
                      "avg_names": float(b["names"].mean()), "days": int(len(b)),
                      "missing_marks": b.attrs.get("missing_marks", 0)})
            res["books"][name][label] = s
            if label == "base":
                series[name] = b["excess"]
    var_sr = float(np.var([s.mean() / s.std(ddof=1) for s in series.values()], ddof=1))
    res["trial_sharpe_var"] = var_sr
    bench = benchmark_excess()
    for cand in [s for s in selected if s in series]:
        ctl = CANDIDATES[cand]
        x = series[cand]
        res["books"][cand]["base"]["deflated_sharpe_prob_n65"] = deflated_sharpe(x.to_numpy(), N_TRIALS, var_sr)
        d = (x - series[ctl]).dropna()
        res["books"][cand]["minus_control"] = {"sharpe": float(d.mean() / d.std() * np.sqrt(252)),
                                               "p_one_sided": block_bootstrap_p(d.to_numpy(), block=BLOCK)}
        j = pd.concat([x, bench], axis=1, join="inner").dropna()
        res["books"][cand]["corr_with_pead_benchmark"] = (
            {"corr": float(j.corr().iloc[0, 1]), "days": int(len(j))} if len(j) > 20 else None)
    if mode == "dev":
        sel = [c for c in CANDIDATES if res["books"][c]["base"]["sharpe"] >= DEV_GATE
               and res["books"][c]["base"]["sharpe"] > res["books"][CANDIDATES[c]]["base"]["sharpe"]]
        (outdir / "selection.json").write_text(json.dumps({"selected": sel}, indent=1))
        res["selected"] = sel
    else:
        for c in selected:
            b, s = res["books"][c]["base"], res["books"][c]["stress"]
            b["passes_validation"] = bool(b["sharpe"] >= VAL_GATE and s["sharpe"] > 0
                                          and b["p_one_sided"] < ALPHA and b["sharpe"] > BENCHMARK)
    res["code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (outdir / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    print(json.dumps(r["events"]))
    for n, v in r["books"].items():
        b, s = v["base"], v["stress"]
        print(f"{n:15s} traded {v['events_traded']:5d} net {b['sharpe']:+.2f} CI[{b['ci95'][0]:+.2f},{b['ci95'][1]:+.2f}] "
              f"gross {b['gross_sharpe']:+.2f} stress {s['sharpe']:+.2f} p {b['p_one_sided']:.3f} beta {b['beta']:.2f} "
              f"alpha {b['alpha_ann']:+.2%} t {b['alpha_t']:.2f} names {b['avg_names']:.0f} miss {b['missing_marks']}")
    print("selected:", r.get("selected"))
