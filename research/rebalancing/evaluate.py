"""Development and validation runs for research/rebalancing/PLAN.md.

  PYTHONPATH=. .venv/bin/python -m research.rebalancing.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.rebalancing.evaluate validation   # needs the unlock

The development run truncates the price inputs at DEV_END before any signal is computed. The
validation run refuses to start unless research/rebalancing/VALIDATION_UNLOCK.md is registered with a
matching hash, and evaluates only candidates the development run selected.
"""
from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import pandas as pd

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.options_signals.evaluate import block_bootstrap_p
from research.options_signals.signals import french_daily
from research.rebalancing import signals as sg

ROOT = sg.ROOT
OUT = ROOT / "reports" / "rebalancing"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/rebalancing/VALIDATION_UNLOCK.md"
PEAD = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

DEV_START, DEV_END = pd.Timestamp("2003-02-03"), pd.Timestamp("2014-12-31")
VAL_START, VAL_END = pd.Timestamp("2015-01-01"), pd.Timestamp("2026-09-18")
CANDIDATES = ["R1_calendar", "R2_threshold", "R3_combined"]
COSTS = {"base": 0.0002, "stress": 0.0006}  # per side, per leg
DEV_GATE, VAL_GATE, BENCH = 0.5, 0.75, 0.70
ALPHA = 0.05 / len(CANDIDATES)
BLOCK, N_TRIALS = 21, 60


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


def backtest(w: pd.Series, r: pd.Series, per_side: float, lag: int = 0) -> pd.Series:
    """Position w_t set at close t earns r_{t+1}; cost 2 legs x per_side x |w_t - w_{t-1}| on t+1."""
    w = w.shift(lag).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    cost = 2 * per_side * w.diff().abs().fillna(w.abs()).shift(1).fillna(0.0)
    return held * r - cost


def sharpe(x) -> float:
    x = np.asarray(x, float)
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan")


def summarize(net: pd.Series, held: pd.Series) -> dict:
    x = net.to_numpy()
    nav = (1 + net).cumprod()
    active = held != 0
    ci = sharpe_ci(x, 252, block=BLOCK)
    return {
        "days": int(len(x)), "active_days": int(active.sum()),
        "sharpe": sharpe(x), "ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5),
        "p_one_sided": block_bootstrap_p(x, block=BLOCK),
        "ann_mean": float(x.mean() * 252), "ann_vol": float(x.std(ddof=1) * np.sqrt(252)),
        "max_dd": float((nav / nav.cummax() - 1).min()),
        "hit_rate_active": float((net[active] > 0).mean()) if active.any() else float("nan"),
        "mean_bp_per_active_day": float(net[active].mean() * 1e4) if active.any() else float("nan"),
        "position_changes": int((held.diff().abs() > 1e-12).sum()),
        "max_abs_w": float(held.abs().max()),
        "by_year": {int(k): float(v) for k, v in net.groupby(net.index.year).apply(lambda s: (1 + s).prod() - 1).items()},
    }


def pead_excess() -> pd.Series:
    c = pd.read_csv(PEAD, index_col=0, parse_dates=True)
    return (c["mtm_rf"].pct_change() - c["rf_index"].pct_change()).dropna()


def run(mode: str) -> dict:
    if mode == "dev":
        ret = sg.load_returns(upto=DEV_END)
        start, end, names = DEV_START, DEV_END, CANDIDATES
    else:
        if not validation_unlocked():
            raise SystemExit(f"validation locked: register {UNLOCK} first")
        dev = json.loads((OUT / "dev_results.json").read_text())
        names = dev["selected"]
        if not names:
            raise SystemExit("no candidate passed development")
        ret = sg.load_returns()
        start, end = VAL_START, VAL_END
    pos = sg.positions(ret)
    spread = ret["SPY"] - ret["IEF"]
    rf = french_daily()["rf"]
    rf = rf.reindex(rf.index.union(ret.index)).ffill().reindex(ret.index)
    win = (ret.index >= start) & (ret.index <= end)

    res = {"mode": mode, "window": [str(start.date()), str(end.date())], "candidates": {}}
    nets, daily_sr = {}, {}
    frames = {}
    for n in names:
        w = pos[n]
        held = w.shift(1).fillna(0.0)[win]
        net = backtest(w, spread, COSTS["base"])[win]
        gross = backtest(w, spread, 0.0)[win]
        stress = backtest(w, spread, COSTS["stress"])[win]
        lag1 = backtest(w, spread, COSTS["base"], lag=1)[win]
        eq_only = (held * (ret["SPY"] - rf)[win]
                   - COSTS["base"] * w.diff().abs().fillna(0).shift(1).fillna(0)[win])
        s = summarize(net, held)
        s.update({"sharpe_gross": sharpe(gross), "stress_sharpe": sharpe(stress),
                  "stress_ann_mean": float(stress.mean() * 252),
                  "descriptive_lag1_sharpe": sharpe(lag1), "descriptive_equity_only_sharpe": sharpe(eq_only),
                  "ann_cost_drag": float((gross - net).mean() * 252)})
        res["candidates"][n] = s
        nets[n] = net
        daily_sr[n] = net.mean() / net.std(ddof=1)
        frames[n] = pd.DataFrame({"w_held": held, "net": net, "gross": gross, "stress": stress, "lag1": lag1})
        frames[n].to_csv(OUT / f"{mode}_{n}_daily.csv")
    var = float(np.var(list(daily_sr.values()), ddof=1)) if len(daily_sr) > 1 else 0.0
    if mode == "dev":
        # the dev run always holds all three candidates, so the trial variance is recorded for validation
        res["trial_sharpe_var"] = var
    else:
        var = json.loads((OUT / "dev_results.json").read_text())["trial_sharpe_var"]
    for n in names:
        res["candidates"][n]["deflated_sharpe_60"] = deflated_sharpe(nets[n].to_numpy(), N_TRIALS, var)

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
                         "overlay_sharpe": sharpe(ov), "overlay_ci95": sharpe_ci(ov.to_numpy(), 252, block=BLOCK)}
    (OUT / f"{mode}_results.json").write_text(json.dumps(res, indent=2, default=float))
    return res


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    out = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    print(json.dumps(out, indent=2, default=float))
