"""Development and validation runs for research/etf_hybrids/PLAN.md.

  PYTHONPATH=. .venv/bin/python -m research.etf_hybrids.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.etf_hybrids.evaluate validation   # needs the unlock

The development run truncates every price input (and the rate series) at DEV_END before any signal
is computed. The validation run refuses to start unless research/etf_hybrids/VALIDATION_UNLOCK.md is
registered, with a matching hash, in research/preregistrations.jsonl; it evaluates only candidates the
development run selected, and refuses to overwrite an earlier validation result.
"""
from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import pandas as pd

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.etf_hybrids import signals as sg
from research.options_signals.evaluate import block_bootstrap_p
from research.options_signals.signals import french_daily

ROOT = sg.ROOT
OUT = ROOT / "reports" / "etf_hybrids"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/etf_hybrids/VALIDATION_UNLOCK.md"
PEAD = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

DEV_SIGNALS = (pd.Timestamp("2002-12-31"), pd.Timestamp("2014-11-28"))
DEV_END = pd.Timestamp("2014-12-31")
VAL_SIGNALS = (pd.Timestamp("2014-12-31"), pd.Timestamp("2026-08-31"))
VAL_END = pd.Timestamp("2026-09-18")
U_FIRST_SIGNAL = pd.Timestamp("2000-01-31")   # first month with both halves eligible

CANDIDATES = ["E1", "E2", "E3", "E4", "E5"]
REFERENCES = ["B", "R0", "SPY"]
STRESS_MULT = 3.0
DEV_GATE, VAL_GATE, PEAD_BENCH = 0.50, 0.75, 0.70
ALPHA = 0.05 / len(CANDIDATES)
BLOCK, DRAWS, SEED = 63, 5000, 20260918
N_TRIALS, FIXED_TRIAL_SR_ANNUAL = 80, 0.5
NW_LAGS = 20


# -- guard (copied from research/options_signals/evaluate.py) -------------------------------------------
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


# -- daily marking ---------------------------------------------------------------------------------------
def mark(schedule: dict, opens: pd.DataFrame, closes: pd.DataFrame, rf: pd.Series, end: pd.Timestamp,
         costs: pd.Series) -> pd.DataFrame:
    """schedule: entry session -> target weights (fractions of NAV). Rebalance day: old book
    close->open, trade at the open, new book open->close; other days close->close. Cash earns the
    day's rf (after the open on a rebalance day). Returns per session: gross return, the cost as a
    fraction of NAV at the open (net = (1+gross)(1-cost)-1), turnover, risky exposure and holdings."""
    names = list(closes.columns)
    cal = closes.index
    entries = sorted(schedule)
    days = cal[(cal >= entries[0]) & (cal <= end)]
    pos = {d: i for i, d in enumerate(cal)}
    O, C = opens.to_numpy(float), closes.to_numpy(float)
    rfv = rf.reindex(cal).to_numpy(float)
    cvec = costs.reindex(names).fillna(0.0).to_numpy(float)
    w, cash = np.zeros(len(names)), 1.0
    out = np.zeros((len(days), 5))
    for j, d in enumerate(days):
        i = pos[d]
        r_f = rfv[i]
        held = w != 0
        if d in schedule:
            ratio = np.ones(len(names))
            ratio[held] = O[i, held] / C[i - 1, held]
            if not np.all(np.isfinite(ratio)):
                raise ValueError(f"missing open/close for a held ETF on {d.date()}")
            g_on = float(w @ ratio) + cash
            drift = w * ratio / g_on
            target = schedule[d].reindex(names).fillna(0.0).to_numpy(float)
            dw = np.abs(target - drift)
            cost = float(dw @ cvec)
            tgt = target != 0
            day = np.ones(len(names))
            day[tgt] = C[i, tgt] / O[i, tgt]
            if not np.all(np.isfinite(day)):
                raise ValueError(f"missing open/close for a target ETF on {d.date()}")
            cash_new = 1.0 - float(target.sum())
            g_day = float(target @ day) + cash_new * (1.0 + r_f)
            gross = g_on * g_day - 1.0
            w, cash = target * day / g_day, cash_new * (1.0 + r_f) / g_day
            out[j] = (gross, cost, float(dw.sum()), 0.0, 0.0)
        else:
            ratio = np.ones(len(names))
            ratio[held] = C[i, held] / C[i - 1, held]
            if not np.all(np.isfinite(ratio)):
                raise ValueError(f"missing close for a held ETF on {d.date()}")
            g = float(w @ ratio) + cash * (1.0 + r_f)
            w, cash = w * ratio / g, cash * (1.0 + r_f) / g
            out[j] = (g - 1.0, 0.0, 0.0, 0.0, 0.0)
        out[j, 3] = float(w.sum())
        out[j, 4] = float((w > 1e-12).sum())
    f = pd.DataFrame(out, index=days, columns=["gross", "cost", "turnover", "exposure", "holdings"])
    f["rf"] = rf.reindex(days).to_numpy(float)
    return f


def with_costs(f: pd.DataFrame, mult: float = 1.0) -> pd.Series:
    return (1.0 + f["gross"]) * (1.0 - mult * f["cost"]) - 1.0


def excess_frame(f: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"net_ex": with_costs(f) - f["rf"], "gross_ex": f["gross"] - f["rf"],
                         "stress_ex": with_costs(f, STRESS_MULT) - f["rf"], "net_total": with_costs(f),
                         "cost": f["cost"], "turnover": f["turnover"], "exposure": f["exposure"],
                         "holdings": f["holdings"]})


def vol_scale(u_gross_ex: pd.Series, d: pd.Timestamp) -> float:
    """E1: s = min(1, 0.12 / sigma), sigma = sqrt(252 x mean squared daily gross excess return of U over
    the 126 sessions ending at d)."""
    x = u_gross_ex.loc[:d].iloc[-sg.VOL_WINDOW:]
    if len(x) < sg.VOL_WINDOW:
        raise ValueError(f"U has only {len(x)} sessions before {d.date()}")
    sigma = float(np.sqrt(252.0 * np.mean(np.square(x.to_numpy()))))
    return min(1.0, sg.VOL_TARGET / sigma) if sigma > 0 else 1.0


# -- statistics ------------------------------------------------------------------------------------------
def sharpe(x) -> float:
    x = np.asarray(x, float)
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan")


def _row_sharpe(a: np.ndarray) -> np.ndarray:
    return a.mean(axis=1) / a.std(axis=1, ddof=1) * np.sqrt(252)


def paired_sharpe_p(x: np.ndarray, y: np.ndarray, block: int = BLOCK, draws: int = DRAWS, seed: int = SEED,
                    chunk: int = 500) -> float:
    """One-sided p for H0: Sharpe(x) <= Sharpe(y). Paired circular block bootstrap of the daily pairs;
    p = share of centred resampled differences >= the observed difference."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    obs = sharpe(x) - sharpe(y)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(draws, nb))
    hits = 0
    for a in range(0, draws, chunk):
        s = starts[a:a + chunk]
        idx = (s[:, :, None] + np.arange(block)[None, None, :]).reshape(len(s), -1)[:, :n] % n
        diff = _row_sharpe(x[idx]) - _row_sharpe(y[idx])
        hits += int(np.sum(diff - obs >= obs))
    return float((hits + 1) / (draws + 1))


def ols_hac(y: np.ndarray, x: np.ndarray, lags: int = NW_LAGS) -> tuple[np.ndarray, np.ndarray]:
    X = np.column_stack([np.ones(len(x)), x])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    xe = X * e[:, None]
    S = xe.T @ xe
    for L in range(1, lags + 1):
        G = xe[L:].T @ xe[:-L]
        S += (1 - L / (lags + 1)) * (G + G.T)
    inv = np.linalg.inv(X.T @ X)
    V = inv @ S @ inv
    return b, np.sqrt(np.diag(V))


def by_year(x: pd.Series) -> dict:
    return {int(k): float(v) for k, v in x.groupby(x.index.year).apply(lambda s: (1 + s).prod() - 1).items()}


def summarize(ex: pd.DataFrame, bench: pd.DataFrame | None, spy_gross_ex: pd.Series, targets: dict) -> dict:
    x = ex["net_ex"]
    xv = x.to_numpy()
    years = (x.index[-1] - x.index[0]).days / 365.25
    ci = sharpe_ci(xv, 252, block=BLOCK, draws=DRAWS)
    b_spy, se_spy = ols_hac(xv, spy_gross_ex.reindex(x.index).to_numpy())
    nav_ex, nav_tot = (1 + x).cumprod(), (1 + ex["net_total"]).cumprod()
    tsum = np.array([float(w.sum()) for w in targets.values()])
    s = {
        "days": int(len(x)), "start": str(x.index[0].date()), "end": str(x.index[-1].date()),
        "sharpe_net": sharpe(xv), "ci95": list(ci), "null_kind_0.5": null_kind(ci, 0.5),
        "null_kind_0.70": null_kind(ci, 0.70),
        "p_one_sided": block_bootstrap_p(xv, block=BLOCK, draws=DRAWS),
        "sharpe_gross": sharpe(ex["gross_ex"]), "sharpe_stress": sharpe(ex["stress_ex"]),
        "ann_mean_net": float(x.mean() * 252), "ann_vol": float(x.std(ddof=1) * np.sqrt(252)),
        "stress_ann_mean": float(ex["stress_ex"].mean() * 252),
        "beta_spy": float(b_spy[1]), "alpha_spy_ann": float(b_spy[0] * 252), "alpha_spy_hac_t": float(b_spy[0] / se_spy[0]),
        "max_dd_excess": float((nav_ex / nav_ex.cummax() - 1).min()),
        "max_dd_total": float((nav_tot / nav_tot.cummax() - 1).min()),
        "annual_turnover": float(ex["turnover"].sum() / years),
        "annual_cost_drag": float((ex["gross_ex"] - x).mean() * 252),
        "mean_holdings": float(ex["holdings"].mean()), "mean_exposure": float(ex["exposure"].mean()),
        "rebalances": int(len(targets)), "rebalances_with_tbill_slot": int(np.sum(tsum < 1 - 1e-9)),
        "mean_target_exposure": float(tsum.mean()),
        "by_year_net_excess": by_year(x),
    }
    if bench is not None:
        bx = bench["net_ex"].reindex(x.index).to_numpy()
        a = xv - bx
        s["bench_sharpe_net"] = sharpe(bx)
        s["beats_bench_point"] = bool(s["sharpe_net"] > s["bench_sharpe_net"])
        s["beta_bench"] = float(ols_hac(xv, bx)[0][1])
        s["corr_bench"] = float(np.corrcoef(xv, bx)[0, 1])
        s["active_ann_mean"] = float(a.mean() * 252)
        s["tracking_error"] = float(a.std(ddof=1) * np.sqrt(252))
        s["info_ratio"] = sharpe(a)
        s["paired_sharpe_p_vs_B"] = paired_sharpe_p(xv, bx)
    return s


def pead_excess() -> pd.Series:
    c = pd.read_csv(PEAD, index_col=0, parse_dates=True)
    return (c["mtm_rf"].pct_change() - c["rf_index"].pct_change()).dropna()


# -- runs ------------------------------------------------------------------------------------------------
def rates(upto: pd.Timestamp | None, cal: pd.DatetimeIndex) -> pd.Series:
    rf = french_daily()["rf"]
    if upto is not None:
        rf = rf.loc[:upto]
    return rf.reindex(rf.index.union(cal)).ffill().reindex(cal)


def entry_after(cal: pd.DatetimeIndex, d: pd.Timestamp) -> pd.Timestamp:
    i = cal.searchsorted(d, side="right")
    return cal[i]


def build(mode: str) -> dict:
    if mode == "dev":
        upto, (s0, s1), end = DEV_END, DEV_SIGNALS, DEV_END
    else:
        upto, (s0, s1), end = VAL_END, VAL_SIGNALS, VAL_END
    panel = sg.load_panel(upto=upto)
    cal = panel["adj_close"].index
    rf = rates(upto, cal)
    sig = sg.signal_panels(panel, rf)
    me = sig["me"]
    dates = me[(me >= s0) & (me <= s1)]
    u_dates = me[(me >= U_FIRST_SIGNAL) & (me <= s1)]
    books = sg.target_books(sig, dates)
    u_books = sg.target_books(sig, u_dates)["R0"]
    costs = pd.Series(sg.COST_PER_SIDE)
    O, C = panel["adj_open"], panel["adj_close"]

    # U = unscaled 12-1 book, marked from the 2000-02-01 open, for E1's ex-ante volatility
    u = mark({entry_after(cal, d): w for d, w in u_books.items()}, O, C, rf, end, costs)
    u_gross_ex = u["gross"] - u["rf"]
    scales = {d: vol_scale(u_gross_ex, d) for d in dates}
    books["E1"] = {d: books["R0"][d] * scales[d] for d in dates}
    books["SPY"] = {d: pd.Series({"SPY": 1.0}) for d in dates}

    frames = {k: excess_frame(mark({entry_after(cal, d): w for d, w in v.items()}, O, C, rf, end, costs))
              for k, v in books.items()}
    elig = sig["eligible"].loc[dates]
    return {"books": books, "frames": frames, "scales": scales, "dates": dates, "window_end": end,
            "eligible_counts": {"sector": elig[sg.SECTORS].sum(axis=1), "country": elig[sg.COUNTRY].sum(axis=1)},
            "seas_valid": sig["seas"].loc[dates].where(elig).notna()}


def code_hashes() -> dict:
    files = ["research/etf_hybrids/signals.py", "research/etf_hybrids/evaluate.py", "research/etf_hybrids/pull.py",
             "data/etf_hybrids/manifest.json", "research/etf_hybrids/PLAN.md"]
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}


def run(mode: str) -> dict:
    if mode == "dev":
        names = CANDIDATES
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} in {PREREG.name} first")
        if (OUT / "validation" / "results.json").exists():
            raise SystemExit("validation already ran once; refusing to overwrite")
        names = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not names:
            raise SystemExit("development selected nothing; validation is not run")
    else:
        raise SystemExit("mode must be dev or validation")

    b = build(mode)
    fr = b["frames"]
    spy_gross_ex = fr["SPY"]["gross_ex"]
    res = {"mode": mode, "window": [str(fr["B"].index[0].date()), str(b["window_end"].date())],
           "signal_dates": [str(b["dates"][0].date()), str(b["dates"][-1].date())], "candidates": {}, "references": {}}
    for n in names:
        res["candidates"][n] = summarize(fr[n], fr["B"], spy_gross_ex, b["books"][n])
    for n in REFERENCES:
        res["references"][n] = summarize(fr[n], None if n == "B" else fr["B"], spy_gross_ex, b["books"][n])
    res["E1_scale"] = {"mean": float(np.mean(list(b["scales"].values()))), "min": float(min(b["scales"].values())),
                       "max": float(max(b["scales"].values())),
                       "share_at_cap": float(np.mean([s >= 1.0 - 1e-12 for s in b["scales"].values()]))}
    res["eligible_counts"] = {k: {"min": int(v.min()), "max": int(v.max())} for k, v in b["eligible_counts"].items()}
    sv = b["seas_valid"]
    res["E5_valid_counts"] = {"sector_min": int(sv[sg.SECTORS].sum(axis=1).min()),
                              "country_min": int(sv[sg.COUNTRY].sum(axis=1).min()),
                              "first_month_sector_ge3": str(sv.index[sv[sg.SECTORS].sum(axis=1) >= 3][0].date())}

    daily_sr = {n: float(fr[n]["net_ex"].mean() / fr[n]["net_ex"].std(ddof=1)) for n in names}
    if mode == "dev":
        var = float(np.var(list(daily_sr.values()), ddof=1))
        res["trial_sharpe_var_daily"] = var
    else:
        var = json.loads((OUT / "dev" / "results.json").read_text())["trial_sharpe_var_daily"]
    fixed_var = FIXED_TRIAL_SR_ANNUAL ** 2 / 252.0
    for n in names:
        x = fr[n]["net_ex"].to_numpy()
        res["candidates"][n]["deflated_sharpe_80_candidate_var"] = deflated_sharpe(x, N_TRIALS, var)
        res["candidates"][n]["deflated_sharpe_80_fixed_0.5"] = deflated_sharpe(x, N_TRIALS, fixed_var)

    if mode == "dev":
        sel = [n for n in names if res["candidates"][n]["sharpe_net"] >= DEV_GATE and res["candidates"][n]["beats_bench_point"]]
        for n in names:
            res["candidates"][n]["passes_dev_gate"] = n in sel
        res["selected"] = sel
    else:
        pe = pead_excess()
        for n in names:
            r = res["candidates"][n]
            r["passes_validation"] = bool(r["sharpe_net"] >= VAL_GATE and r["stress_ann_mean"] > 0
                                          and r["p_one_sided"] < ALPHA and r["sharpe_net"] > PEAD_BENCH
                                          and r["paired_sharpe_p_vs_B"] < ALPHA)
            common = fr[n].index.intersection(pe.index)
            r["pead"] = {"common_days": int(len(common)),
                         "corr": float(np.corrcoef(pe.loc[common], fr[n]["net_ex"].loc[common])[0, 1]),
                         "pead_sharpe_common": sharpe(pe.loc[common]),
                         "candidate_sharpe_common": sharpe(fr[n]["net_ex"].loc[common])}
    res["code_sha256"] = code_hashes()

    outdir = OUT / mode
    outdir.mkdir(parents=True, exist_ok=True)
    keep = names + REFERENCES
    daily = pd.concat({k: fr[k][["net_ex", "gross_ex", "stress_ex", "exposure", "holdings"]] for k in keep}, axis=1)
    daily.to_csv(outdir / "daily.csv")
    wrows = [{"book": k, "signal_date": str(d.date()), **{t: float(v) for t, v in w.items() if v != 0}}
             for k in keep for d, w in b["books"][k].items()]
    pd.DataFrame(wrows).to_csv(outdir / "weights.csv", index=False)
    if mode == "dev":
        (outdir / "selection.json").write_text(json.dumps(
            {"selected": res["selected"], "gate": f"net Sharpe >= {DEV_GATE} and above benchmark B"}, indent=1))
    (outdir / "results.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def table(res: dict) -> str:
    rows = []
    for grp in ("candidates", "references"):
        for n, r in res[grp].items():
            rows.append(f"{n:4s} SR {r['sharpe_net']:+.2f} [{r['ci95'][0]:+.2f},{r['ci95'][1]:+.2f}] gross {r['sharpe_gross']:+.2f} "
                        f"stress {r['sharpe_stress']:+.2f} mean {r['ann_mean_net']:+.1%} vol {r['ann_vol']:.1%} "
                        f"p {r['p_one_sided']:.3f} ddEx {r['max_dd_excess']:.0%} beta {r['beta_spy']:.2f} "
                        f"TO {r['annual_turnover']:.1f} "
                        + (f"vsB p {r['paired_sharpe_p_vs_B']:.3f} act {r['active_ann_mean']:+.1%} TE {r['tracking_error']:.1%}"
                           if "paired_sharpe_p_vs_B" in r else ""))
    return "\n".join(rows)


if __name__ == "__main__":
    out = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    print(table(out))
    print("selected:", out.get("selected"))
