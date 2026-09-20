"""Development / validation runs for research/intraday/PLAN.md.

  PYTHONPATH=. .venv/bin/python -m research.intraday.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.intraday.evaluate validation   # needs the registered unlock

Implementation choices the plan left open, fixed here before any result:
- Indicator features (RSI, Bollinger %b, ATR) use the full 30-minute series, all sessions, up to and
  including the 15:00 bar.
- The roll exclusion is implemented literally: from the Thursday immediately before the third
  Friday of Mar/Jun/Sep/Dec through the following Monday.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.common.inference import null_kind, sharpe_ci
from research.options_signals.evaluate import block_bootstrap_p

ROOT = Path(__file__).resolve().parents[2]
BARS = ROOT / "data" / "lse" / "futures_30m"
ECON = ROOT / "data" / "lse" / "econ_calendar_us.parquet"
OUT = ROOT / "reports" / "intraday"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/intraday/VALIDATION_UNLOCK.md"
PEAD_BENCH = ROOT / "reports" / "pead_audit" / "wide_5p0_curves.csv"

INSTR = {"ES": "ES_F", "NQ": "NQ_F"}
DEV = (pd.Timestamp("2016-06-01"), pd.Timestamp("2020-12-31"))
VAL = (pd.Timestamp("2021-01-01"), pd.Timestamp("2026-09-17"))
COSTS = {"base": 0.5e-4, "stress": 1.5e-4}
CANDIDATES = ["I1_intraday_momentum", "I2_rest_of_day", "I3_ml_lgbm", "I4_announcement_day"]
DEV_GATE, VAL_GATE, ALPHA, BENCHMARK = 0.5, 0.75, 0.05 / 4, 0.70
LGBM = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50, subsample=0.8,
            subsample_freq=1, colsample_bytree=0.8, random_state=7, verbose=-1)
FEATURES = ["r1", "r2", "r4", "r8", "r12", "overnight", "first_half_hour", "rest_of_day", "rsi14", "bb_pctb",
            "atr_pct", "rv20", "vol_z", "dow", "is_nq"]


def validation_unlocked() -> bool:
    p = ROOT / UNLOCK
    if not p.exists():
        return False
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    return any(json.loads(l).get("file") == UNLOCK and json.loads(l).get("sha256") == h
               for l in PREREG.read_text().splitlines())


def load_bars(name: str, upto: pd.Timestamp) -> pd.DataFrame:
    d = pd.read_parquet(BARS / f"{name}.parquet")
    d["ts"] = pd.to_datetime(d["ts"]).dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
    d = d[d["ts"] < upto + pd.Timedelta(days=1)].sort_values("ts").reset_index(drop=True)
    return d


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    diff = close.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def daily_table(bars: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day with the prices the rules need and the ML features, all known by 15:30 ET."""
    b = bars.copy()
    b["date"] = b["ts"].dt.normalize()
    b["hm"] = b["ts"].dt.strftime("%H:%M")
    # indicators on the full 30-minute series, each value using bars up to and including its own bar
    b["rsi14"] = rsi(b["close"])
    mid = b["close"].rolling(20).mean()
    sd = b["close"].rolling(20).std()
    b["bb_pctb"] = (b["close"] - (mid - 2 * sd)) / (4 * sd)
    tr = pd.concat([b["high"] - b["low"], (b["high"] - b["close"].shift()).abs(), (b["low"] - b["close"].shift()).abs()], axis=1).max(axis=1)
    b["atr_pct"] = tr.rolling(14).mean() / b["close"]
    b["lc"] = np.log(b["close"])
    for k in (1, 2, 4, 8, 12):
        b[f"r{k}"] = b["lc"] - b["lc"].shift(k)
    piv = lambda col, hm: b[b["hm"] == hm].set_index("date")[col]
    t = pd.DataFrame({
        "open_0930": piv("open", "09:30"), "p1000": piv("close", "09:30"), "p1530": piv("close", "15:00"),
        "p1600": piv("close", "15:30"), "vol_1500": piv("volume", "15:00"),
    })
    at1500 = b[b["hm"] == "15:00"].set_index("date")
    for c in ["rsi14", "bb_pctb", "atr_pct", "r1", "r2", "r4", "r8", "r12"]:
        t[c] = at1500[c]
    t = t.dropna(subset=["p1530", "p1600"]).sort_index()
    t["p1600_prev"] = t["p1600"].shift(1)
    t["overnight"] = np.log(t["open_0930"] / t["p1600_prev"])
    t["first_half_hour"] = np.log(t["p1000"] / t["open_0930"])
    t["mom_1000"] = np.log(t["p1000"] / t["p1600_prev"])
    t["rest_of_day"] = np.log(t["p1530"] / t["p1600_prev"])
    t["r_last"] = t["p1600"] / t["p1530"] - 1
    t["r_cc"] = t["p1600"] / t["p1600_prev"] - 1
    t["rv20"] = np.log(t["p1600"]).diff().rolling(20).std().shift(1) * np.sqrt(252)  # through yesterday's close
    v = t["vol_1500"]
    t["vol_z"] = (v - v.rolling(20).mean().shift(1)) / v.rolling(20).std().shift(1)
    t["dow"] = t.index.dayofweek
    return t


def roll_days(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    out = []
    for y in range(index.min().year, index.max().year + 1):
        for m in (3, 6, 9, 12):
            first = pd.Timestamp(y, m, 1)
            third_fri = first + pd.Timedelta(days=(4 - first.dayofweek) % 7 + 14)
            out.extend(pd.date_range(third_fri - pd.Timedelta(days=1), third_fri + pd.Timedelta(days=3)))
    return pd.DatetimeIndex(out)


def announcement_days(upto: pd.Timestamp) -> pd.DatetimeIndex:
    e = pd.read_parquet(ECON)
    e = e[e["region_code"] == "US"]
    ev = e["event"]
    keep = (ev == "Fed Interest Rate Decision") | (ev == "CPI YoY") | (ev.str.startswith("Non Farm Payrolls ") & ~ev.str.contains("Private"))
    ts = pd.to_datetime(e.loc[keep, "datetime"]).dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
    days = pd.DatetimeIndex(sorted(set(ts.dt.normalize())))
    return days[days <= upto]


def ml_positions(tables: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.Series]:
    import lightgbm as lgb
    rows = []
    for name, t in tables.items():
        f = t.copy()
        f["is_nq"] = 1 if name == "NQ" else 0
        f["y"] = (f["r_last"] > 0).astype(int)
        f["instr"] = name
        rows.append(f)
    panel = pd.concat(rows).dropna(subset=FEATURES + ["r_last"])
    pos = {n: pd.Series(np.nan, index=t.index) for n, t in tables.items()}
    first_year = max(2018, start.year)
    for year in range(first_year, end.year + 1):
        y0 = pd.Timestamp(year, 1, 1)
        train = panel[panel.index < y0]
        test = panel[(panel.index >= y0) & (panel.index <= min(end, pd.Timestamp(year, 12, 31)))]
        if test.empty or len(train) < 500:
            continue
        model = lgb.LGBMClassifier(**LGBM).fit(train[FEATURES], train["y"])
        p = model.predict_proba(test[FEATURES])[:, 1]
        for name in tables:
            m = (test["instr"] == name).to_numpy()
            pos[name].loc[test.index[m]] = np.where(p[m] > 0.5, 1.0, -1.0)
    return pos


def book(tables, positions, cost_side, col="r_last") -> pd.Series:
    parts = []
    for name, t in tables.items():
        p = positions[name].reindex(t.index).fillna(0.0)
        parts.append(0.5 * (p * t[col] - (p != 0) * 2 * cost_side))
    return pd.concat(parts, axis=1).fillna(0.0).sum(axis=1)


def summarize(r: pd.Series, gross: pd.Series) -> dict:
    x = r.to_numpy()
    ci = sharpe_ci(x, 252, block=21)
    nav = np.cumprod(1 + x)
    active = r != 0
    return {"days": int(len(r)), "active_days": int(active.sum()),
            "sharpe_net": float(x.mean() / x.std(ddof=1) * np.sqrt(252)),
            "sharpe_gross": float(gross.mean() / gross.std(ddof=1) * np.sqrt(252)),
            "sharpe_ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5),
            "ann_mean": float(x.mean() * 252), "ann_vol": float(x.std(ddof=1) * np.sqrt(252)),
            "cagr": float(nav[-1] ** (252 / len(x)) - 1), "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
            "hit_rate_active": float((r[active] > 0).mean()) if active.any() else None,
            "bootstrap_p_one_sided": block_bootstrap_p(x, block=21),
            "by_year": {int(y): float(np.prod(1 + v) - 1) for y, v in r.groupby(r.index.year)}}


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
    tables = {n: daily_table(load_bars(f, end)) for n, f in INSTR.items()}
    common = tables["ES"].index.intersection(tables["NQ"].index)
    rolls = roll_days(common)
    for n in tables:
        tables[n] = tables[n].reindex(common)
    window = common[(common >= start) & (common <= end)]
    tradable = window.difference(rolls)
    positions = {
        "I1_intraday_momentum": {n: np.sign(t["mom_1000"]).reindex(tradable) for n, t in tables.items()},
        "I2_rest_of_day": {n: np.sign(t["rest_of_day"]).reindex(tradable) for n, t in tables.items()},
    }
    ml = ml_positions(tables, start, end)
    positions["I3_ml_lgbm"] = {n: s.reindex(tradable) for n, s in ml.items()}
    ann = announcement_days(end).intersection(tradable)
    positions["I4_announcement_day"] = {n: pd.Series(1.0, index=ann) for n in tables}
    col = {"I4_announcement_day": "r_cc"}
    out = OUT / mode
    out.mkdir(parents=True, exist_ok=True)
    res = {"mode": mode, "window": [str(start.date()), str(end.date())], "roll_days_excluded": int(len(window.intersection(rolls))),
           "announcement_days": int(len(ann)), "candidates": {}}
    bench = None
    if PEAD_BENCH.exists():
        c = pd.read_csv(PEAD_BENCH, index_col=0, parse_dates=True)
        bench = c["mtm_rf"].pct_change() - c["rf_index"].pct_change()
    for name in selected:
        if name == "I3_ml_lgbm":
            w = window[window >= pd.Timestamp(max(2018, start.year), 1, 1)]
        else:
            w = window
        res["candidates"][name] = {}
        gross = book(tables, positions[name], 0.0, col.get(name, "r_last")).reindex(w).fillna(0.0)
        for label, cs in COSTS.items():
            r = book(tables, positions[name], cs, col.get(name, "r_last")).reindex(w).fillna(0.0)
            s = summarize(r, gross)
            if bench is not None:
                both = pd.concat([r, bench], axis=1, join="inner").dropna()
                s["corr_with_pead_benchmark"] = float(both.corr().iloc[0, 1]) if len(both) > 60 else None
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
    print("roll days excluded", r["roll_days_excluded"], "| announcement days", r["announcement_days"])
    for n, v in r["candidates"].items():
        b, s = v["base"], v["stress"]
        print(f"{n:22s} net {b['sharpe_net']:+.2f} CI [{b['sharpe_ci95'][0]:+.2f},{b['sharpe_ci95'][1]:+.2f}] gross {b['sharpe_gross']:+.2f} "
              f"stress {s['sharpe_net']:+.2f} | ann {b['ann_mean']:+.2%} vol {b['ann_vol']:.1%} maxDD {b['max_drawdown']:.1%} "
              f"hit {b['hit_rate_active']:.3f} active {b['active_days']}")
    print("selected:", r.get("selected"))
