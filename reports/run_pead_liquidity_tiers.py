"""Direct test of the literature's prediction: PEAD should be STRONGER in
less-liquid, less-covered names. Splits the expanded universe into
liquidity tertiles (by the same trailing dollar-volume measure used
throughout this project) and re-runs the identical ML-filter + backtest
pipeline independently within each tier. If the effect is real and
liquidity-driven as theory predicts, the least-liquid tertile should show
a STRONGER, more consistent edge than the most-liquid tertile (which is
close to the original 75-name universe). If the effect looks the same
(or weaker) in the less-liquid tier, that's the honest, reported-as-is
answer -- not what theory would predict, but a genuine finding either way.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from ml.validation import split_time_disjoint_panel, check_class_completeness
from ml.ensemble import fit_weighted_ensemble
from ml.calibration import select_and_fit_calibrator
from ml.baselines import evaluate_majority_baseline
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


def run_tier(df_tier: pd.DataFrame, breaker_tiers: dict, tier_name: str) -> dict:
    try:
        parts, partitions = split_time_disjoint_panel(df_tier, holding_period=HOLDING_PERIOD_DAYS, min_rows_per_partition=60)
    except Exception as e:
        return {"tier": tier_name, "n_events": len(df_tier), "error": str(e)}

    ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    payoff = estimate_payoff_ratio(parts["train"], PRIMARY_LABEL)
    majority = evaluate_majority_baseline(parts, PRIMARY_LABEL)

    holdout_results = {}
    for name in ["holdout_a", "holdout_b", "holdout_c"]:
        outcomes = to_outcomes(parts[name])
        proba = calibrator.transform(ensemble.predict_proba(outcomes))
        result = simulate_portfolio(outcomes, proba, payoff.b, breaker_tiers, cost_bps=10.0)
        metrics = compute_metrics(result.daily_returns, result.n_trades,
                                   avg_position_size=float(np.mean([t.size_fraction for t in result.trades])) if result.trades else 0.0)
        from sklearn.metrics import roc_auc_score
        y_true = outcomes[PRIMARY_LABEL].to_numpy()
        auc = float(roc_auc_score(y_true, proba)) if len(np.unique(y_true)) == 2 else None
        acc = float(((proba >= 0.5).astype(int) == y_true).mean())
        holdout_results[name] = {
            "n_events": len(outcomes), "n_trades": result.n_trades, "auc": auc, "accuracy": acc,
            "majority_accuracy": majority[name]["accuracy"], "beats_majority": acc > majority[name]["accuracy"],
            "sharpe_ratio": metrics.sharpe_ratio, "annualized_return": metrics.annualized_return,
            "max_drawdown": metrics.max_drawdown,
        }
    return {
        "tier": tier_name, "n_events_total": len(df_tier),
        "partitions": [p.__dict__ for p in partitions],
        "holdout_results": holdout_results,
        "ensemble_weights": ensemble.weights,
    }


def main():
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "pead_labeled_features_expanded.parquet")
    breaker_tiers = load_breaker_tiers()

    # tertiles by dollar_volume_rank: rank=1 is MOST liquid (lowest rank number)
    n = df["dollar_volume_rank"].nunique()
    tertile_edges = df["dollar_volume_rank"].quantile([1 / 3, 2 / 3]).tolist()
    df = df.copy()
    df["liquidity_tier"] = pd.cut(df["dollar_volume_rank"], bins=[0, tertile_edges[0], tertile_edges[1], np.inf],
                                    labels=["most_liquid", "mid_liquid", "least_liquid"])

    logger.info(f"liquidity tier event counts:\n{df['liquidity_tier'].value_counts()}")

    results = {}
    for tier_name in ["most_liquid", "mid_liquid", "least_liquid"]:
        tier_df = df[df["liquidity_tier"] == tier_name].drop(columns=["liquidity_tier"])
        logger.info(f"running tier {tier_name} ({len(tier_df)} events)...")
        results[tier_name] = run_tier(tier_df, breaker_tiers, tier_name)

    with open(REPORTS_DIR / "pead_liquidity_tier_report.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("wrote pead_liquidity_tier_report.json")
    return results


if __name__ == "__main__":
    results = main()
    print(json.dumps(results, indent=2, default=str))
