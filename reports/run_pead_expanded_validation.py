"""Steps 2+4+5 combined: full D1-D4 ML filter, backtest, and raw-SUE-
baseline comparison on the EXPANDED (503-ticker) PEAD dataset, using
identical logic/thresholds/methodology to the original 75-name run --
only the input data changes. This is the direct test of whether the
original small-sample result holds up, strengthens, or weakens with
~6.9x more real observations.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import roc_auc_score

from ml.validation import split_time_disjoint_panel, check_class_completeness
from ml.baselines import evaluate_majority_baseline, build_logistic_regression, evaluate_model_across_partitions
from ml.ensemble import fit_weighted_ensemble
from ml.calibration import select_and_fit_calibrator
from ml.metrics import classification_report_dict
from risk.kelly import estimate_payoff_ratio
from earnings.features import PEAD_FEATURE_COLUMNS
from earnings.labeling import HOLDING_PERIOD_DAYS
from backtest.engine import simulate_portfolio
from backtest.metrics import compute_metrics, TRADING_DAYS_PER_YEAR

REPORTS_DIR = Path(__file__).parent
PRIMARY_LABEL = "label_cost_adjusted"
SUE_THRESHOLD = 1.0
N_BOOTSTRAP = 5000
N_PERMUTATIONS = 2000
RNG_SEED = 20260819


def load_breaker_tiers() -> dict:
    df = pd.read_csv(REPORTS_DIR / "circuit_breaker_daily_production.csv", parse_dates=["date"])
    return dict(zip(df["date"], df["tier"]))


def to_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["exit_day"] = HOLDING_PERIOD_DAYS
    out["realized_return"] = out["position_return"]
    return out


def sharpe_from_daily_returns(daily_returns: pd.Series) -> float:
    n = len(daily_returns)
    if n < 2:
        return 0.0
    ann_return = (1 + daily_returns).prod() ** (TRADING_DAYS_PER_YEAR / n) - 1
    ann_std = daily_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    return float(ann_return / ann_std) if ann_std > 0 else 0.0


def bootstrap_sharpe_ci(daily_returns: pd.Series, n_bootstrap: int, rng) -> dict:
    values = daily_returns.to_numpy()
    n = len(values)
    boot = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        boot[i] = sharpe_from_daily_returns(pd.Series(rng.choice(values, size=n, replace=True)))
    return {
        "point_estimate": sharpe_from_daily_returns(daily_returns),
        "ci_2.5pct": float(np.percentile(boot, 2.5)), "ci_97.5pct": float(np.percentile(boot, 97.5)),
        "ci_includes_zero": bool(np.percentile(boot, 2.5) <= 0 <= np.percentile(boot, 97.5)),
        "pct_bootstrap_draws_negative": float(np.mean(boot < 0)),
    }


def permutation_test(outcomes, calibrated_proba, payoff_b, breaker_tiers, n_permutations, rng) -> dict:
    real_result = simulate_portfolio(outcomes, calibrated_proba, payoff_b, breaker_tiers, cost_bps=10.0)
    real_sharpe = sharpe_from_daily_returns(real_result.daily_returns)
    null = np.empty(n_permutations)
    for i in range(n_permutations):
        shuffled = rng.permutation(calibrated_proba)
        r = simulate_portfolio(outcomes, shuffled, payoff_b, breaker_tiers, cost_bps=10.0)
        null[i] = sharpe_from_daily_returns(r.daily_returns)
    p_value = float(np.mean(null >= real_sharpe))
    return {"real_sharpe": real_sharpe, "null_mean": float(np.mean(null)),
            "null_ci_2.5pct": float(np.percentile(null, 2.5)), "null_ci_97.5pct": float(np.percentile(null, 97.5)),
            "empirical_p_value": p_value, "significant_at_5pct": p_value < 0.05}


def raw_sue_pseudo_proba(signal: np.ndarray, threshold: float) -> np.ndarray:
    abs_sue = np.abs(signal)
    return np.where(abs_sue >= threshold, 0.5 + 0.5 * np.minimum(abs_sue / 5.0, 0.45), 0.0)


def main():
    rng = np.random.default_rng(RNG_SEED)
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "pead_labeled_features_expanded.parquet")
    logger.info(f"expanded dataset: {len(df)} labeled events, {df['ticker'].nunique()} tickers")
    breaker_tiers = load_breaker_tiers()

    parts, partitions = split_time_disjoint_panel(df, holding_period=HOLDING_PERIOD_DAYS, min_rows_per_partition=100)
    class_completeness = check_class_completeness(parts, PRIMARY_LABEL)

    majority = evaluate_majority_baseline(parts, PRIMARY_LABEL)
    lr = evaluate_model_across_partitions(build_logistic_regression(), parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)

    ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    payoff = estimate_payoff_ratio(parts["train"], PRIMARY_LABEL)
    logger.info(f"ensemble weights: {ensemble.weights}, payoff_b={payoff.b:.4f}")

    holdout_summary = {}
    for name in ["holdout_a", "holdout_b", "holdout_c"]:
        outcomes = to_outcomes(parts[name])
        raw_proba_ens = ensemble.predict_proba(outcomes)
        calibrated_proba = calibrator.transform(raw_proba_ens)
        y_true = outcomes[PRIMARY_LABEL].to_numpy()

        cls_report = classification_report_dict(y_true, (calibrated_proba >= 0.5).astype(int), calibrated_proba)
        ml_backtest = simulate_portfolio(outcomes, calibrated_proba, payoff.b, breaker_tiers, cost_bps=10.0)
        ml_metrics = compute_metrics(ml_backtest.daily_returns, ml_backtest.n_trades,
                                      avg_position_size=float(np.mean([t.size_fraction for t in ml_backtest.trades])) if ml_backtest.trades else 0.0)

        raw_proba_baseline = raw_sue_pseudo_proba(outcomes["signal"].to_numpy(), SUE_THRESHOLD)
        raw_backtest = simulate_portfolio(outcomes, raw_proba_baseline, payoff.b, breaker_tiers, cost_bps=10.0)
        raw_metrics = compute_metrics(raw_backtest.daily_returns, raw_backtest.n_trades,
                                       avg_position_size=float(np.mean([t.size_fraction for t in raw_backtest.trades])) if raw_backtest.trades else 0.0)

        logger.info(f"{name}: bootstrapping ({N_BOOTSTRAP})...")
        boot = bootstrap_sharpe_ci(ml_backtest.daily_returns, N_BOOTSTRAP, rng)
        logger.info(f"{name}: permutation test ({N_PERMUTATIONS})...")
        perm = permutation_test(outcomes, calibrated_proba, payoff.b, breaker_tiers, N_PERMUTATIONS, rng)

        holdout_summary[name] = {
            "n_events": len(outcomes),
            "classification": {"accuracy": cls_report["accuracy"], "roc_auc": cls_report.get("roc_auc"),
                                "majority_accuracy": majority[name]["accuracy"],
                                "beats_majority": cls_report["accuracy"] > majority[name]["accuracy"],
                                "logistic_regression_auc": lr[name].get("roc_auc")},
            "ml_backtest": {"n_trades": ml_backtest.n_trades, "metrics": ml_metrics.__dict__},
            "raw_sue_baseline_backtest": {"n_trades": raw_backtest.n_trades, "metrics": raw_metrics.__dict__},
            "bootstrap_ci": boot,
            "permutation_test": perm,
        }
        logger.info(f"{name}: ML Sharpe={ml_metrics.sharpe_ratio} (CI [{boot['ci_2.5pct']:.2f},{boot['ci_97.5pct']:.2f}], "
                    f"perm p={perm['empirical_p_value']:.4f}) vs raw-SUE Sharpe={raw_metrics.sharpe_ratio}")

    summary = {
        "n_total_events": len(df), "n_tickers": df["ticker"].nunique(),
        "partitions": [p.__dict__ for p in partitions],
        "class_completeness": class_completeness,
        "ensemble_weights": ensemble.weights, "payoff_ratio_b": payoff.b,
        "holdout_summary": holdout_summary,
        "all_holdouts_beat_majority": all(v["classification"]["beats_majority"] for v in holdout_summary.values()),
        "all_holdouts_significant_at_5pct": all(v["permutation_test"]["significant_at_5pct"] for v in holdout_summary.values()),
    }
    with open(REPORTS_DIR / "pead_expanded_validation_report.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("wrote pead_expanded_validation_report.json")
    return summary


if __name__ == "__main__":
    summary = main()
    print(json.dumps(summary, indent=2, default=str))
