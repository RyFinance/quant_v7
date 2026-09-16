"""Section 4.5 -- walk-forward validation. Rolling quarterly retrain: for
each calendar quarter from 2022-Q3 through 2026-Q2 (spanning holdout_a's
start through holdout_c's end -- i.e. entirely inside the out-of-sample
region already established in Phase 3/6, never touching the original
training window), refit the ensemble on an EXPANDING window of all data
up to ~2 months before the quarter starts, calibrate on the 2 months
immediately before, then trade that quarter fresh. This is closer to how
the system would actually behave live (retrained periodically, tested
only on data genuinely after the retrain point) and is meant to catch
slow performance decay that a single static holdout split can miss.
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
from signals.features import FEATURE_COLUMNS
from backtest.engine import precompute_position_outcomes, simulate_portfolio
from backtest.metrics import compute_metrics

REPORTS_DIR = Path(__file__).parent
PRIMARY_LABEL = "label_cost_adjusted"
CALIBRATION_WINDOW_DAYS = 65
PURGE_DAYS = 5

QUARTERS = [
    ("2022-07-01", "2022-09-30"), ("2022-10-01", "2022-12-31"),
    ("2023-01-01", "2023-03-31"), ("2023-04-01", "2023-06-30"), ("2023-07-01", "2023-09-30"), ("2023-10-01", "2023-12-31"),
    ("2024-01-01", "2024-03-31"), ("2024-04-01", "2024-06-30"), ("2024-07-01", "2024-09-30"), ("2024-10-01", "2024-12-31"),
    ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"), ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31"),
    ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
]


def main():
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "labeled_features.parquet")
    resid = pd.read_parquet(REPORTS_DIR.parent / "data" / "residual_returns_wide.parquet")
    breaker_df = pd.read_csv(REPORTS_DIR / "circuit_breaker_daily_production.csv", parse_dates=["date"])
    breaker_tiers = dict(zip(breaker_df["date"], breaker_df["tier"]))

    quarterly_results = []
    for q_start, q_end in QUARTERS:
        q_start_ts, q_end_ts = pd.Timestamp(q_start), pd.Timestamp(q_end)
        val_start = q_start_ts - pd.Timedelta(days=CALIBRATION_WINDOW_DAYS)
        train_end = val_start - pd.Timedelta(days=PURGE_DAYS)

        train = df[df["date"] < train_end]
        validation = df[(df["date"] >= val_start) & (df["date"] < q_start_ts - pd.Timedelta(days=PURGE_DAYS))]
        test = df[(df["date"] >= q_start_ts) & (df["date"] <= q_end_ts)]

        if len(train) < 5000 or len(validation) < 500 or len(test) < 100:
            logger.warning(f"quarter {q_start}: insufficient data (train={len(train)}, val={len(validation)}, test={len(test)}), skipping")
            continue

        parts = {"train": train, "validation": validation}
        ensemble = fit_weighted_ensemble(parts, FEATURE_COLUMNS, PRIMARY_LABEL)
        calibrator = select_and_fit_calibrator(ensemble, validation, PRIMARY_LABEL)
        payoff = estimate_payoff_ratio(train, PRIMARY_LABEL)

        outcomes = precompute_position_outcomes(test, resid, holding_period=5)
        if outcomes.empty:
            continue
        proba = calibrator.transform(ensemble.predict_proba(outcomes))
        result = simulate_portfolio(outcomes, proba, payoff.b, breaker_tiers, cost_bps=10.0)
        metrics = compute_metrics(result.daily_returns, result.n_trades,
                                   avg_position_size=float(np.mean([t.size_fraction for t in result.trades])) if result.trades else 0.0)

        quarterly_results.append({
            "quarter": f"{q_start}_to_{q_end}",
            "train_n": len(train), "validation_n": len(validation), "test_n": len(test),
            "n_trades": result.n_trades, "ensemble_weights": ensemble.weights,
            "sharpe_ratio": metrics.sharpe_ratio, "annualized_return": metrics.annualized_return,
            "max_drawdown": metrics.max_drawdown, "total_return": metrics.total_return,
        })
        logger.info(f"quarter {q_start}->{q_end}: sharpe={metrics.sharpe_ratio}, ann_return={metrics.annualized_return}, "
                    f"trades={result.n_trades}")

    sharpes = [q["sharpe_ratio"] for q in quarterly_results]
    returns = [q["annualized_return"] for q in quarterly_results]
    combined_daily_returns = None  # not stitched into one continuous series here; per-quarter metrics are the deliverable

    summary = {
        "n_quarters": len(quarterly_results),
        "quarterly_results": quarterly_results,
        "sharpe_mean": float(np.mean(sharpes)) if sharpes else None,
        "sharpe_std": float(np.std(sharpes)) if sharpes else None,
        "pct_quarters_positive_sharpe": float(np.mean([s > 0 for s in sharpes])) if sharpes else None,
        "first_half_mean_sharpe": float(np.mean(sharpes[:len(sharpes) // 2])) if len(sharpes) >= 2 else None,
        "second_half_mean_sharpe": float(np.mean(sharpes[len(sharpes) // 2:])) if len(sharpes) >= 2 else None,
    }
    with open(REPORTS_DIR / "phase6_walk_forward_report.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("wrote phase6_walk_forward_report.json")
    return summary


if __name__ == "__main__":
    summary = main()
    print(json.dumps(summary, indent=2, default=str))
