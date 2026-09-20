"""Metrics, the equal-risk combination rule from PLAN.md, and the development run.

Run (development window only; the hold-out is locked by panel.resolve_end):
    PYTHONPATH=. .venv/bin/python -m research.multiasset.evaluate
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.multiasset import panel, sleeves

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/multiasset"
SLEEVE_VOL = 0.10
BOOK_VOL = 0.10
MAX_SCALE = 4.0
MIN_SHARPE = 0.30
MIN_YEARS = 3.0


def hac_t(x: pd.Series, lags: int = 20) -> float:
    """Newey-West t-statistic of the mean."""
    x = x.dropna().to_numpy()
    n = len(x)
    if n < lags + 2:
        return float("nan")
    e = x - x.mean()
    lrv = e @ e / n
    for lag in range(1, lags + 1):
        lrv += 2 * (1 - lag / (lags + 1)) * (e[lag:] @ e[:-lag]) / n
    return float(x.mean() / np.sqrt(lrv / n))


def vol_scale(r: pd.Series, target: float) -> pd.Series:
    """Scale to target vol with trailing 252-day realized vol, decided two sessions before use."""
    vol = r.rolling(252, min_periods=126).std() * np.sqrt(252)
    scale = (target / vol).clip(upper=MAX_SCALE).shift(2)
    return (r * scale).dropna()


def stats(excess: pd.Series, rf: pd.Series, spy_excess: pd.Series) -> dict:
    x = excess.dropna()
    if len(x) < 60:
        return {"days": len(x)}
    years = len(x) / 252
    total = (1 + x + rf.reindex(x.index).fillna(0)).cumprod()
    wealth = (1 + x).cumprod()
    dd = (wealth / wealth.cummax() - 1).min()
    m = spy_excess.reindex(x.index)
    ok = m.notna()
    beta = float(np.cov(x[ok], m[ok])[0, 1] / m[ok].var()) if ok.sum() > 60 else float("nan")
    alpha = x - beta * m.fillna(0)
    return {
        "start": str(x.index[0].date()), "end": str(x.index[-1].date()), "years": round(years, 2),
        "sharpe": round(float(x.mean() / x.std() * np.sqrt(252)), 3),
        "ann_excess": round(float(x.mean() * 252), 4),
        "vol": round(float(x.std() * np.sqrt(252)), 4),
        "cagr_total": round(float(total.iloc[-1] ** (1 / years) - 1), 4),
        "max_dd": round(float(dd), 4),
        "hac_t": round(hac_t(x), 2),
        "beta_spy": round(beta, 3),
        "alpha_hac_t": round(hac_t(alpha), 2),
        "worst_day": round(float(x.min()), 4),
    }


def combine(sleeve_returns: dict[str, pd.Series]) -> pd.Series:
    scaled = pd.DataFrame({k: vol_scale(v, SLEEVE_VOL) for k, v in sleeve_returns.items()})
    book = scaled.mean(axis=1, skipna=True)  # equal risk across the sleeves alive that day
    return vol_scale(book, BOOK_VOL)


def code_hash() -> str:
    h = hashlib.sha256()
    for f in ("panel.py", "sleeves.py", "evaluate.py"):
        h.update((Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


def active(res: pd.DataFrame) -> pd.Series:
    """Net excess returns from the first day the sleeve holds anything."""
    live = res.index[res.gross_exposure > 0]
    return res.net[res.index >= live[0]] if len(live) else res.net.iloc[:0]


def run_dev() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rf = panel.risk_free(panel.DEV_END)
    spy = panel.etf_returns(panel.DEV_END)["SPY"] - rf
    results, series = {}, {}
    trials = OUT / "dev_trials.jsonl"
    logged = {json.loads(l)["sleeve"] for l in trials.read_text().splitlines()} if trials.exists() else set()
    for name, fn in sleeves.SLEEVES.items():
        t0 = time.time()
        res = fn(panel.DEV_END)
        r = active(res)
        series[name] = r
        s_raw = stats(r, rf, spy)
        s_scaled = stats(vol_scale(r, SLEEVE_VOL), rf, spy)
        s_raw["avg_cost_bps_per_year"] = round(float(res.cost.loc[r.index].mean() * 252 * 1e4), 1)
        s_raw["avg_gross_exposure"] = round(float(res.gross_exposure.loc[r.index].mean()), 2)
        included = bool(s_raw.get("sharpe", -9) >= MIN_SHARPE and s_raw.get("years", 0) >= MIN_YEARS)
        results[name] = {"raw": s_raw, "scaled_10pct": s_scaled, "included": included}
        print(f"{name:18s} {json.dumps(s_raw)}  [{time.time() - t0:.0f}s]")
        if name not in logged:   # every sleeve is a trial once; reruns of the same spec are not new tries
            with open(trials, "a") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "window": "development",
                                    "sleeve": name, "code_sha256": code_hash(), "stats": s_raw,
                                    "passes_inclusion_rule": included}) + "\n")

    pd.DataFrame(series).to_csv(OUT / "dev_sleeve_returns.csv")
    corr = pd.DataFrame({k: vol_scale(v, SLEEVE_VOL) for k, v in series.items()}).corr().round(2)
    corr.to_csv(OUT / "dev_correlations.csv")
    # PLAN_ADDENDUM_1: only the best of the near-duplicate TSMOM variants may enter
    tsm = [k for k in sleeves.TSMOM_VARIANTS if k in results]
    best_tsm = max(tsm, key=lambda k: results[k]["raw"].get("sharpe", -9)) if tsm else None
    for k in tsm:
        if k != best_tsm:
            results[k]["included"] = False
    chosen = [k for k, v in results.items() if v["included"]]
    book = combine({k: series[k] for k in chosen})
    everything = combine({k: v for k, v in series.items() if k not in tsm or k == best_tsm})
    summary = {"included": chosen, "book": stats(book, rf, spy),
               "all_candidates_descriptive": stats(everything, rf, spy),
               "sleeves": results, "correlations": corr.to_dict(), "code_sha256": code_hash()}
    (OUT / "dev_results.json").write_text(json.dumps(summary, indent=2))
    print("\nincluded:", chosen)
    print("book (dev):", json.dumps(summary["book"]))
    print("all candidates, one TSMOM (dev, descriptive):", json.dumps(summary["all_candidates_descriptive"]))
    print(corr.to_string())
    return summary


if __name__ == "__main__":
    run_dev()
