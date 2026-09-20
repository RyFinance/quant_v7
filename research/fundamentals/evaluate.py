"""Development and validation runs for research/fundamentals/PLAN.md (registered).

  PYTHONPATH=. .venv/bin/python -m research.fundamentals.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.fundamentals.evaluate validation   # needs the unlock
"""
from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import pandas as pd

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.fundamentals import signals as sg
from research.options_signals import evaluate as ev
from research.options_signals.signals import french_daily

ROOT = sg.ROOT
OUT = ROOT / "reports" / "fundamentals"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/fundamentals/VALIDATION_UNLOCK.md"
PEAD = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

WINDOWS = {"dev": ("2003-01-31", "2014-11-28"), "validation": ("2014-12-31", "2026-07-31")}
CANDS = ["F1_issuance", "F2_consistency", "F3_combined"]
DEV_GATE, VAL_GATE, BENCH = 0.5, 0.75, 0.70
ALPHA = 0.05 / 3
BLOCK = 6
N_TRIALS = 65
PPY = 12


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


def scores(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    f1 = panel.pivot(index="date", columns="ticker", values="f1")
    f2 = panel.pivot(index="date", columns="ticker", values="f2")
    s1, s2 = -f1, f2
    both = s1.notna() & s2.notna()
    r1 = s1.where(both).rank(axis=1, pct=True)
    r2 = s2.where(both).rank(axis=1, pct=True)
    return {"F1_issuance": s1, "F2_consistency": s2, "F3_combined": (r1 + r2) / 2}


def f3_scores_on_tradeable(s1, s2, tradeable: pd.DataFrame) -> pd.DataFrame:
    """F3 ranks among names with both signals AND an entry open (PLAN)."""
    both = s1.notna() & s2.notna() & tradeable
    return (s1.where(both).rank(axis=1, pct=True) + s2.where(both).rank(axis=1, pct=True)) / 2


def summarize(bt: pd.DataFrame) -> dict:
    net, gross = bt["net"].to_numpy(), bt["gross"].to_numpy()
    nav = np.cumprod(1 + net)
    years = (bt["exit"].iloc[-1] - bt["entry"].iloc[0]).days / 365.25
    sr = lambda x: float(x.mean() / x.std(ddof=1) * np.sqrt(PPY))
    ci = sharpe_ci(net, PPY, BLOCK)
    return {
        "months": int(len(bt)), "sharpe_net": sr(net), "sharpe_gross": sr(gross),
        "sharpe_ci95": ci, "null_kind_0.5": null_kind(ci, 0.5),
        "ann_mean_net": float(net.mean() * PPY), "ann_vol": float(net.std(ddof=1) * np.sqrt(PPY)),
        "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
        "annual_turnover": float(bt["turnover"].sum() / years),
        "annual_cost_drag": float((bt["cost"] + bt["borrow"] + bt["proceeds_drag"]).sum() / years),
        "bootstrap_p_one_sided": ev.block_bootstrap_p(net, block=BLOCK),
        "nw_t": ev.newey_west_t(net, lags=3),
        "avg_names_per_leg": float(bt[["names_long", "names_short"]].mean().mean()),
        "by_year_net": {int(k): float(np.prod(1 + v) - 1) for k, v in bt.groupby(bt.index.year)["net"]},
    }


def period_returns(daily: pd.Series, bt: pd.DataFrame) -> pd.Series:
    """Compound a daily series over each (entry, exit] holding period."""
    out = {}
    for t, r in bt.iterrows():
        seg = daily[(daily.index > r["entry"]) & (daily.index <= r["exit"])]
        out[t] = float(np.prod(1 + seg) - 1) if len(seg) else np.nan
    return pd.Series(out)


def beta_alpha(y: np.ndarray, x: np.ndarray) -> dict:
    X = np.column_stack([np.ones_like(x), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    cov = (e @ e / (len(y) - 2)) * np.linalg.inv(X.T @ X)
    return {"beta": float(b[1]), "alpha_ann": float(b[0] * PPY), "alpha_t": float(b[0] / np.sqrt(cov[0, 0]))}


def run(mode: str) -> dict:
    cal = sg.trading_calendar()
    start, end = map(pd.Timestamp, WINDOWS[mode])
    months = sg.month_end_dates(cal)
    dates = months[(months >= start) & (months <= end)]
    nxt = months[months > end][0]
    dates = dates.append(pd.DatetimeIndex([nxt]))  # defines the last exit only
    upto = cal[cal.searchsorted(nxt, side="right")]
    if mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} in {PREREG.name} first")
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
    else:
        selected = CANDS
    panel = pd.read_parquet(OUT / "signals.parquet")
    panel = panel[panel["date"] <= dates[-2]]
    names = sorted(panel["ticker"].unique())
    opens, closes = ev.load_opens(names, upto)
    opens, closes = opens.reindex(cal[cal <= upto]), closes.reindex(cal[cal <= upto])
    fr = french_daily()
    rf = fr["rf"].reindex(cal[cal <= upto]).ffill()
    spy = pd.read_parquet(ROOT / "data" / "multiasset" / "etf" / "SPY.parquet").set_index("date")
    spy.index = pd.to_datetime(spy.index)

    sc = scores(panel)
    pos = {d: i for i, d in enumerate(cal)}
    entry = {t: cal[pos[t] + 1] for t in dates[:-1]}
    tradeable = pd.DataFrame({t: opens.loc[entry[t]].notna() for t in dates[:-1]}).T
    sc["F3_combined"] = f3_scores_on_tradeable(sc["F1_issuance"], sc["F2_consistency"],
                                               tradeable.reindex(columns=sc["F1_issuance"].columns, fill_value=False)
                                               .reindex(sc["F1_issuance"].index, fill_value=False))
    res, curves = {}, {}
    for name in selected:
        s = sc[name].reindex(index=dates, columns=names)
        base = ev.backtest(s, opens, closes, dates, cal, rf, ev.COSTS["base"])
        stress = ev.backtest(s, opens, closes, dates, cal, rf, ev.COSTS["stress"])
        out = summarize(base)
        out["stress_sharpe"] = float(stress["net"].mean() / stress["net"].std(ddof=1) * np.sqrt(PPY))
        out["stress_mean_ann"] = float(stress["net"].mean() * PPY)
        # market
        spy_ret = pd.Series({t: spy["open"].loc[r["exit"]] / spy["open"].loc[r["entry"]] - 1 for t, r in base.iterrows()})
        out.update(beta_alpha(base["net"].to_numpy(), (spy_ret - base["rf"]).to_numpy()))
        # same-universe controls (gross)
        ew, lg, sh = [], [], []
        for t, r in base.iterrows():
            e, x = r["entry"], r["exit"]
            px = opens.loc[x].fillna(closes.loc[:x].ffill().loc[x])
            ret = px / opens.loc[e] - 1
            v = s.loc[t].where(opens.loc[e].notna()).dropna()
            w = ev.target_weights(s.loc[t].where(opens.loc[e].notna()))
            ew.append(ret[v.index].mean())
            lg.append(ret[w[w > 0].index].mean())
            sh.append(ret[w[w < 0].index].mean())
        ew, lg, sh = np.array(ew), np.array(lg), np.array(sh)
        ew_x = ew - base["rf"].to_numpy()
        out["control_ew_excess_sharpe"] = float(ew_x.mean() / ew_x.std(ddof=1) * np.sqrt(PPY))
        out["control_ew_excess_ann"] = float(ew_x.mean() * PPY)
        out["long_minus_ew_ann"] = float((lg - ew).mean() * PPY)
        out["ew_minus_short_ann"] = float((ew - sh).mean() * PPY)
        res[name] = out
        curves[name] = base
    per_sr = [c["net"].mean() / c["net"].std(ddof=1) for c in curves.values()]
    var = float(np.var(per_sr, ddof=1)) if len(per_sr) > 1 else 0.0
    for name, c in curves.items():
        res[name]["deflated_sharpe_65"] = deflated_sharpe(c["net"].to_numpy(), N_TRIALS, var)
    d = OUT / mode
    d.mkdir(parents=True, exist_ok=True)
    for name, c in curves.items():
        c.to_csv(d / f"{name}_curve.csv")
    if mode == "dev":
        sel = [n for n in CANDS if res[n]["sharpe_net"] >= DEV_GATE]
        (d / "selection.json").write_text(json.dumps({"selected": sel}, indent=1))
    else:
        pc = pd.read_csv(PEAD, index_col=0, parse_dates=True)
        pead = (pc["mtm_rf"].pct_change() - pc["rf_index"].pct_change()).dropna()
        for name, c in curves.items():
            c2 = c[(c["entry"] >= pead.index[0]) & (c["exit"] <= pead.index[-1])]
            pr = period_returns(pead, c2)
            res[name]["corr_pead"] = float(np.corrcoef(c2["net"], pr)[0, 1])
            res[name]["corr_pead_months"] = int(len(c2))
            r = res[name]
            r["pass"] = bool(r["sharpe_net"] >= VAL_GATE and r["stress_mean_ann"] > 0
                             and r["bootstrap_p_one_sided"] < ALPHA and r["sharpe_net"] > BENCH)
    (d / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = run(sys.argv[1])
    for k, v in r.items():
        print(k, {a: (round(b, 3) if isinstance(b, float) else b) for a, b in v.items() if a != "by_year_net"})
        print("  by year", {y: round(x, 3) for y, x in v["by_year_net"].items()})
