"""Item 5: Monte Carlo simulation on the real trade sequence produced by
the live-code-path replay (live_backtest/run_historical_replay.py).

Extracts each REAL closed trade's contribution to portfolio return as
pnl_contribution_pct = realized_pnl / nav_at_entry (a fraction of NAV,
directly comparable and compoundable across trades regardless of their
original dollar notional). This is the same unit backtest/engine.py's
`Trade.pnl_contribution` already uses for the vectorized backtest; here it
is reconstructed from the replay's real JSONL ledger (open/close pairs)
since bot/execution.py's live code path logs to a ledger, not an in-memory
Trade list.

DOCUMENTED SIMPLIFICATION: a rigorous Monte Carlo that reorders trades and
also correctly recomputes each trade's originally-overlapping position
sizing under the new order is a much harder problem (trade N's size in
the real run depended on NAV at ITS actual entry time, which depended on
every earlier trade's real outcome). Standard practice in trade-sequence
Monte Carlo analysis (e.g. system-trading risk tools) instead treats each
trade's REALIZED percentage contribution as a fixed unit and simulates
SEQUENTIAL (non-overlapping) compounding of a resampled/reordered
sequence of those units: NAV_sim = NAV_0 * prod(1 + r_i). This isolates
and answers "how much does the OUTCOME depend on the order/luck of the
same set of wins and losses" -- the actual question Monte Carlo trade
analysis exists to answer -- without pretending to re-simulate the full
overlapping-position mechanics. Documented here explicitly, not silently
assumed.

Two distinct methods, both run and reported (they answer different
questions):
  1. BOOTSTRAP (resample WITH replacement, same length as the original):
     captures both magnitude and sequence uncertainty -- "what if I had
     drawn from the same underlying return distribution again."
  2. PERMUTATION (reorder the SAME exact trades, no replacement): holds
     the total ending return in a linear sum framing constant in
     expectation and isolates purely SEQUENCE risk -- "given exactly
     these wins and losses, how much does drawdown depend on the order
     they happened to arrive in."
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

N_BOOTSTRAP = 5000
N_PERMUTATION = 5000
RNG_SEED = 20260819


@dataclass
class TradeRecord:
    ticker: str
    entry_date: str
    exit_date: str
    notional: float
    size_fraction: float
    realized_pnl: float
    nav_at_entry: float
    pnl_contribution_pct: float


def extract_trades_from_ledger(ledger_path: Path) -> list[TradeRecord]:
    """Reconstruct one TradeRecord per matched open/close pair from the
    real replay ledger JSONL. Real data only -- if a ticker's close never
    arrives (position still open at the end of the replay window), it is
    excluded (unrealized, not a completed trade)."""
    opens: dict[str, dict] = {}
    trades: list[TradeRecord] = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            ticker = record["ticker"]
            if record["event"] == "open":
                opens[ticker] = record
            elif record["event"] == "close":
                open_record = opens.pop(ticker, None)
                if open_record is None:
                    continue  # closed without a matching open in this file -- shouldn't happen, skip defensively
                notional = open_record["notional"]
                size_fraction = open_record["size_fraction"]
                nav_at_entry = notional / size_fraction if size_fraction > 0 else float("nan")
                pnl_pct = record["realized_pnl"] / nav_at_entry if nav_at_entry and nav_at_entry > 0 else 0.0
                trades.append(TradeRecord(
                    ticker=ticker, entry_date=open_record.get("entry_date", ""), exit_date=record["exit_date"],
                    notional=notional, size_fraction=size_fraction, realized_pnl=record["realized_pnl"],
                    nav_at_entry=nav_at_entry, pnl_contribution_pct=pnl_pct,
                ))
    trades.sort(key=lambda t: t.exit_date)
    logger.info(f"extracted {len(trades)} completed trades from {ledger_path}")
    return trades


def _equity_curve_from_sequence(returns: np.ndarray, starting_nav: float = 100_000.0) -> np.ndarray:
    return starting_nav * np.cumprod(1 + returns)


def _max_drawdown(equity_curve: np.ndarray) -> float:
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min())


def _ending_return(equity_curve: np.ndarray, starting_nav: float = 100_000.0) -> float:
    return float(equity_curve[-1] / starting_nav - 1.0)


def run_monte_carlo(trades: list[TradeRecord], n_bootstrap: int = N_BOOTSTRAP,
                     n_permutation: int = N_PERMUTATION, seed: int = RNG_SEED) -> dict:
    if len(trades) < 2:
        return {"error": f"too few completed trades ({len(trades)}) for a meaningful Monte Carlo", "n_trades": len(trades)}

    rng = np.random.default_rng(seed)
    returns = np.array([t.pnl_contribution_pct for t in trades])
    n = len(returns)

    real_curve = _equity_curve_from_sequence(returns)
    real_ending_return = _ending_return(real_curve)
    real_max_dd = _max_drawdown(real_curve)

    boot_ending_returns = np.empty(n_bootstrap)
    boot_max_dds = np.empty(n_bootstrap)
    boot_curves = np.empty((n_bootstrap, n))  # every draw's full step-by-step NAV path, for the fan-chart band below
    for i in range(n_bootstrap):
        sample = rng.choice(returns, size=n, replace=True)
        curve = _equity_curve_from_sequence(sample)
        boot_ending_returns[i] = _ending_return(curve)
        boot_max_dds[i] = _max_drawdown(curve)
        boot_curves[i] = curve

    # Fan-chart band: at each trade-step index (0..n-1), the P5/P50/P95 NAV
    # across all bootstrap draws -- this is what actually overlays
    # meaningfully on the real equity curve (a single ending-return number
    # can't be drawn as a band; a per-step percentile of the SIMULATED
    # paths can). Indexed by trade step, not calendar date, since bootstrap
    # draws don't preserve real dates -- the dashboard aligns this to the
    # real curve's own trade-step x-axis, documented in the dashboard spec.
    fan_chart = {
        "step": list(range(n)),
        "p5": np.percentile(boot_curves, 5, axis=0).tolist(),
        "p50": np.percentile(boot_curves, 50, axis=0).tolist(),
        "p95": np.percentile(boot_curves, 95, axis=0).tolist(),
    }

    perm_ending_returns = np.empty(n_permutation)
    perm_max_dds = np.empty(n_permutation)
    for i in range(n_permutation):
        sample = rng.permutation(returns)
        curve = _equity_curve_from_sequence(sample)
        perm_ending_returns[i] = _ending_return(curve)
        perm_max_dds[i] = _max_drawdown(curve)

    def percentiles(arr):
        return {"p5": float(np.percentile(arr, 5)), "p50": float(np.percentile(arr, 50)), "p95": float(np.percentile(arr, 95))}

    result = {
        "n_trades": n,
        "n_bootstrap_draws": n_bootstrap,
        "n_permutation_draws": n_permutation,
        "real_realized": {"ending_return": real_ending_return, "max_drawdown": real_max_dd},
        "bootstrap": {
            "ending_return_pct": percentiles(boot_ending_returns),
            "max_drawdown_pct": percentiles(boot_max_dds),
            "pct_draws_ending_negative": float(np.mean(boot_ending_returns < 0)),
        },
        "permutation": {
            "ending_return_pct": percentiles(perm_ending_returns),
            "max_drawdown_pct": percentiles(perm_max_dds),
            "pct_draws_ending_negative": float(np.mean(perm_ending_returns < 0)),
            "note": "ending_return under pure permutation is mathematically close to constant "
                    "(same trades, order doesn't change the product much unless compounding effects "
                    "are large) -- max_drawdown is the metric permutation actually varies meaningfully.",
        },
        "fan_chart_nav_by_step": fan_chart,
        "real_equity_curve_by_step": {"step": list(range(n)), "nav": real_curve.tolist()},
        "raw_bootstrap_ending_returns": boot_ending_returns.tolist(),
        "raw_bootstrap_max_drawdowns": boot_max_dds.tolist(),
        "raw_permutation_max_drawdowns": perm_max_dds.tolist(),
    }
    logger.info(f"Monte Carlo ({n} trades): real ending_return={real_ending_return:.2%}, real max_dd={real_max_dd:.2%} | "
                f"bootstrap ending_return p5/p50/p95={result['bootstrap']['ending_return_pct']} | "
                f"bootstrap max_dd p5/p50/p95={result['bootstrap']['max_drawdown_pct']}")
    return result


if __name__ == "__main__":
    import sys
    ledger_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "state" / "replay_ledger.jsonl"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent / "reports" / "pead_live_backtest_monte_carlo.json"
    trades = extract_trades_from_ledger(ledger_path)
    result = run_monte_carlo(trades)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"wrote {out_path}")
    print(json.dumps({k: v for k, v in result.items() if not k.startswith("raw_")}, indent=2, default=str))
