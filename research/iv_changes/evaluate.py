"""Development and validation runs for the registered IV-change candidates (research/iv_changes/PLAN.md).

  PYTHONPATH=. .venv/bin/python -m research.iv_changes.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.iv_changes.evaluate validation   # needs the unlock

Names are processed one at a time (memory). The portfolio engine is the registered options-signals
backtest, imported unchanged and run on monthly signal dates.
"""
from __future__ import annotations

import gc
import hashlib
import json
import sys

import numpy as np
import pandas as pd

from research.iv_changes import atm_iv
from research.options_signals import evaluate as oev
from research.options_signals import signals as sg

ROOT = sg.ROOT
OUT = ROOT / "reports" / "iv_changes"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/iv_changes/VALIDATION_UNLOCK.md"

DEV_START, DEV_END = pd.Timestamp("2014-07-31"), pd.Timestamp("2019-12-31")
VAL_START, VAL_END = pd.Timestamp("2020-01-31"), pd.Timestamp("2026-09-30")
CANDIDATES = ("V1_dcall", "V2_dput", "V3_dspread")
COSTS = oev.COSTS
MIN_NAMES = oev.MIN_NAMES  # 25
DEV_GATE_SHARPE = 0.5
VAL_GATE_SHARPE, VAL_GATE_GROSS = 0.75, 0.70
BONFERRONI_ALPHA = 0.05 / 3
BLOCK, DRAWS, NW_LAGS = 3, 5000, 3
PRICE_TAIL_DAYS = 45


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


def month_end_dates(calendar: pd.DatetimeIndex, start, end) -> pd.DatetimeIndex:
    """Last trading day of each calendar month, judged on the whole calendar, then cut to [start, end]."""
    s = pd.Series(calendar, index=calendar)
    last = s.groupby([calendar.year, calendar.month]).max()
    d = pd.DatetimeIndex(sorted(last.to_numpy()))
    return d[(d >= start) & (d <= end)]


def complete_month_ends(calendar: pd.DatetimeIndex, start, end) -> pd.DatetimeIndex:
    """Month-end signal dates in [start, end], excluding the calendar's final month (possibly partial)."""
    d = month_end_dates(calendar, start, end)
    if len(calendar):
        last = calendar[-1]
        d = d[~((d.year == last.year) & (d.month == last.month))]
    return d


def iv_levels(names, upto, dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """5-day-mean 30d ATM IV at each date, one name at a time."""
    call, put = {}, {}
    for t in names:
        daily = atm_iv.daily_atm_iv(t, upto=upto)
        sm = atm_iv.smoothed(daily)
        call[t] = sm["call_iv30"].reindex(dates)
        put[t] = sm["put_iv30"].reindex(dates)
        del daily, sm
        gc.collect()
    return {"call": pd.DataFrame(call, index=dates), "put": pd.DataFrame(put, index=dates)}


def scores_from_levels(levels: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Changes between consecutive month-end signal dates (the frame's own rows)."""
    dcall = levels["call"].diff()
    dput = levels["put"].diff()
    return {"V1_dcall": dcall, "V2_dput": -dput, "V3_dspread": dcall - dput}


def summarize(bt: pd.DataFrame) -> dict:
    net, gross = bt["net"].to_numpy(), bt["gross"].to_numpy()
    active = bt["names_long"] > 0
    nav = np.cumprod(1.0 + net)
    years = max((bt["exit"].iloc[-1] - bt["entry"].iloc[0]).days / 365.25, 1e-9)
    dd = nav / np.maximum.accumulate(nav) - 1.0
    mean_turn = float(bt["turnover"].mean())
    by_year = bt.groupby(bt.index.year)["net"].apply(lambda s: float(np.prod(1 + s) - 1)).to_dict()
    sd = lambda x: x.std(ddof=1)
    return {
        "months": int(len(bt)), "active_months": int(active.sum()),
        "sharpe_net": float(net.mean() / sd(net) * np.sqrt(12)) if sd(net) > 0 else float("nan"),
        "sharpe_gross": float(gross.mean() / sd(gross) * np.sqrt(12)) if sd(gross) > 0 else float("nan"),
        "ann_mean_net": float(net.mean() * 12), "ann_vol": float(sd(net) * np.sqrt(12)),
        "excess_cagr": float(nav[-1] ** (1 / years) - 1), "max_drawdown": float(dd.min()),
        "annual_turnover": float(bt["turnover"].sum() / years),
        "annual_cost_drag": float((bt["cost"] + bt["borrow"] + bt["proceeds_drag"]).sum() / years),
        "breakeven_cost_per_side_bps": float(bt["gross"].mean() / mean_turn * 1e4) if mean_turn > 0 else None,
        "nw_t": oev.newey_west_t(net, lags=NW_LAGS),
        "bootstrap_p_one_sided": oev.block_bootstrap_p(net, block=BLOCK, draws=DRAWS),
        "avg_names_per_leg": float(bt.loc[active, ["names_long", "names_short"]].mean().mean()) if active.any() else 0.0,
        "by_year_net": {int(k): v for k, v in by_year.items()},
    }


def run(mode: str) -> dict:
    names = oev.universe()
    missing = [t for t in names if not (sg.OPT_DIR / f"{t}.parquet").exists()]
    if missing:
        raise SystemExit(f"option pull incomplete: {len(missing)} names missing ({missing[:5]}...)")
    if mode == "dev":
        start, end = DEV_START, DEV_END
        selected = list(CANDIDATES)
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} in {PREREG.name} first")
        start, end = VAL_START, VAL_END
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not selected:
            raise SystemExit("development selected nothing; validation is not run")
    else:
        raise SystemExit("mode must be dev or validation")

    price_upto = end + pd.Timedelta(days=PRICE_TAIL_DAYS)
    opens, closes = oev.load_opens(names, price_upto)
    calendar = opens.index[opens.notna().sum(axis=1) > len(names) // 2]
    opens, closes = opens.reindex(calendar), closes.reindex(calendar)
    # signal dates plus the previous month-end (for the first change) and the next (last exit)
    all_me = complete_month_ends(calendar, calendar[0], calendar[-1])
    sig = all_me[(all_me >= start) & (all_me <= end)]
    prev = all_me[all_me < start][-1:]
    nxt = all_me[all_me > end][:1]
    level_dates = prev.append(sig)
    levels = iv_levels(names, upto=end, dates=level_dates)
    scores = {k: v.loc[sig] for k, v in scores_from_levels(levels).items()}
    dates = sig.append(nxt)
    ff = sg.french_daily()
    rf_daily = ff["rf"].reindex(calendar.union(ff.index)).ffill().reindex(calendar)

    outdir = OUT / mode
    outdir.mkdir(parents=True, exist_ok=True)
    levels["call"].to_csv(outdir / "call_iv30_levels.csv")
    levels["put"].to_csv(outdir / "put_iv30_levels.csv")
    results = {"mode": mode, "window": [str(start.date()), str(end.date())], "candidates": {},
               "signal_dates": [str(sig[0].date()), str(sig[-1].date()), len(sig)]}
    for name in selected:
        results["candidates"][name] = {}
        for label, cost in COSTS.items():
            bt = oev.backtest(scores[name].reindex(calendar), opens, closes, dates, calendar, rf_daily, cost)
            bt.to_csv(outdir / f"{name}_{label}.csv")
            results["candidates"][name][label] = summarize(bt)
    results["mean_names_with_score"] = {n: float(s.notna().sum(axis=1).mean()) for n, s in scores.items()}

    if mode == "dev":
        sel = [n for n in selected if results["candidates"][n]["base"]["sharpe_net"] >= DEV_GATE_SHARPE]
        (outdir / "selection.json").write_text(json.dumps({"selected": sel, "gate": f"net base Sharpe >= {DEV_GATE_SHARPE}"}, indent=1))
        results["selected"] = sel
    else:
        for n in selected:
            b, s = results["candidates"][n]["base"], results["candidates"][n]["stress"]
            b["passes"] = bool(b["sharpe_net"] >= VAL_GATE_SHARPE and s["ann_mean_net"] > 0
                               and b["bootstrap_p_one_sided"] < BONFERRONI_ALPHA
                               and b["sharpe_gross"] >= VAL_GATE_GROSS)
    results["code_sha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
        "research/iv_changes/atm_iv.py", "research/iv_changes/evaluate.py",
        "research/options_signals/signals.py", "research/options_signals/evaluate.py")}
    data = json.loads((sg.OPT_DIR / "manifest.json").read_text())
    results["options_data_sha256"] = {t: data.get(t, {}).get("sha256") for t in names}
    (outdir / "results.json").write_text(json.dumps(results, indent=1, default=str))
    return results


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dev"
    r = run(mode)
    for n, v in r["candidates"].items():
        b, s = v["base"], v["stress"]
        print(f"{n:11s} net Sharpe {b['sharpe_net']:+.2f} (gross {b['sharpe_gross']:+.2f}, stress {s['sharpe_net']:+.2f}) "
              f"excess CAGR {b['excess_cagr']:+.2%} maxDD {b['max_drawdown']:.1%} p={b['bootstrap_p_one_sided']:.3f}")
    print("selected:", r.get("selected"))
