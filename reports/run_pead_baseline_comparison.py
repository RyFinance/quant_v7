"""Step 4: is the ML filter earning its complexity, or would a trivial
raw-SUE-magnitude threshold do just as well? Same simulate_portfolio
machinery (same risk limits, circuit breaker, costs) for both, so the
ONLY thing that differs is how a trade gets selected/sized:

  - ML-filtered: ensemble + calibration (Part D), Kelly-sized off the
    calibrated probability.
  - Raw-SUE baseline: trade every event with |SUE| >= `sue_threshold`
    (1.0 = "one full standard deviation surprise," a standard, literature-
    typical bar -- not tuned to flatter either result), Kelly-sized off a
    simple monotonic confidence proxy (0.5 + 0.5*min(|SUE|/5, 0.45)) so
    bigger surprises get bigger size without any learned model.

No cherry-picked threshold search -- one reasonable, pre-registered-style
choice, reported as-is.
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
SUE_THRESHOLD = 1.0


def load_breaker_tiers() -> dict:
    df = pd.read_csv(REPORTS_DIR / "circuit_breaker_daily_production.csv", parse_dates=["date"])
    return dict(zip(df["date"], df["tier"]))


def to_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["exit_day"] = HOLDING_PERIOD_DAYS
    out["realized_return"] = out["position_return"]
    return out


def raw_sue_pseudo_proba(signal: np.ndarray, threshold: float) -> np.ndarray:
    abs_sue = np.abs(signal)
    proba = np.where(abs_sue >= threshold, 0.5 + 0.5 * np.minimum(abs_sue / 5.0, 0.45), 0.0)
    return proba  # 0.0 for below-threshold events -> min_conviction_proba filter drops them


def run_metrics(outcomes, proba, payoff_b, breaker_tiers, label):
    result = simulate_portfolio(outcomes, proba, payoff_b, breaker_tiers, cost_bps=10.0)
    metrics = compute_metrics(result.daily_returns, result.n_trades,
                               avg_position_size=float(np.mean([t.size_fraction for t in result.trades])) if result.trades else 0.0)
    return {"label": label, "n_trades": result.n_trades, "metrics": metrics.__dict__}


def main(data_path: Path = None, tag: str = "original_75"):
    data_path = data_path or (REPORTS_DIR.parent / "data" / "pead_labeled_features.parquet")
    df = pd.read_parquet(data_path)
    breaker_tiers = load_breaker_tiers()

    parts, partitions = split_time_disjoint_panel(df, holding_period=HOLDING_PERIOD_DAYS, min_rows_per_partition=100)
    ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    payoff = estimate_payoff_ratio(parts["train"], PRIMARY_LABEL)

    comparison = {}
    for name in ["holdout_a", "holdout_b", "holdout_c"]:
        outcomes = to_outcomes(parts[name])
        ml_proba = calibrator.transform(ensemble.predict_proba(outcomes))
        raw_proba = raw_sue_pseudo_proba(outcomes["signal"].to_numpy(), SUE_THRESHOLD)

        ml_result = run_metrics(outcomes, ml_proba, payoff.b, breaker_tiers, f"{name}_ml_filtered")
        raw_result = run_metrics(outcomes, raw_proba, payoff.b, breaker_tiers, f"{name}_raw_sue_threshold")
        comparison[name] = {"ml_filtered": ml_result, "raw_sue_threshold": raw_result}
        logger.info(f"{name}: ML Sharpe={ml_result['metrics']['sharpe_ratio']} (n={ml_result['n_trades']}) vs "
                    f"raw-SUE Sharpe={raw_result['metrics']['sharpe_ratio']} (n={raw_result['n_trades']})")

    out_path = REPORTS_DIR / f"pead_baseline_comparison_{tag}.json"
    with open(out_path, "w") as f:
        json.dump(comparison, f, indent=2, default=str)
    logger.info(f"wrote {out_path}")
    return comparison


if __name__ == "__main__":
    import sys
    tag = sys.argv[1] if len(sys.argv) > 1 else "original_75"
    data_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    comparison = main(data_path, tag)
    print(json.dumps(comparison, indent=2, default=str))
