"""PEAD backtest -- reuses backtest/engine.py's `simulate_portfolio` and
backtest/metrics.py directly (both are strategy-agnostic: they just need a
DataFrame with date/ticker/signal/realized_return/exit_day + a calibrated
probability array). Reuses the SAME Phase 5 circuit-breaker daily tier
series (circuit_breaker_daily_production.csv) since that's computed purely
from market data, not from any particular signal.

DELIBERATE SIMPLIFICATION vs. the mean-reversion backtest: no adaptive
TP/SL exit simulation here. Part E3's adaptive-exit machinery was built
around the mean-reversion signal's cluster-relative statistics (entry
deviation vs. cluster volatility) which don't have a PEAD equivalent (no
"cluster" for a single-stock earnings event). PEAD is also economically a
slower, drift-based effect, not a spike-and-revert trade, so a full
holding-period exit is a more natural fit than tight intraday-style stops.
Positions are therefore held the full 20 trading days, using the same
`position_return` computed during labeling as the realized outcome.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from ml.validation import split_time_disjoint_panel
from ml.ensemble import fit_weighted_ensemble
from ml.calibration import select_and_fit_calibrator
from risk.kelly import estimate_payoff_ratio
from earnings.features import PEAD_FEATURE_COLUMNS
from earnings.labeling import HOLDING_PERIOD_DAYS
from backtest.engine import simulate_portfolio
from backtest.metrics import compute_metrics

REPORTS_DIR = Path(__file__).parent
PRIMARY_LABEL = "label_cost_adjusted"


def load_breaker_tiers() -> dict:
    df = pd.read_csv(REPORTS_DIR / "circuit_breaker_daily_production.csv", parse_dates=["date"])
    return dict(zip(df["date"], df["tier"]))


def to_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["exit_day"] = HOLDING_PERIOD_DAYS
    out["realized_return"] = out["position_return"]
    return out


def run_one_backtest(outcomes, ensemble, calibrator, payoff_b, breaker_tiers, cost_bps, label):
    if outcomes.empty:
        return {"label": label, "n_days": 0, "note": "no candidates"}
    raw_proba = ensemble.predict_proba(outcomes)
    calibrated_proba = calibrator.transform(raw_proba)
    result = simulate_portfolio(outcomes, calibrated_proba, payoff_b, breaker_tiers, cost_bps=cost_bps)
    metrics = compute_metrics(result.daily_returns, result.n_trades,
                               avg_position_size=float(np.mean([t.size_fraction for t in result.trades])) if result.trades else 0.0)
    return {
        "label": label, "cost_bps": cost_bps, "n_candidates": len(outcomes), "n_trades": result.n_trades,
        "n_blocked_by_circuit_breaker": result.n_blocked_by_circuit_breaker,
        "n_blocked_by_risk_limits": result.n_blocked_by_risk_limits,
        "n_blocked_by_no_conviction": result.n_blocked_by_no_conviction,
        "metrics": metrics.__dict__,
    }


def main():
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "pead_labeled_features.parquet")
    breaker_tiers = load_breaker_tiers()

    parts, partitions = split_time_disjoint_panel(df, holding_period=HOLDING_PERIOD_DAYS, min_rows_per_partition=100)
    ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    payoff = estimate_payoff_ratio(parts["train"], PRIMARY_LABEL)
    logger.info(f"payoff ratio b={payoff.b:.4f}")

    holdout_results = {}
    for name in ["holdout_a", "holdout_b", "holdout_c"]:
        outcomes = to_outcomes(parts[name])
        holdout_results[name] = run_one_backtest(outcomes, ensemble, calibrator, payoff.b, breaker_tiers, 10.0, name)

    cost_sweep = {}
    for cost_bps in [0.0, 2.0, 5.0, 10.0]:
        cost_sweep[f"{cost_bps}bps"] = {
            name: run_one_backtest(to_outcomes(parts[name]), ensemble, calibrator, payoff.b, breaker_tiers, cost_bps, name)
            for name in ["holdout_a", "holdout_b", "holdout_c"]
        }

    baseline_results = {}
    for name in ["holdout_a", "holdout_b", "holdout_c"]:
        outcomes = to_outcomes(parts[name])
        uniform_proba = np.full(len(outcomes), 0.55)
        result = simulate_portfolio(outcomes, uniform_proba, payoff.b, breaker_tiers, cost_bps=10.0)
        metrics = compute_metrics(result.daily_returns, result.n_trades,
                                   avg_position_size=float(np.mean([t.size_fraction for t in result.trades])) if result.trades else 0.0)
        baseline_results[name] = {"n_trades": result.n_trades, "metrics": metrics.__dict__}

    summary = {
        "holding_period_days": HOLDING_PERIOD_DAYS,
        "partitions": [p.__dict__ for p in partitions],
        "ensemble_weights": ensemble.weights,
        "payoff_ratio_b": payoff.b,
        "holdout_backtests_10bps": holdout_results,
        "transaction_cost_sensitivity_sweep": cost_sweep,
        "unconditional_no_ml_filter_baseline_10bps": baseline_results,
    }
    with open(REPORTS_DIR / "pead_backtest_report.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("wrote pead_backtest_report.json")
    return summary


if __name__ == "__main__":
    summary = main()
    print(json.dumps(summary, indent=2, default=str))
