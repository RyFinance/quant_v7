"""Audit of the config-sweep PEAD results (reports/config_sweep/COMPARISON.md): what is the true Sharpe?

The sweep's Sharpe (1.34 for 2x sizing, 1.44 for the live 2.5% config) comes from
backtest/metrics.compute_metrics on the bot's CASH-BASIS NAV (bot/execution.PaperExecutionClient.nav:
starting capital + realised P&L; open positions carried at cost) with the risk-free rate at 0.
This rebuilds each configuration's daily NAV from its recorded ledger:
- same trades, share quantities, dates and fill prices; closes from data/raw (the panel the fills used);
- the same 10 bps round trip, charged half at entry and half at exit;
- marked to market every day.
It then measures the Sharpe under progressively more honest definitions and against timing-matched
controls: the same trades placed in SPY, and in the equal-weight average of the 503-name universe
(which shares its survivorship bias).

Run: PYTHONPATH=. .venv/bin/python -m research.pead_audit.mtm_audit
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.common.inference import deflated_sharpe, null_kind, sharpe_ci
from research.options_signals.signals import french_daily

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "live_backtest" / "state"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "reports" / "pead_audit"
CONFIGS = {
    "wide_5p0": "Sized 2x · 5% positions, 100% gross",
    "wide_3p5": "Sized 1.4x · 3.5% positions, 85% gross",
    "wide_2p5": "Live · 2.5% positions",
    "wide_10p0": "Wide universe, 10% positions",
    "old_pead_75": "Old PEAD · 75 names, 10% positions",
}
START_CAPITAL = 100_000.0
ONE_WAY = 0.0005  # half of the bot's 10 bps round trip
BORROW = 0.005    # stress: general-collateral borrow on shorts
EXTRA_SLIP = 0.0005  # stress: 5 bps more per side
PRIOR_TRIALS = 31  # this sweep's 5 configurations plus the 26 earlier configurations noted in reports/higher_sharpe


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def closes(tickers: list[str]) -> pd.DataFrame:
    out = {}
    for t in tickers:
        d = pd.read_parquet(RAW / f"{t}.parquet", columns=["timestamp", "close"])
        d["timestamp"] = pd.to_datetime(d["timestamp"]).dt.normalize()
        out[t] = d.drop_duplicates("timestamp").set_index("timestamp")["close"]
    return pd.DataFrame(out).sort_index()


def cash_basis_returns(name: str) -> pd.Series:
    log = read_jsonl(STATE / f"sweep_{name}_cycle_log.jsonl")
    nav = pd.Series({pd.Timestamp(r["as_of_date"]): r["nav_after"] for r in log}).sort_index()
    nav = nav.groupby(level=0).last()
    return nav.pct_change().fillna(nav.iloc[0] / START_CAPITAL - 1)


def positions(name: str) -> pd.DataFrame:
    L = read_jsonl(STATE / f"sweep_{name}_ledger.jsonl")
    o = pd.DataFrame([x for x in L if x["event"] == "open"])
    c = pd.DataFrame([x for x in L if x["event"] == "close"])
    o["k"] = o.groupby("ticker").cumcount()
    c["k"] = c.groupby("ticker").cumcount()
    p = o.merge(c[["ticker", "k", "exit_date", "exit_price", "realized_pnl", "cost"]], on=["ticker", "k"], how="left")
    p["entry_date"] = pd.to_datetime(p["entry_date"])
    p["exit_date"] = pd.to_datetime(p["exit_date"])
    p["sign"] = np.where(p["direction"] == "long", 1.0, -1.0)
    p["shares"] = p["notional"] / p["fill_price"]
    return p


def mtm_book(p: pd.DataFrame, px: pd.DataFrame, cal: pd.DatetimeIndex, rf: pd.Series,
             one_way: float, borrow: float, cash_earns_rf: bool, substitute: pd.Series | None = None) -> pd.DataFrame:
    """Daily marked P&L. With `substitute`, every trade is placed in that one price series instead
    (same dates, direction and notional), giving a timing-matched control."""
    pnl = pd.Series(0.0, index=cal)
    long_mv = pd.Series(0.0, index=cal)
    short_mv = pd.Series(0.0, index=cal)
    missing = 0
    for r in p.itertuples():
        s = (substitute if substitute is not None else px[r.ticker]).reindex(cal).ffill()
        window = s.loc[r.entry_date:r.exit_date]
        missing += int(px[r.ticker].reindex(window.index).isna().sum()) if substitute is None else 0
        if substitute is None:
            path = window.copy()
            path.iloc[0] = r.fill_price
            path.iloc[-1] = r.exit_price
            shares = r.shares
        else:
            path = window
            shares = r.notional / window.iloc[0]
        mv = shares * path
        dp = r.sign * mv.diff().fillna(0.0)
        dp.iloc[0] -= r.notional * one_way
        dp.iloc[-1] -= mv.iloc[-1] * one_way
        pnl = pnl.add(dp, fill_value=0.0)
        held = mv.iloc[:-1]  # exposure carried overnight into the next day
        if r.sign > 0:
            long_mv = long_mv.add(held.shift(1).reindex(mv.index).fillna(0).iloc[1:], fill_value=0.0) if len(mv) > 1 else long_mv
        else:
            short_mv = short_mv.add(held.shift(1).reindex(mv.index).fillna(0).iloc[1:], fill_value=0.0) if len(mv) > 1 else short_mv
    nav = START_CAPITAL + pnl.cumsum()
    nav_prev = nav.shift(1).fillna(START_CAPITAL)
    interest = (nav_prev - long_mv).clip(lower=0) * rf if cash_earns_rf else 0.0 * rf
    borrow_cost = short_mv * borrow / 252
    total = pnl + interest - borrow_cost
    nav2 = START_CAPITAL + total.cumsum()
    ret = total / nav2.shift(1).fillna(START_CAPITAL)
    return pd.DataFrame({"ret": ret, "nav": nav2, "long_mv": long_mv, "short_mv": short_mv, "missing_marks": missing})


def ols_hac(y: np.ndarray, x: np.ndarray, lags: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """OLS of y on [1, x] with Newey-West standard errors; returns (params, t-stats)."""
    X = np.column_stack([np.ones_like(x), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = (y - X @ b)[:, None] * X
    S = u.T @ u
    for L in range(1, lags + 1):
        g = u[L:].T @ u[:-L]
        S += (1 - L / (lags + 1)) * (g + g.T)
    V = XtX_inv @ S @ XtX_inv
    return b, b / np.sqrt(np.diag(V))


def stats(ex: pd.Series, mkt_ex: pd.Series | None = None) -> dict:
    x = ex.to_numpy()
    sr = float(x.mean() / x.std(ddof=1) * np.sqrt(252))
    ci = sharpe_ci(x, 252, block=21)
    out = {"sharpe": sr, "ci95": ci, "null_kind_at_0.5": null_kind(ci, 0.5), "ann_mean": float(x.mean() * 252),
           "ann_vol": float(x.std(ddof=1) * np.sqrt(252)), "lag1_autocorr": float(pd.Series(x).autocorr(1))}
    if mkt_ex is not None:
        b, t = ols_hac(x, mkt_ex.reindex(ex.index).fillna(0.0).to_numpy())
        out.update({"beta": float(b[1]), "alpha_ann": float(b[0] * 252), "alpha_t": float(t[0])})
    return out


def lo_adjusted_sharpe(x: np.ndarray, q: int = 20) -> float:
    """Lo (2002): annualise with autocorrelations instead of √252 (for the cash-basis series)."""
    x = pd.Series(x)
    rho = [x.autocorr(k) for k in range(1, q + 1)]
    eta = np.sqrt(252 / (1 + 2 * sum((1 - k / 252) * r for k, r in enumerate(rho, 1))))
    return float(x.mean() / x.std(ddof=1) * eta)


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    ff = french_daily()
    spy = pd.read_parquet(ROOT / "data" / "stocks_raw_2014" / "SPY.parquet")
    spy = spy.assign(date=pd.to_datetime(spy["date"]).dt.tz_localize(None)).set_index("date")["Adj Close"]
    universe = [f[:-8] for f in sorted(p.name for p in RAW.glob("*.parquet"))]
    all_px = closes(universe)
    results, series = {}, {}
    trial_srs = []
    for name, label in CONFIGS.items():
        cb = cash_basis_returns(name)
        cal = cb.index
        rf = ff["rf"].reindex(cal.union(ff.index)).ffill().reindex(cal)
        mkt_ex = ff["mkt_rf"].reindex(cal)
        p = positions(name)
        px = all_px.reindex(columns=p["ticker"].unique())
        base = mtm_book(p, px, cal, rf, ONE_WAY, 0.0, cash_earns_rf=False)
        withrf = mtm_book(p, px, cal, rf, ONE_WAY, 0.0, cash_earns_rf=True)
        stress = mtm_book(p, px, cal, rf, ONE_WAY + EXTRA_SLIP, BORROW, cash_earns_rf=True)
        ctl_spy = mtm_book(p, px, cal, rf, ONE_WAY, 0.0, cash_earns_rf=True, substitute=spy)
        ew = all_px.reindex(cal).pct_change(fill_method=None).mean(axis=1).fillna(0.0)
        ew_index = (1 + ew).cumprod()
        ctl_ew = mtm_book(p, px, cal, rf, ONE_WAY, 0.0, cash_earns_rf=True, substitute=ew_index)
        final_cash_basis = START_CAPITAL * float(np.prod(1 + cb))
        r = {
            "label": label, "days": len(cal), "trades": len(p), "longs": int((p["sign"] > 0).sum()),
            "reconciliation": {"cash_basis_final_nav": final_cash_basis, "mtm_final_nav_same_costs": float(base["nav"].iloc[-1]),
                               "missing_marks_filled": int(base["missing_marks"].iloc[0])},
            "avg_gross_exposure": float(((withrf["long_mv"] + withrf["short_mv"]) / withrf["nav"].shift(1)).mean()),
            "A_reported_cash_basis_rf0": stats(cb) | {"lo_autocorr_adjusted_sharpe": lo_adjusted_sharpe(cb.to_numpy())},
            "B_mtm_rf0_cash_idle": stats(base["ret"]),
            "C_mtm_excess_cash_earns_rf": stats(withrf["ret"] - rf, mkt_ex),
            "D_stress_borrow_slippage": stats(stress["ret"] - rf, mkt_ex),
            "control_same_trades_in_SPY": stats(ctl_spy["ret"] - rf, mkt_ex),
            "control_same_trades_in_universe_avg": stats(ctl_ew["ret"] - rf, mkt_ex),
            "selection_alpha_vs_universe_control": stats(withrf["ret"] - ctl_ew["ret"]),
            "selection_alpha_vs_spy_control": stats(withrf["ret"] - ctl_spy["ret"]),
        }
        trial_srs.append(r["C_mtm_excess_cash_earns_rf"]["sharpe"] / np.sqrt(252))
        results[name] = r
        series[name] = pd.DataFrame({"cash_basis": (1 + cb).cumprod(), "mtm_rf": withrf["nav"] / START_CAPITAL,
                                     "rf_index": (1 + rf).cumprod(), "spy_control": ctl_spy["nav"] / START_CAPITAL,
                                     "universe_control": ctl_ew["nav"] / START_CAPITAL})
        series[name].to_csv(OUT / f"{name}_curves.csv")
    var_sr = float(np.var(trial_srs, ddof=1))
    for name in CONFIGS:
        cal = series[name].index
        rf = ff["rf"].reindex(cal.union(ff.index)).ffill().reindex(cal)
        ex = series[name]["mtm_rf"].pct_change().fillna(0) - rf
        results[name]["deflated_sharpe_prob"] = {
            "n5_this_sweep": deflated_sharpe(ex.to_numpy(), 5, var_sr),
            f"n{PRIOR_TRIALS}_with_earlier_configs": deflated_sharpe(ex.to_numpy(), PRIOR_TRIALS, var_sr),
        }
    (OUT / "results.json").write_text(json.dumps(results, indent=1, default=str))
    return results


if __name__ == "__main__":
    res = main()
    for n, r in res.items():
        A, B, C, D = (r[k] for k in ["A_reported_cash_basis_rf0", "B_mtm_rf0_cash_idle", "C_mtm_excess_cash_earns_rf", "D_stress_borrow_slippage"])
        sel = r["selection_alpha_vs_universe_control"]
        print(f"{n:12s} reported {A['sharpe']:.2f} (lo-adj {A['lo_autocorr_adjusted_sharpe']:.2f}, ac1 {A['lag1_autocorr']:+.2f}) | "
              f"MTM rf0 {B['sharpe']:.2f} | excess {C['sharpe']:.2f} CI[{C['ci95'][0]:.2f},{C['ci95'][1]:.2f}] beta {C['beta']:.2f} "
              f"alpha {C['alpha_ann']:+.2%} t {C['alpha_t']:.2f} | stress {D['sharpe']:.2f} | "
              f"vs universe ctl {sel['sharpe']:.2f} CI[{sel['ci95'][0]:.2f},{sel['ci95'][1]:.2f}] | DSR31 {r['deflated_sharpe_prob'][f'n{PRIOR_TRIALS}_with_earlier_configs']:.2f}")
        print("   recon", {k: round(v, 1) for k, v in r["reconciliation"].items()}, "gross exp", round(r["avg_gross_exposure"], 2))
