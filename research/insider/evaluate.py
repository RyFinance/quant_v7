"""Development and validation runs for the registered insider candidates (research/insider/PLAN.md).

  PYTHONPATH=. .venv/bin/python -m research.insider.evaluate dev
  PYTHONPATH=. .venv/bin/python -m research.insider.evaluate validation   # needs the unlock

Development mode cannot load a filing or a price dated after DEV_END. Validation mode refuses to
start until research/insider/VALIDATION_UNLOCK.md is registered, with a matching sha256, in
research/preregistrations.jsonl. It evaluates only the candidates that development selected.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.insider import prices as px
from research.insider import sec_data as sd
from research.insider import signals as sg
from research.options_signals.signals import french_daily

ROOT = sd.ROOT
OUT = ROOT / "reports" / "insider"
PREREG = ROOT / "research" / "preregistrations.jsonl"
UNLOCK = "research/insider/VALIDATION_UNLOCK.md"

DEV_START, DEV_END = pd.Timestamp("2006-01-01"), pd.Timestamp("2015-12-31")
VAL_START, VAL_END = pd.Timestamp("2016-01-01"), pd.Timestamp("2026-06-30")
PX_START = {"dev": pd.Timestamp("2005-10-01"), "validation": pd.Timestamp("2015-09-01")}
EVAL_START = {"dev": {"N1_cluster": DEV_START, "N2_csuite": DEV_START,
                      "N3_opportunistic": pd.Timestamp(sg.N3_FIRST_YEAR, 1, 1), "N4_composite": DEV_START},
              "validation": {}}  # validation: every candidate from VAL_START
SLEEVES = ["N1_cluster", "N2_csuite", "N3_opportunistic"]
COMPOSITE = "N4_composite"
CANDIDATES = SLEEVES + [COMPOSITE]

HOLD = 63
MIN_PRICE = 5.0
MIN_ADV = 2e6
ADV_WINDOW = 20
TIERS = ((50e6, 0.0005), (5e6, 0.0015))  # ADV > 50M: 5 bps; > 5M: 15 bps; else 40 bps
TIER_LOW = 0.0040
HEDGE = {"window": 126, "min_obs": 60, "borrow": 0.0025, "trade": 0.0001, "clip": (0.0, 2.0)}
STRESS_MULT = 2.0
N_CONTROL, CONTROL_SEED = 20, 20260918
DEV_GATE_SHARPE = 0.5
VAL_GATE_SHARPE, BENCHMARK = 0.75, 0.70
ALPHA = 0.05 / 4
BLOCK, DRAWS, NW_LAGS = 21, 5000, 20


# -- guard ------------------------------------------------------------------------------------------
def validation_unlocked() -> bool:
    path = ROOT / UNLOCK
    if not path.exists() or not PREREG.exists():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for line in PREREG.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("file") == UNLOCK and rec.get("sha256") == digest:
                return True
    return False


def check_upto(upto: pd.Timestamp) -> None:
    if upto > DEV_END and not validation_unlocked():
        raise PermissionError(f"data after {DEV_END.date()} are locked: register {UNLOCK} first")


# -- panel helpers ----------------------------------------------------------------------------------
def filter_and_costs(raw_close: pd.DataFrame, dollar_vol: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """passes[t, j]: known at the close of t (raw close >= $5, 20-session ADV >= $2M, all 20 bars present).
    cost[t, j]: per-side cost for a trade at the open of t, tiered on ADV through the close of t-1."""
    adv = dollar_vol.rolling(ADV_WINDOW, min_periods=ADV_WINDOW).mean()
    passes = (raw_close >= MIN_PRICE) & (adv >= MIN_ADV)
    lag = adv.shift(1)
    cost = pd.DataFrame(np.where(lag > TIERS[0][0], TIERS[0][1], np.where(lag > TIERS[1][0], TIERS[1][1], TIER_LOW)),
                        index=adv.index, columns=adv.columns)
    return passes, cost


def fill_prices(open_tr: pd.DataFrame, close_tr: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """gap = open_t / close_{t-1}; intra = close_t / open_t. Missing closes carried forward, a missing
    open replaced by the prior close; before the first bar both are 1 (never held there)."""
    o = open_tr.where(open_tr > 0)
    c = close_tr.where(close_tr > 0).ffill()
    prev = c.shift(1)
    o = o.where(o.notna(), prev)
    c = c.where(c.notna(), o)
    gap = (o / prev).to_numpy()
    intra = (c / o).to_numpy()
    gap[~np.isfinite(gap)] = 1.0
    intra[~np.isfinite(intra)] = 1.0
    return gap, intra


def place_events(events: pd.DataFrame, calendar: pd.DatetimeIndex, columns: pd.Index, passes: np.ndarray,
                 has_open: np.ndarray) -> tuple[pd.DataFrame, dict]:
    """Map (ticker, signal_date) to calendar rows. s = last session on/before the signal date (filter
    checked there); entry = s + 1, strictly after the filing date. Needs prices, the filter, and a real
    open on the entry day."""
    col = pd.Series(np.arange(len(columns)), index=columns)
    e = events.copy()
    e["j"] = e["ticker"].map(col)
    counts = {"events": int(len(e)), "with_prices": int(e["j"].notna().sum())}
    e = e.dropna(subset=["j"])
    e["j"] = e["j"].astype(int)
    e["s"] = calendar.searchsorted(e["signal_date"].to_numpy(), side="right") - 1
    e["entry"] = e["s"] + 1
    e = e[(e["s"] >= 0) & (e["entry"] < len(calendar))]
    e = e[passes[e["s"].to_numpy(), e["j"].to_numpy()]]
    counts["pass_filter"] = int(len(e))
    e = e[has_open[e["entry"].to_numpy(), e["j"].to_numpy()]]
    counts["entered"] = int(len(e))
    return e.reset_index(drop=True), counts


def active_matrix(placed: pd.DataFrame, shape: tuple[int, int], hold: int = HOLD) -> np.ndarray:
    act = np.zeros(shape, dtype=bool)
    for entry, j in zip(placed["entry"].to_numpy(), placed["j"].to_numpy()):
        act[entry:entry + hold, j] = True  # exit at the open of entry + hold
    return act


def run_book(active: np.ndarray, gap: np.ndarray, intra: np.ndarray, cost: np.ndarray,
             rf: np.ndarray) -> pd.DataFrame:
    """Equal-weight long book, rebalanced to 1/N at the open whenever the active set changes.
    Returns daily total returns (net, gross, stress = costs x STRESS_MULT), cost, turnover, positions."""
    cols = np.flatnonzero(active.any(axis=0))
    act_all, g_all, m_all, c_all = active[:, cols], gap[:, cols], intra[:, cols], cost[:, cols]
    T, K = act_all.shape
    w = np.zeros(K)
    prev = np.zeros(K, dtype=bool)
    out = np.zeros((T, 6))
    for t in range(T):
        act, g, m = act_all[t], g_all[t], m_all[t]
        vo = 1.0 - w.sum() + (w * g).sum()
        u = w * g / vo
        if (act != prev).any():
            n = act.sum()
            a = act / n if n else np.zeros(K)
            d = np.abs(a - u)
            c, to = float((d * c_all[t]).sum()), float(d.sum())
        else:
            a, c, to = u, 0.0, 0.0
        vc = (a * m).sum() + (1.0 - a.sum()) * (1.0 + rf[t])
        out[t] = (vo * (1 - c) * vc - 1, vo * vc - 1, vo * (1 - STRESS_MULT * c) * vc - 1, c, to, act.sum())
        w = a * m / vc
        prev = act
    return pd.DataFrame(out, columns=["net", "gross", "stress", "cost", "turnover", "positions"])


def hedge(excess: np.ndarray, invested: np.ndarray, mkt_rf: np.ndarray, mult: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Short the market at the book's trailing beta (last `window` invested sessions before t)."""
    T = len(excess)
    h = np.zeros(T)
    inv_idx = np.flatnonzero(invested)
    for t in range(T):
        if not invested[t]:
            continue
        past = inv_idx[inv_idx < t][-HEDGE["window"]:]
        if len(past) >= HEDGE["min_obs"]:
            x, y = mkt_rf[past], excess[past]
            var = x.var(ddof=1)
            b = float(np.cov(x, y, ddof=1)[0, 1] / var) if var > 0 else 1.0
        else:
            b = 1.0
        h[t] = float(np.clip(b, *HEDGE["clip"]))
    dh = np.abs(np.diff(np.concatenate([[0.0], h])))
    hedged = excess - h * mkt_rf - mult * (h * HEDGE["borrow"] / 252 + dh * HEDGE["trade"])
    return hedged, h


def control_placements(placed: pd.DataFrame, passes: np.ndarray, has_open: np.ndarray, seed: int) -> pd.DataFrame:
    """One random same-date replacement per event: a ticker passing the same filter at s with an open
    at entry."""
    rng = np.random.default_rng(seed)
    placed = placed.reset_index(drop=True)
    js = np.empty(len(placed), dtype=int)
    for (s, entry), pos in sorted(placed.groupby(["s", "entry"]).indices.items()):
        pool = np.flatnonzero(passes[s] & has_open[entry])
        js[pos] = rng.choice(pool, size=len(pos), replace=True)
    return placed.assign(j=js)


# -- statistics -------------------------------------------------------------------------------------
def newey_west_t(x: np.ndarray, lags: int = NW_LAGS) -> float:
    x = np.asarray(x, dtype=float)
    n = len(x)
    e = x - x.mean()
    s = e @ e / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else float("nan")


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


def sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    sd_ = x.std(ddof=1)
    return float(x.mean() / sd_ * np.sqrt(252)) if sd_ > 0 else float("nan")


def summarize(x: pd.Series) -> dict:
    """x: daily excess returns indexed by date."""
    a = x.to_numpy()
    nav = np.cumprod(1 + a)
    if not a.std() > 0:  # a sleeve with no positions: excess return is identically 0
        return {"days": int(len(a)), "sharpe": float("nan"), "ann_mean": 0.0, "ann_vol": 0.0, "excess_cagr": 0.0,
                "max_drawdown": 0.0, "nw_t": float("nan"), "bootstrap_p_one_sided": 1.0, "ci95": None,
                "null_kind_vs_0.70": "no positions", "by_year": {}}
    ci = sharpe_ci(a, 252, block=BLOCK)
    return {
        "days": int(len(a)), "sharpe": sharpe(a), "ci95": ci, "null_kind_vs_0.70": null_kind(ci, BENCHMARK),
        "ann_mean": float(a.mean() * 252), "ann_vol": float(a.std(ddof=1) * np.sqrt(252)),
        "excess_cagr": float(nav[-1] ** (252 / len(a)) - 1), "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
        "nw_t": newey_west_t(a), "bootstrap_p_one_sided": block_bootstrap_p(a),
        "by_year": {int(k): float(np.prod(1 + v) - 1) for k, v in x.groupby(x.index.year)},
    }


# -- run --------------------------------------------------------------------------------------------
def load_inputs(mode: str) -> dict:
    upto = DEV_END if mode == "dev" else VAL_END
    check_upto(upto)
    om, own = sd.load_open_market(upto=upto)
    tickers = sorted(set(pd.read_parquet(sd.DATA / "cik_ticker.parquet")["ticker"]) & set(px.available_tickers()))
    a2 = sg.price_consistent(om, lambda t: px.raw_close_series(t, upto))  # amendment 1, A2
    p_rows = (om["code"] == "P").to_numpy()
    a2_stats = {"P_trades": int(p_rows.sum()), "P_pass_A2": int((a2 & p_rows).sum())}
    events = sg.all_events(om, own, valid=a2)
    start = DEV_START if mode == "dev" else VAL_START
    events = {k: v[(v["signal_date"] >= start) & (v["signal_date"] <= upto)] for k, v in events.items()}
    ff = french_daily()
    cal = ff.index[(ff.index >= PX_START[mode]) & (ff.index <= upto)]
    panel = px.load_panel(tickers, PX_START[mode], upto, calendar=cal)
    if panel["close_tr"].index.max() > upto:
        raise AssertionError("price panel extends past the window")
    return {"events": events, "calendar": cal, "panel": panel, "rf": ff["rf"].reindex(cal).to_numpy(),
            "mkt_rf": ff["mkt_rf"].reindex(cal).to_numpy(), "upto": upto, "a2": a2_stats}


def evaluate(inp: dict, sleeves: list[str]) -> dict:
    cal, panel = inp["calendar"], inp.pop("panel")
    columns = panel["close_tr"].columns
    passes_df, cost_df = filter_and_costs(panel.pop("raw_close"), panel.pop("dollar_vol"))
    passes, cost = passes_df.to_numpy(), cost_df.to_numpy()
    del passes_df, cost_df
    has_open = (panel["open_tr"] > 0).to_numpy()
    gap, intra = fill_prices(panel.pop("open_tr"), panel.pop("close_tr"))
    del panel
    rf, mkt = inp["rf"], inp["mkt_rf"]
    books, meta = {}, {}
    for name in sleeves:
        placed, counts = place_events(inp["events"][name], cal, columns, passes, has_open)
        bk = run_book(active_matrix(placed, gap.shape), gap, intra, cost, rf)
        bk.index = cal
        ctrl, ctrl_pos = [], []
        for r in range(N_CONTROL):
            cp = control_placements(placed, passes, has_open, CONTROL_SEED + r)
            cb = run_book(active_matrix(cp, gap.shape), gap, intra, cost, rf)
            ctrl.append(cb["net"].to_numpy() - rf)
            ctrl_pos.append(cb["positions"].to_numpy())
        books[name] = {"book": bk, "control": np.array(ctrl), "control_positions": np.mean(ctrl_pos, axis=0)}
        meta[name] = counts
    return {"books": books, "meta": meta}


def series_for(books: dict, name: str, rf: np.ndarray, mkt: np.ndarray, cal: pd.DatetimeIndex) -> dict:
    """Daily excess series for one candidate (a sleeve, or the N4 average of the sleeves)."""
    parts = SLEEVES if name == COMPOSITE else [name]
    out = {k: [] for k in ("net", "gross", "stress", "hedged", "hedged_stress", "positions", "turnover", "cost")}
    ctrl, ctrl_pos = [], []
    for p in parts:
        bk = books[p]["book"]
        inv = bk["positions"].to_numpy() > 0
        net_x = bk["net"].to_numpy() - rf
        stress_x = bk["stress"].to_numpy() - rf
        out["net"].append(net_x)
        out["gross"].append(bk["gross"].to_numpy() - rf)
        out["stress"].append(stress_x)
        out["hedged"].append(hedge(net_x, inv, mkt)[0])
        out["hedged_stress"].append(hedge(stress_x, inv, mkt, mult=STRESS_MULT)[0])
        for k in ("positions", "turnover", "cost"):
            out[k].append(bk[k].to_numpy())
        ctrl.append(books[p]["control"])
        ctrl_pos.append(books[p]["control_positions"])
    s = {k: pd.Series(np.mean(v, axis=0), index=cal) for k, v in out.items()}
    s["control_positions"] = pd.Series(np.mean(ctrl_pos, axis=0), index=cal)
    s["control_draws"] = np.mean(ctrl, axis=0)  # (N_CONTROL, T): draw r of each sleeve, averaged
    return s


def run(mode: str) -> dict:
    if mode == "dev":
        selected = list(CANDIDATES)
    elif mode == "validation":
        if not validation_unlocked():
            raise SystemExit(f"validation is locked: register {UNLOCK} in {PREREG.name} first")
        selected = json.loads((OUT / "dev" / "selection.json").read_text())["selected"]
        if not selected:
            raise SystemExit("development selected nothing; validation is not run")
    else:
        raise SystemExit("mode must be dev or validation")
    inp = load_inputs(mode)
    needed = sorted({p for n in selected for p in (SLEEVES if n == COMPOSITE else [n])})
    ev = evaluate(inp, needed)
    cal, rf, mkt = inp["calendar"], inp["rf"], inp["mkt_rf"]
    outdir = OUT / mode
    outdir.mkdir(parents=True, exist_ok=True)
    res = {"mode": mode, "window": [str((DEV_START if mode == "dev" else VAL_START).date()), str(inp["upto"].date())],
           "event_counts": ev["meta"], "a2_price_check": inp["a2"], "candidates": {}}
    daily_sr, nets = {}, {}
    for name in selected:
        s = series_for(ev["books"], name, rf, mkt, cal)
        start = EVAL_START[mode].get(name, VAL_START)
        m = (cal >= start) & (cal <= inp["upto"])
        net = s["net"][m]
        ctrl = s["control_draws"][:, m]
        diff = net.to_numpy() - ctrl.mean(axis=0)
        ctrl_sr = [sharpe(c) if c.std() > 0 else float("nan") for c in ctrl]
        years = m.sum() / 252
        base = summarize(net)
        base.update({
            "sharpe_gross": sharpe(s["gross"][m].to_numpy()),
            "mean_positions": float(s["positions"][m].mean()),
            "share_days_invested": float((s["positions"][m] > 0).mean()),
            "annual_turnover": float(s["turnover"][m].sum() / years),
            "annual_cost_drag": float(s["cost"][m].sum() / years),
        })
        c = {
            "control_sharpe_median": float(np.median(ctrl_sr)), "control_sharpe_draws": ctrl_sr,
            "control_mean_series_sharpe": sharpe(ctrl.mean(axis=0)),
            "diff_ann_mean": float(diff.mean() * 252), "diff_ir": sharpe(diff),
            "diff_nw_t": newey_west_t(diff),
            "paired_p_one_sided": block_bootstrap_p(diff) if diff.std() > 0 else 1.0,
            "share_draws_beaten": float(np.mean(np.array(ctrl_sr) < base["sharpe"])),
            "control_mean_positions": float(s["control_positions"][m].mean()),
        }
        mk = mkt[m]
        X = np.column_stack([np.ones(m.sum()), mk])
        coef = np.linalg.lstsq(X, net.to_numpy(), rcond=None)[0]
        resid = net.to_numpy() - X @ coef
        se = np.sqrt(resid.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0])
        base.update({"capm_beta": float(coef[1]), "capm_alpha_ann": float(coef[0] * 252),
                     "capm_alpha_t": float(coef[0] / se) if se > 0 else float("nan")})
        stress = summarize(s["stress"][m])
        hedged = summarize(s["hedged"][m])
        hedged["stress_ann_mean"] = float(s["hedged_stress"][m].mean() * 252)
        res["candidates"][name] = {"base": base, "stress": {"sharpe": stress["sharpe"], "ann_mean": stress["ann_mean"]},
                                   "hedged": hedged, "control": c, "eval_start": str(start.date())}
        if net.std() > 0:
            daily_sr[name] = net.mean() / net.std(ddof=1)
        nets[name] = net.to_numpy()
        pd.DataFrame({"net": net, "gross": s["gross"][m], "stress": s["stress"][m], "hedged": s["hedged"][m],
                      "control_mean": ctrl.mean(axis=0), "positions": s["positions"][m]}).to_csv(outdir / f"{name}_daily.csv")
    var = float(np.var(list(daily_sr.values()), ddof=1)) if len(daily_sr) > 1 else 0.0
    for name in selected:
        res["candidates"][name]["base"]["deflated_sharpe_4_trials"] = (
            deflated_sharpe(nets[name], 4, var) if name in daily_sr else float("nan"))

    if mode == "dev":
        sel = []
        for n, r in res["candidates"].items():
            b, c = r["base"], r["control"]
            r["passes_dev_gate"] = bool(b["sharpe"] >= DEV_GATE_SHARPE and c["diff_ann_mean"] > 0
                                        and b["sharpe"] > c["control_sharpe_median"])
            if r["passes_dev_gate"]:
                sel.append(n)
        (outdir / "selection.json").write_text(json.dumps(
            {"selected": sel, "gate": f"net Sharpe >= {DEV_GATE_SHARPE}, beats same-universe control"}, indent=1))
        res["selected"] = sel
    else:
        for n, r in res["candidates"].items():
            b, c = r["base"], r["control"]
            r["passes_validation"] = bool(b["sharpe"] >= VAL_GATE_SHARPE and b["sharpe"] > BENCHMARK
                                          and r["stress"]["ann_mean"] > 0 and b["bootstrap_p_one_sided"] < ALPHA
                                          and c["paired_p_one_sided"] < ALPHA)
    res["code_sha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                          for p in ("research/insider/sec_data.py", "research/insider/signals.py",
                                    "research/insider/prices.py", "research/insider/evaluate.py")}
    man = sd.DATA / "manifest.json"
    res["sec_manifest_sha256"] = hashlib.sha256(man.read_bytes()).hexdigest() if man.exists() else None
    (outdir / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dev"
    r = run(mode)
    for n, v in r["candidates"].items():
        b, c = v["base"], v["control"]
        print(f"{n:17s} net {b['sharpe']:+.2f} gross {b['sharpe_gross']:+.2f} stress {v['stress']['sharpe']:+.2f} "
              f"hedged {v['hedged']['sharpe']:+.2f} | control {c['control_sharpe_median']:+.2f} "
              f"diff {c['diff_ann_mean']:+.2%}/yr p={c['paired_p_one_sided']:.3f} | pos {b['mean_positions']:.0f}")
    print("selected:", r.get("selected"))
