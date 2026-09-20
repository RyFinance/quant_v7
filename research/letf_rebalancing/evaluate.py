"""Development / validation runs for research/letf_rebalancing/PLAN.md.

  PYTHONPATH=. .venv/bin/python -m research.letf_rebalancing.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.letf_rebalancing.evaluate validation   # needs the registered unlock
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.intraday.evaluate import daily_table, load_bars, roll_days
from research.options_signals.evaluate import block_bootstrap_p

ROOT = Path(__file__).resolve().parents[2]
AUM_DIR = ROOT / "data" / "letf_proshares"
OUT = ROOT / "reports" / "letf_rebalancing"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/letf_rebalancing/VALIDATION_UNLOCK.md"
PEAD_BENCH = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

INSTR = {"ES": "ES_F", "NQ": "NQ_F"}
MULT = {"ES": 50.0, "NQ": 20.0}
FUNDS = {"NQ": {"TQQQ": 3, "SQQQ": -3, "QLD": 2, "QID": -2, "PSQ": -1},
         "ES": {"UPRO": 3, "SPXU": -3, "SSO": 2, "SDS": -2, "SH": -1}}
DEV = (pd.Timestamp("2016-06-01"), pd.Timestamp("2020-12-31"))
VAL = (pd.Timestamp("2021-01-01"), pd.Timestamp("2026-09-17"))
COSTS = {"base": 0.5e-4, "stress": 1.5e-4}
CANDIDATES = ["L1_flow_top_quintile", "L2_flow_scaled"]
DEV_GATE, VAL_GATE, ALPHA, BENCHMARK = 0.5, 0.75, 0.05 / 2, 0.70
MIN_HIST, VOL_WIN, CAP = 60, 20, 3.0
N_TRIALS, TRIAL_SR_VAR = 60, 0.25 / 252


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


# -- inputs -------------------------------------------------------------------------------------------
def load_aum(ticker: str) -> pd.Series:
    d = pd.read_csv(AUM_DIR / f"{ticker}.csv")
    d["Date"] = pd.to_datetime(d["Date"], format="%m/%d/%Y")
    return d.set_index("Date").sort_index()["Assets Under Management"].astype(float)


def gamma_dollars(funds: dict[str, int], aum: dict[str, pd.Series] | None = None) -> pd.Series:
    """Sum of AUM_i * L_i (L_i - 1) on each ProShares file date (end of that day)."""
    aum = aum or {t: load_aum(t) for t in funds}
    parts = [aum[t] * L * (L - 1) for t, L in funds.items()]
    return pd.concat(parts, axis=1).sort_index().ffill().sum(axis=1, min_count=1).dropna()


def prior_close_value(s: pd.Series, days: pd.DatetimeIndex) -> pd.Series:
    """Latest value of s dated strictly before each day (known at the prior close)."""
    left = pd.DataFrame({"day": days})
    right = pd.DataFrame({"d": s.index, "v": s.to_numpy()}).sort_values("d")
    m = pd.merge_asof(left, right, left_on="day", right_on="d", allow_exact_matches=False)
    return pd.Series(m["v"].to_numpy(), index=days)


def last_bar_volume(bars: pd.DataFrame) -> pd.Series:
    b = bars[bars["ts"].dt.strftime("%H:%M") == "15:30"]
    return b.set_index(b["ts"].dt.normalize())["volume"].astype(float)


def signal_table(bars: pd.DataFrame, gamma: pd.Series, mult: float) -> pd.DataFrame:
    t = daily_table(bars)
    vol = last_bar_volume(bars).reindex(t.index)
    notional = vol * t["p1600"] * mult
    t["vbar"] = notional.rolling(VOL_WIN, min_periods=VOL_WIN).median().shift(1)  # excludes day t
    t["gamma_prev"] = prior_close_value(gamma, t.index)
    t["flow"] = t["gamma_prev"] * t["rest_of_day"].pipe(np.expm1)  # r_t = P(15:30)/P_prev(16:00) - 1
    t["phi"] = t["flow"].abs() / t["vbar"]
    return t


def expanding_refs(phi: pd.Series) -> pd.DataFrame:
    """Per day: 20/40/50/60/80th percentiles of phi on all earlier valid days (>= MIN_HIST of them)."""
    vals = phi.to_numpy()
    out = np.full((len(vals), 5), np.nan)
    hist: list[float] = []
    for i, v in enumerate(vals):
        if len(hist) >= MIN_HIST:
            out[i] = np.percentile(hist, [20, 40, 50, 60, 80])
        if np.isfinite(v):
            hist.append(v)
    return pd.DataFrame(out, index=phi.index, columns=["p20", "p40", "p50", "p60", "p80"])


def positions(t: pd.DataFrame) -> dict[str, pd.Series]:
    ref = expanding_refs(t["phi"])
    sgn = np.sign(t["flow"])
    ok = ref["p80"].notna() & t["phi"].notna()
    l1 = (sgn * (t["phi"] >= ref["p80"])).where(ok)
    l2 = (sgn * np.minimum(t["phi"] / ref["p50"], CAP)).where(ok)
    bucket = (t["phi"].to_numpy()[:, None] >= ref[["p20", "p40", "p60", "p80"]].to_numpy()).sum(axis=1) + 1
    return {"L1_flow_top_quintile": l1, "L2_flow_scaled": l2,
            "bucket": pd.Series(np.where(ok, bucket, np.nan), index=t.index)}


def book(tables, pos, cost_side, days) -> pd.Series:
    parts = []
    for n, t in tables.items():
        p = pos[n].reindex(days).fillna(0.0)
        parts.append(0.5 * (p * t["r_last"].reindex(days) - p.abs() * 2 * cost_side))
    return pd.concat(parts, axis=1).fillna(0.0).sum(axis=1)


# -- statistics ---------------------------------------------------------------------------------------
def summarize(r: pd.Series, gross: pd.Series, rf: pd.Series) -> dict:
    x = r.to_numpy()
    ci = sharpe_ci(x, 252, block=21)
    nav = np.cumprod(1 + x)
    active = r != 0
    tot = (1 + r + rf.reindex(r.index).fillna(0.0)).prod() ** (252 / len(r)) - 1
    return {"days": int(len(r)), "active_days": int(active.sum()),
            "sharpe_net": float(x.mean() / x.std(ddof=1) * np.sqrt(252)),
            "sharpe_gross": float(gross.mean() / gross.std(ddof=1) * np.sqrt(252)),
            "sharpe_ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5),
            "deflated_sharpe_60_trials": deflated_sharpe(x, N_TRIALS, TRIAL_SR_VAR),
            "ann_mean": float(x.mean() * 252), "ann_vol": float(x.std(ddof=1) * np.sqrt(252)),
            "cagr_excess": float(nav[-1] ** (252 / len(x)) - 1), "cagr_with_cash_rf": float(tot),
            "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
            "hit_rate_active": float((r[active] > 0).mean()) if active.any() else None,
            "bootstrap_p_one_sided": block_bootstrap_p(x, block=21),
            "by_year": {int(y): float(np.prod(1 + v) - 1) for y, v in r.groupby(r.index.year)}}


def dose_response(tables, pos, days) -> dict:
    out = {}
    rows = []
    for n, t in tables.items():
        b = pos[n]["bucket"].reindex(days)
        s = np.sign(t["flow"].reindex(days)) * t["r_last"].reindex(days)
        rows.append(pd.DataFrame({"bucket": b, "sr": s, "instr": n}))
    df = pd.concat(rows).dropna()
    for scope, d in [("pooled", df)] + [(n, df[df["instr"] == n]) for n in tables]:
        g = {}
        for q in range(1, 6):
            v = d.loc[d["bucket"] == q, "sr"]
            g[q] = {"n": int(len(v)), "mean_bp": float(v.mean() * 1e4) if len(v) else None,
                    "t": float(v.mean() / v.std(ddof=1) * np.sqrt(len(v))) if len(v) > 2 else None,
                    "hit": float((v > 0).mean()) if len(v) else None}
        means = [g[q]["mean_bp"] for q in range(1, 6)]
        rho = spearmanr(range(1, 6), means).statistic if all(m is not None for m in means) else None
        out[scope] = {"buckets": g, "q5_minus_q1_bp": (means[4] - means[0]) if None not in (means[0], means[4]) else None,
                      "spearman": float(rho) if rho is not None else None,
                      "grows_with_flow": bool(rho is not None and rho > 0 and means[4] - means[0] > 0)}
    return out


def run(mode: str) -> dict:
    if mode == "dev":
        (start, end), selected = DEV, CANDIDATES
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} first")
        start, end = VAL
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not selected:
            raise SystemExit("development selected nothing")
    else:
        raise SystemExit("mode must be dev or validation")
    tables = {n: signal_table(load_bars(f, end), gamma_dollars(FUNDS[n]), MULT[n]) for n, f in INSTR.items()}
    common = tables["ES"].index.intersection(tables["NQ"].index)
    rolls = roll_days(common)
    for n in tables:
        tables[n] = tables[n].reindex(common)
    pos = {n: positions(t) for n, t in tables.items()}
    window = common[(common >= start) & (common <= end)]
    tradable = window.difference(rolls)
    from research.options_signals.signals import french_daily
    rf = french_daily()["rf"]
    bench = None
    if PEAD_BENCH.exists():
        c = pd.read_csv(PEAD_BENCH, index_col=0, parse_dates=True)
        bench = c["mtm_rf"].pct_change() - c["rf_index"].pct_change()
    out = OUT / mode
    out.mkdir(parents=True, exist_ok=True)
    res = {"mode": mode, "window": [str(start.date()), str(end.date())],
           "roll_days_excluded": int(len(window.intersection(rolls))), "tradable_days": int(len(tradable)),
           "gamma_by_year_bn": {n: {int(y): float(v / 1e9) for y, v in t["gamma_prev"].reindex(window).groupby(window.year).mean().items()}
                                for n, t in tables.items()},
           "phi_median_by_year": {n: {int(y): float(v) for y, v in t["phi"].reindex(window).groupby(window.year).median().items()}
                                  for n, t in tables.items()},
           "dose_response": dose_response(tables, pos, tradable), "candidates": {}}
    for name in selected:
        p = {n: pos[n][name].reindex(tradable) for n in tables}
        gross = book(tables, p, 0.0, window)
        res["candidates"][name] = {}
        for label, cs in COSTS.items():
            r = book(tables, p, cs, window)
            s = summarize(r, gross, rf)
            if bench is not None:
                both = pd.concat([r, bench], axis=1, join="inner").dropna()
                s["corr_with_pead_benchmark"] = float(both.corr().iloc[0, 1]) if len(both) > 60 else None
            s["mean_abs_position"] = float(np.mean([p[n].fillna(0).abs().mean() for n in tables]))
            res["candidates"][name][label] = s
            r.to_csv(out / f"{name}_{label}_daily.csv")
    if mode == "dev":
        sel = [n for n in selected if res["candidates"][n]["base"]["sharpe_net"] >= DEV_GATE]
        (out / "selection.json").write_text(json.dumps({"selected": sel}, indent=1))
        res["selected"] = sel
    else:
        for n in selected:
            b, s = res["candidates"][n]["base"], res["candidates"][n]["stress"]
            b["passes"] = bool(b["sharpe_net"] >= VAL_GATE and s["ann_mean"] > 0 and b["bootstrap_p_one_sided"] < ALPHA
                               and b["sharpe_net"] > BENCHMARK)
    res["code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = run(sys.argv[1] if len(sys.argv) > 1 else "dev")
    print("roll days excluded", r["roll_days_excluded"], "| tradable", r["tradable_days"])
    print("gamma bn", json.dumps(r["gamma_by_year_bn"]))
    print("phi median", json.dumps(r["phi_median_by_year"]))
    for sc, d in r["dose_response"].items():
        print(f"dose {sc:6s}", " ".join(f"Q{q}:{v['mean_bp']:+.2f}bp(t{v['t']:+.1f},n{v['n']})" for q, v in d["buckets"].items()),
              f"| Q5-Q1 {d['q5_minus_q1_bp']:+.2f} rho {d['spearman']:+.2f}")
    for n, v in r["candidates"].items():
        b, s = v["base"], v["stress"]
        print(f"{n:22s} net {b['sharpe_net']:+.2f} CI [{b['sharpe_ci95'][0]:+.2f},{b['sharpe_ci95'][1]:+.2f}] gross {b['sharpe_gross']:+.2f} "
              f"stress {s['sharpe_net']:+.2f} | ann {b['ann_mean']:+.2%} vol {b['ann_vol']:.1%} maxDD {b['max_drawdown']:.1%} "
              f"hit {b['hit_rate_active']} active {b['active_days']} p {b['bootstrap_p_one_sided']:.3f} "
              f"DSR {b['deflated_sharpe_60_trials']:.3f} corrPEAD {b.get('corr_with_pead_benchmark')}")
        print("   by year", {y: round(x, 4) for y, x in b["by_year"].items()})
    print("selected:", r.get("selected"))
