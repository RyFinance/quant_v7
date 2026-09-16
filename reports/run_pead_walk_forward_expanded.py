"""Step 5's walk-forward requirement, on the EXPANDED (503-ticker) PEAD
dataset. Annual (not quarterly) rolling windows here -- PEAD events are
inherently sparser per unit time than the daily mean-reversion signal
walk-forward used quarters for; annual windows keep each retrain/test
step statistically meaningful given real earnings cadence, at real
computational cost (this still means 5 full ensemble refits).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from ml.ensemble import fit_weighted_ensemble
from ml.calibration import select_and_fit_calibrator
from risk.kelly import estimate_payoff_ratio
from earnings.features import PEAD_FEATURE_COLUMNS
from earnings.labeling import HOLDING_PERIOD_DAYS
from backtest.engine import simulate_portfolio
from backtest.metrics import compute_metrics

REPORTS_DIR = Path(__file__).parent
PRIMARY_LABEL = "label_cost_adjusted"
CALIBRATION_WINDOW_DAYS = 130  # ~6 months for calibration
PURGE_DAYS = 20  # matches PEAD's own holding period

YEARS = [
    ("2021-08-01", "2022-07-31"), ("2022-08-01", "2023-07-31"),
    ("2023-08-01", "2024-07-31"), ("2024-08-01", "2025-06-30"),
]


def main():
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "pead_labeled_features_expanded.parquet")
    breaker_df = pd.read_csv(REPORTS_DIR / "circuit_breaker_daily_production.csv", parse_dates=["date"])
    breaker_tiers = dict(zip(breaker_df["date"], breaker_df["tier"]))

    results = []
    for y_start, y_end in YEARS:
        y_start_ts, y_end_ts = pd.Timestamp(y_start), pd.Timestamp(y_end)
        val_start = y_start_ts - pd.Timedelta(days=CALIBRATION_WINDOW_DAYS)
        train_end = val_start - pd.Timedelta(days=PURGE_DAYS)

        train = df[df["date"] < train_end]
        validation = df[(df["date"] >= val_start) & (df["date"] < y_start_ts - pd.Timedelta(days=PURGE_DAYS))]
        test = df[(df["date"] >= y_start_ts) & (df["date"] <= y_end_ts)]

        if len(train) < 2000 or len(validation) < 200 or len(test) < 100:
            logger.warning(f"{y_start}: insufficient data, skipping")
            continue

        parts = {"train": train, "validation": validation}
        ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
        calibrator = select_and_fit_calibrator(ensemble, validation, PRIMARY_LABEL)
        payoff = estimate_payoff_ratio(train, PRIMARY_LABEL)

        outcomes = test.copy()
        outcomes["exit_day"] = HOLDING_PERIOD_DAYS
        outcomes["realized_return"] = outcomes["position_return"]
        proba = calibrator.transform(ensemble.predict_proba(outcomes))
        result = simulate_portfolio(outcomes, proba, payoff.b, breaker_tiers, cost_bps=10.0)
        metrics = compute_metrics(result.daily_returns, result.n_trades,
                                   avg_position_size=float(np.mean([t.size_fraction for t in result.trades])) if result.trades else 0.0)

        row = {
            "year": f"{y_start}_to_{y_end}", "train_n": len(train), "validation_n": len(validation), "test_n": len(test),
            "n_trades": result.n_trades, "sharpe_ratio": metrics.sharpe_ratio,
            "annualized_return": metrics.annualized_return, "max_drawdown": metrics.max_drawdown,
        }
        results.append(row)
        logger.info(f"{y_start}->{y_end}: sharpe={metrics.sharpe_ratio}, ann_return={metrics.annualized_return}, "
                    f"trades={result.n_trades}")

    sharpes = [r["sharpe_ratio"] for r in results]
    summary = {
        "n_periods": len(results), "annual_results": results,
        "sharpe_mean": float(np.mean(sharpes)) if sharpes else None,
        "sharpe_std": float(np.std(sharpes)) if sharpes else None,
        "pct_periods_positive_sharpe": float(np.mean([s > 0 for s in sharpes])) if sharpes else None,
    }
    with open(REPORTS_DIR / "pead_walk_forward_expanded_report.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("wrote pead_walk_forward_expanded_report.json")
    return summary


if __name__ == "__main__":
    summary = main()
    print(json.dumps(summary, indent=2, default=str))
