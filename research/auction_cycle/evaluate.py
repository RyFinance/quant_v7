"""Development and validation runs for research/auction_cycle/PLAN.md (+ amendment 1).

  PYTHONPATH=. .venv/bin/python -m research.auction_cycle.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.auction_cycle.evaluate validation   # needs the unlock

Development truncates prices at DEV_END before anything is computed. Validation refuses to start
unless research/auction_cycle/VALIDATION_UNLOCK.md is registered with a matching hash, and evaluates
only the candidates development selected.
"""
from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import pandas as pd

from research.auction_cycle import signals as sg
from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.options_signals.evaluate import block_bootstrap_p
from research.options_signals.signals import french_daily

ROOT = sg.ROOT
OUT = ROOT / "reports" / "auction_cycle"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/auction_cycle/VALIDATION_UNLOCK.md"
PEAD = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

DEV_START, DEV_END = pd.Timestamp("2015-01-02"), pd.Timestamp("2019-12-31")
VAL_START, VAL_END = pd.Timestamp("2020-01-01"), pd.Timestamp("2026-09-18")
CANDIDATES = ["A1_pre_short", "A2_post_long", "A3_combined"]
COSTS = {"base": 0.0002, "stress": 0.0006}  # per side
DEV_GATE, VAL_GATE, BENCH = 0.5, 0.75, 0.70
ALPHA = 0.05 / len(CANDIDATES)
BLOCK, N_TRIALS = 21, 65


def validation_unlocked() -> bool:
    path = ROOT / UNLOCK
    if not path.exists() or not PREREG.exists():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for line in PREREG.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("file") == UNLOCK and rec.get("sha256") == digest:
            return True
    return False


def backtest(w_held: pd.Series, xr: pd.Series, per_side: float, lag: int = 0) -> pd.Series:
    """w_held[i] (chosen at close i-1) earns excess return xr[i]; cost per_side x |w_i - w_{i-1}| on day i."""
    w = w_held.shift(lag).fillna(0.0)
    cost = per_side * w.diff().abs().fillna(w.abs())
    return w * xr - cost


def sharpe(x) -> float:
    x = np.asarray(x, float)
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan")


def summarize(net: pd.Series, held: pd.Series) -> dict:
    x = net.to_numpy()
    nav = (1 + net).cumprod()
    active = held != 0
    ci = sharpe_ci(x, 252, block=BLOCK)
    entries = int(((held != 0) & (held.shift(1).fillna(0) != held)).sum())
    return {
        "days": int(len(x)), "active_days": int(active.sum()), "entries": entries,
        "sharpe": sharpe(x), "ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5),
        "p_one_sided": block_bootstrap_p(x, block=BLOCK),
        "ann_mean": float(x.mean() * 252), "ann_vol": float(x.std(ddof=1) * np.sqrt(252)),
        "max_dd": float((nav / nav.cummax() - 1).min()),
        "hit_rate_active": float((net[active] > 0).mean()) if active.any() else float("nan"),
        "mean_bp_per_entry": float(net.sum() / max(entries, 1) * 1e4),
        "by_year": {int(k): float(v) for k, v in net.groupby(net.index.year).apply(lambda s: (1 + s).prod() - 1).items()},
        "sharpe_by_year": {int(k): sharpe(v) for k, v in net.groupby(net.index.year)},
    }


def excess(sym: str, upto: pd.Timestamp | None) -> pd.Series:
    p = sg.load_prices(sym, upto)
    r = p.pct_change()
    rf = french_daily()["rf"]
    rf = rf.reindex(rf.index.union(r.index)).ffill().reindex(r.index)
    return (r - rf).iloc[1:]


def event_study(xr: pd.Series, adates: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> dict:
    idx = xr.index
    out = {}
    for label, sub in [("all", adates), ("10y", adates[adates.tenor == 10])]:
        d = sub.date[(sub.date >= lo) & (sub.date <= hi)]
        pos = sg.auction_index(pd.DatetimeIndex(d), idx)
        row = {}
        for k in range(-5, 6):
            j = pos + k
            j = j[(j >= 0) & (j < len(idx))]
            row[k] = float(xr.iloc[j].mean() * 1e4)
        out[label] = {"n": int(len(pos)), "mean_bp_by_day": row}
    return out


def pead_excess() -> pd.Series:
    c = pd.read_csv(PEAD, index_col=0, parse_dates=True)
    return (c["mtm_rf"].pct_change() - c["rf_index"].pct_change()).dropna()


def run(mode: str) -> dict:
    if mode == "dev":
        upto, start, end, names = DEV_END, DEV_START, DEV_END, CANDIDATES
    else:
        if not validation_unlocked():
            raise SystemExit(f"validation locked: register {UNLOCK} first")
        dev = json.loads((OUT / "dev_results.json").read_text())
        names = dev["selected"]
        if not names:
            raise SystemExit("no candidate passed development")
        upto, start, end = VAL_END, VAL_START, VAL_END
    xr = excess("IEF", upto)
    xr_tlt = excess("TLT", upto)
    auc = sg.auctions()
    pos = sg.positions(xr.index, pd.DatetimeIndex(auc.date))
    win = (xr.index >= start) & (xr.index <= end)

    res = {"mode": mode, "window": [str(start.date()), str(end.date())],
           "n_auction_dates_in_window": int(auc.date[(auc.date >= start) & (auc.date <= end)].nunique()),
           "candidates": {}}
    nets, daily_sr = {}, {}
    for n in names:
        w = pos[n]
        held = w[win]
        net = backtest(w, xr, COSTS["base"])[win]
        gross = backtest(w, xr, 0.0)[win]
        stress = backtest(w, xr, COSTS["stress"])[win]
        lag1 = backtest(w, xr, COSTS["base"], lag=1)[win]
        tlt = backtest(w, xr_tlt.reindex(xr.index).fillna(0.0), COSTS["base"])[win]
        s = summarize(net, held)
        s.update({"sharpe_gross": sharpe(gross), "stress_sharpe": sharpe(stress),
                  "stress_ann_mean": float(stress.mean() * 252), "ann_cost_drag": float((gross - net).mean() * 252),
                  "descriptive_lag1_sharpe": sharpe(lag1), "descriptive_TLT_sharpe": sharpe(tlt),
                  "descriptive_TLT_ann_mean": float(tlt.mean() * 252)})
        res["candidates"][n] = s
        nets[n] = net
        daily_sr[n] = net.mean() / net.std(ddof=1)
        pd.DataFrame({"w_held": held, "net": net, "gross": gross, "stress": stress, "lag1": lag1,
                      "tlt_net": tlt}).to_csv(OUT / f"{mode}_{n}_daily.csv")
    if mode == "dev":
        var = float(np.var(list(daily_sr.values()), ddof=1))
        res["trial_sharpe_var"] = var
        res["event_study_IEF_excess"] = event_study(xr[win], auc, start, end)
        res["ief_excess_sharpe_window"] = sharpe(xr[win])
    else:
        var = json.loads((OUT / "dev_results.json").read_text())["trial_sharpe_var"]
    for n in names:
        res["candidates"][n]["deflated_sharpe_65"] = deflated_sharpe(nets[n].to_numpy(), N_TRIALS, var)

    if mode == "dev":
        res["selected"] = [n for n in names if res["candidates"][n]["sharpe"] >= DEV_GATE]
        for n in names:
            res["candidates"][n]["passes_dev_gate"] = n in res["selected"]
    else:
        pe = pead_excess()
        pe_scale = 0.10 / (pe.std(ddof=1) * np.sqrt(252))
        dev = json.loads((OUT / "dev_results.json").read_text())
        for n in names:
            r = res["candidates"][n]
            r["passes_validation"] = bool(r["sharpe"] >= VAL_GATE and r["stress_ann_mean"] > 0
                                          and r["p_one_sided"] < ALPHA and r["sharpe"] > BENCH)
            common = nets[n].index.intersection(pe.index)
            c_scale = 0.10 / dev["candidates"][n]["ann_vol"]
            ov = 0.5 * pe_scale * pe.loc[common] + 0.5 * c_scale * nets[n].loc[common]
            r["pead"] = {"common_days": int(len(common)),
                         "corr": float(np.corrcoef(pe.loc[common], nets[n].loc[common])[0, 1]),
                         "pead_sharpe_common": sharpe(pe.loc[common]),
                         "candidate_sharpe_common": sharpe(nets[n].loc[common]),
                         "blend_sharpe": sharpe(ov), "blend_ci95": sharpe_ci(ov.to_numpy(), 252, block=BLOCK)}
    (OUT / f"{mode}_results.json").write_text(json.dumps(res, indent=2, default=float))
    return res


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    out = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    print(json.dumps(out, indent=2, default=float))
