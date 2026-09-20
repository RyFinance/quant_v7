"""Development and validation runs for the registered options-signal candidates.

  PYTHONPATH=. .venv/bin/python -m research.options_signals.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.options_signals.evaluate validation   # needs the unlock

The development run truncates every input at DEV_END before computing a signal. The validation run
refuses to start unless research/options_signals/VALIDATION_UNLOCK.md is registered, with a matching
hash, in research/preregistrations.jsonl, and it only evaluates candidates the development run
selected.
"""
from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from research.options_signals import signals as sg

ROOT = sg.ROOT
OUT = ROOT / "reports" / "options_signals"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/options_signals/VALIDATION_UNLOCK.md"
UNIVERSE = sg.OPT_DIR / "universe.json"
STOCK_DIR = ROOT / "data" / "multiasset" / "stocks"

DEV_START, DEV_END = pd.Timestamp("2014-07-01"), pd.Timestamp("2019-12-31")
VAL_START, VAL_END = pd.Timestamp("2020-01-01"), pd.Timestamp("2026-09-17")
CANDIDATES = {  # name: (signal column, +1 if a high value predicts high returns)
    "H1_os": ("os", -1),
    "H2_ivspread": ("ivspread", +1),
    "H3_skew": ("skew", -1),
}
COMPOSITE = "H4_composite"
MIN_NAMES = 25
COSTS = {
    "base": {"per_side": 0.0005, "borrow": 0.005, "proceeds_earn_rf": True},
    "stress": {"per_side": 0.0015, "borrow": 0.03, "proceeds_earn_rf": False},
}
DEV_GATE_SHARPE = 0.5
VAL_GATE_SHARPE = 0.75
BONFERRONI_ALPHA = 0.05 / 4
BLOCK, DRAWS = 8, 5000


# -- guard ------------------------------------------------------------------------------------------
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


# -- panel ------------------------------------------------------------------------------------------
def universe() -> list[str]:
    return json.loads(UNIVERSE.read_text())["names"]


def _one(args):
    t, upto = args
    daily = sg.daily_signals(t, upto=upto)
    return t, sg.rolling_signals(daily)


def signal_panels(names: list[str], upto: pd.Timestamp, workers: int = 6) -> dict[str, pd.DataFrame]:
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = dict(ex.map(_one, [(t, upto) for t in names]))
    return {col: pd.DataFrame({t: res[t][col] for t in names}) for col in ("os", "ivspread", "skew")}


def load_opens(names: list[str], upto: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens, closes = {}, {}
    for t in names:
        d = pd.read_parquet(STOCK_DIR / f"{t}.parquet")
        d.index = pd.to_datetime(d["date"])
        d = d.loc[:upto]
        opens[t], closes[t] = d["open"], d["close"]
    return pd.DataFrame(opens), pd.DataFrame(closes)


def signal_dates(calendar: pd.DatetimeIndex, start, end) -> pd.DatetimeIndex:
    s = pd.Series(calendar, index=calendar)
    iso = calendar.isocalendar()
    last = s.groupby([iso["year"].to_numpy(), iso["week"].to_numpy()]).max()
    d = pd.DatetimeIndex(sorted(last.to_numpy()))
    return d[(d >= start) & (d <= end)]


def window_signal_dates(calendar: pd.DatetimeIndex, start, end, price_upto) -> pd.DatetimeIndex:
    """Registered signal dates in [start, end], plus the first signal date after `end`, which only
    defines the last exit. ISO weeks are judged on the whole calendar (amendment 3), so a week that
    runs past `end` has no signal date inside the window."""
    dates = signal_dates(calendar, start, end)
    nxt = signal_dates(calendar, end + pd.Timedelta(days=1), price_upto)
    return dates.append(nxt[:1]) if len(nxt) else dates


def composite(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ranks = []
    for name, (col, sign) in CANDIDATES.items():
        ranks.append((sign * panels[col]).rank(axis=1, pct=True))
    stack = np.stack([r.to_numpy() for r in ranks])
    n = np.sum(~np.isnan(stack), axis=0)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(stack, axis=0)
    mean[n < 2] = np.nan
    return pd.DataFrame(mean, index=ranks[0].index, columns=ranks[0].columns)


# -- portfolio --------------------------------------------------------------------------------------
def target_weights(score: pd.Series) -> pd.Series:
    """score: higher = expected higher return. Long top quintile 100% NAV, short bottom 100% NAV."""
    s = score.dropna()
    w = pd.Series(0.0, index=score.index)
    if len(s) < MIN_NAMES:
        return w
    q = pd.qcut(s.rank(method="first"), 5, labels=False)
    top, bot = q.index[q == 4], q.index[q == 0]
    w[top] = 1.0 / len(top)
    w[bot] = -1.0 / len(bot)
    return w


def backtest(score: pd.DataFrame, opens: pd.DataFrame, closes: pd.DataFrame, dates: pd.DatetimeIndex,
             calendar: pd.DatetimeIndex, rf_daily: pd.Series, cost: dict) -> pd.DataFrame:
    """Weekly book: signal on t_k, trade at the next open e_k, hold to e_{k+1}."""
    pos = {d: i for i, d in enumerate(calendar)}
    rows = []
    prev_w = pd.Series(0.0, index=score.columns)
    prev_r = pd.Series(0.0, index=score.columns)
    for k in range(len(dates) - 1):
        t, t_next = dates[k], dates[k + 1]
        if pos[t] + 1 >= len(calendar) or pos[t_next] + 1 >= len(calendar):
            break
        e, x = calendar[pos[t] + 1], calendar[pos[t_next] + 1]
        sc = score.loc[t] if t in score.index else pd.Series(np.nan, index=score.columns)
        sc = sc.where(opens.loc[e].notna())  # amendment 1.6: no entry without a next-session open
        w = target_weights(sc)
        exit_px = opens.loc[x].copy()
        missing = exit_px.isna() & (w != 0)
        if missing.any():  # amendment 1.6: exit at the last available close
            last_close = closes.loc[:x].ffill().loc[x]
            exit_px[missing] = last_close[missing]
        r = (exit_px / opens.loc[e] - 1.0).fillna(0.0)
        # drifted weights of the previous book, then turnover to the new one
        gross_prev = float((prev_w * prev_r).sum())
        drift = prev_w * (1.0 + prev_r) / (1.0 + gross_prev) if prev_w.abs().sum() > 0 else prev_w
        turnover = float((w - drift).abs().sum())
        days = (x - e).days
        short_gross = float(-w[w < 0].sum())
        gross_ret = float((w * r).sum())
        rf_hold = float((1.0 + rf_daily.loc[(rf_daily.index > e) & (rf_daily.index <= x)]).prod() - 1.0)
        trade_cost = turnover * cost["per_side"]
        borrow = short_gross * cost["borrow"] * days / 365.0
        proceeds = 0.0 if cost["proceeds_earn_rf"] else short_gross * rf_hold
        rows.append({"signal_date": t, "entry": e, "exit": x, "names_long": int((w > 0).sum()),
                     "names_short": int((w < 0).sum()), "gross": gross_ret, "turnover": turnover,
                     "cost": trade_cost, "borrow": borrow, "proceeds_drag": proceeds,
                     "net": gross_ret - trade_cost - borrow - proceeds, "rf": rf_hold})
        prev_w, prev_r = w, r
    return pd.DataFrame(rows).set_index("signal_date")


# -- statistics -------------------------------------------------------------------------------------
def newey_west_t(x: np.ndarray, lags: int = 4) -> float:
    x = np.asarray(x, dtype=float)
    n = len(x)
    e = x - x.mean()
    s = e @ e / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / n
    return float(x.mean() / np.sqrt(s / n))


def block_bootstrap_p(x: np.ndarray, block: int = BLOCK, draws: int = DRAWS, seed: int = 20260918) -> float:
    """One-sided p for mean <= 0: circular block bootstrap of the centred series."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    c = x - x.mean()
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(draws, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)[:, :n] % n
    means = c[idx].mean(axis=1)
    return float((np.sum(means >= x.mean()) + 1) / (draws + 1))


def summarize(bt: pd.DataFrame) -> dict:
    net, gross = bt["net"].to_numpy(), bt["gross"].to_numpy()
    active = bt["names_long"] > 0
    nav = np.cumprod(1.0 + net)
    years = max((bt["exit"].iloc[-1] - bt["entry"].iloc[0]).days / 365.25, 1e-9)
    dd = nav / np.maximum.accumulate(nav) - 1.0
    mean_turn = float(bt["turnover"].mean())
    by_year = bt.groupby(bt.index.year)["net"].apply(lambda s: float(np.prod(1 + s) - 1)).to_dict()
    return {
        "weeks": int(len(bt)), "active_weeks": int(active.sum()),
        "sharpe_net": float(net.mean() / net.std(ddof=1) * np.sqrt(52)) if net.std() > 0 else float("nan"),
        "sharpe_gross": float(gross.mean() / gross.std(ddof=1) * np.sqrt(52)) if gross.std() > 0 else float("nan"),
        "ann_mean_net": float(net.mean() * 52), "ann_vol": float(net.std(ddof=1) * np.sqrt(52)),
        "excess_cagr": float(nav[-1] ** (1 / years) - 1), "max_drawdown": float(dd.min()),
        "annual_turnover": float(bt["turnover"].sum() / years),
        "annual_cost_drag": float((bt["cost"] + bt["borrow"] + bt["proceeds_drag"]).sum() / years),
        "breakeven_cost_per_side_bps": float(bt["gross"].mean() / mean_turn * 1e4) if mean_turn > 0 else None,
        "nw_t": newey_west_t(net), "bootstrap_p_one_sided": block_bootstrap_p(net),
        "avg_names_per_leg": float(bt.loc[active, ["names_long", "names_short"]].mean().mean()) if active.any() else 0.0,
        "by_year_net": {int(k): v for k, v in by_year.items()},
    }


# -- runs -------------------------------------------------------------------------------------------
def run(mode: str) -> dict:
    names = universe()
    missing = [t for t in names if not (sg.OPT_DIR / f"{t}.parquet").exists()]
    if missing:
        raise SystemExit(f"option pull incomplete: {len(missing)} names missing ({missing[:5]}...)")
    if mode == "dev":
        start, end = DEV_START, DEV_END
        selected = list(CANDIDATES) + [COMPOSITE]
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} in {PREREG.name} first")
        start, end = VAL_START, VAL_END
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not selected:
            raise SystemExit("development selected nothing; validation is not run")
    else:
        raise SystemExit("mode must be dev or validation")

    price_upto = end + pd.Timedelta(days=14)  # exits of the last week only
    opens, closes = load_opens(names, price_upto)
    calendar = opens.index[opens.notna().sum(axis=1) > len(names) // 2]
    opens, closes = opens.reindex(calendar), closes.reindex(calendar)
    panels = signal_panels(names, upto=end)
    scores = {n: sign * panels[col] for n, (col, sign) in CANDIDATES.items()}
    scores[COMPOSITE] = composite(panels)
    dates = window_signal_dates(calendar, start, end, price_upto)
    ff = sg.french_daily()
    rf_daily = ff["rf"].reindex(calendar.union(ff.index)).ffill().reindex(calendar)

    outdir = OUT / mode
    outdir.mkdir(parents=True, exist_ok=True)
    results = {"mode": mode, "window": [str(start.date()), str(end.date())], "candidates": {}}
    for name in selected:
        results["candidates"][name] = {}
        for label, cost in COSTS.items():
            bt = backtest(scores[name].reindex(calendar), opens, closes, dates, calendar, rf_daily, cost)
            bt.to_csv(outdir / f"{name}_{label}.csv")
            results["candidates"][name][label] = summarize(bt)
    coverage = {col: float(p.loc[dates[:-1].intersection(p.index)].notna().sum(axis=1).mean()) for col, p in panels.items()}
    results["mean_names_with_signal"] = coverage

    if mode == "dev":
        sel = [n for n in selected if results["candidates"][n]["base"]["sharpe_net"] >= DEV_GATE_SHARPE]
        (outdir / "selection.json").write_text(json.dumps({"selected": sel, "gate": f"net base Sharpe >= {DEV_GATE_SHARPE}"}, indent=1))
        results["selected"] = sel
    else:
        for n in selected:
            b, s = results["candidates"][n]["base"], results["candidates"][n]["stress"]
            b["passes"] = bool(b["sharpe_net"] >= VAL_GATE_SHARPE and s["ann_mean_net"] > 0
                               and b["bootstrap_p_one_sided"] < BONFERRONI_ALPHA)
    code = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in ("research/options_signals/signals.py", "research/options_signals/evaluate.py")}
    data = json.loads((sg.OPT_DIR / "manifest.json").read_text())
    results["code_sha256"] = code
    results["options_data_sha256"] = {t: data[t].get("sha256") for t in names}
    (outdir / "results.json").write_text(json.dumps(results, indent=1, default=str))
    return results


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dev"
    r = run(mode)
    for n, v in r["candidates"].items():
        b, s = v["base"], v["stress"]
        print(f"{n:14s} net Sharpe {b['sharpe_net']:+.2f} (gross {b['sharpe_gross']:+.2f}, stress {s['sharpe_net']:+.2f}) "
              f"excess CAGR {b['excess_cagr']:+.2%} maxDD {b['max_drawdown']:.1%} p={b['bootstrap_p_one_sided']:.3f}")
    print("selected:", r.get("selected"))
