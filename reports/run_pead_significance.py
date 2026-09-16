"""Step 1 of the PEAD re-validation: is the backtest Sharpe distinguishable
from noise given the small trade counts (~90-108/holdout)?

Two tests, both real, both run on the actual fitted model and actual
market outcomes -- no synthetic returns:

1. BOOTSTRAP CI on the observed Sharpe: resample each holdout's daily
   P&L series with replacement (same length, B=5000 draws), recompute
   annualized Sharpe each draw, report the 2.5/97.5 percentile interval.
   This answers "how much would this exact Sharpe estimate wobble under
   a different random draw of the same underlying trades."

2. PERMUTATION test on the ML filter's skill: shuffle the calibrated
   probability assignment across the holdout's candidate rows (breaking
   the link between the model's prediction and the actual outcome, while
   preserving the real return/signal data and every mechanical piece of
   the simulation -- sizing distribution, risk limits, circuit-breaker
   gating). Re-run the full simulation P=2000 times under this shuffle to
   build a null distribution of Sharpe "if the model had no real skill,
   just this same trade structure." Report the empirical p-value: what
   fraction of null-Sharpes are >= the real, unshuffled Sharpe.
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
from backtest.metrics import compute_metrics, TRADING_DAYS_PER_YEAR

REPORTS_DIR = Path(__file__).parent
PRIMARY_LABEL = "label_cost_adjusted"
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


def bootstrap_sharpe_ci(daily_returns: pd.Series, n_bootstrap: int, rng: np.random.Generator) -> dict:
    values = daily_returns.to_numpy()
    n = len(values)
    boot_sharpes = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sample = rng.choice(values, size=n, replace=True)
        boot_sharpes[i] = sharpe_from_daily_returns(pd.Series(sample))
    return {
        "point_estimate": sharpe_from_daily_returns(daily_returns),
        "bootstrap_mean": float(np.mean(boot_sharpes)),
        "ci_2.5pct": float(np.percentile(boot_sharpes, 2.5)),
        "ci_97.5pct": float(np.percentile(boot_sharpes, 97.5)),
        "ci_includes_zero": bool(np.percentile(boot_sharpes, 2.5) <= 0 <= np.percentile(boot_sharpes, 97.5)),
        "pct_bootstrap_draws_negative": float(np.mean(boot_sharpes < 0)),
    }


def permutation_test(outcomes: pd.DataFrame, calibrated_proba: np.ndarray, payoff_b: float,
                      breaker_tiers: dict, n_permutations: int, rng: np.random.Generator) -> dict:
    real_result = simulate_portfolio(outcomes, calibrated_proba, payoff_b, breaker_tiers, cost_bps=10.0)
    real_sharpe = sharpe_from_daily_returns(real_result.daily_returns)

    null_sharpes = np.empty(n_permutations)
    for i in range(n_permutations):
        shuffled_proba = rng.permutation(calibrated_proba)
        result = simulate_portfolio(outcomes, shuffled_proba, payoff_b, breaker_tiers, cost_bps=10.0)
        null_sharpes[i] = sharpe_from_daily_returns(result.daily_returns)

    p_value = float(np.mean(null_sharpes >= real_sharpe))
    return {
        "real_sharpe": real_sharpe,
        "null_mean": float(np.mean(null_sharpes)),
        "null_std": float(np.std(null_sharpes)),
        "null_ci_2.5pct": float(np.percentile(null_sharpes, 2.5)),
        "null_ci_97.5pct": float(np.percentile(null_sharpes, 97.5)),
        "empirical_p_value": p_value,
        "significant_at_5pct": p_value < 0.05,
    }


def main():
    rng = np.random.default_rng(RNG_SEED)
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "pead_labeled_features.parquet")
    breaker_tiers = load_breaker_tiers()

    parts, partitions = split_time_disjoint_panel(df, holding_period=HOLDING_PERIOD_DAYS, min_rows_per_partition=100)
    ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    payoff = estimate_payoff_ratio(parts["train"], PRIMARY_LABEL)

    results = {}
    for name in ["holdout_a", "holdout_b", "holdout_c"]:
        outcomes = to_outcomes(parts[name])
        raw_proba = ensemble.predict_proba(outcomes)
        calibrated_proba = calibrator.transform(raw_proba)

        real_result = simulate_portfolio(outcomes, calibrated_proba, payoff.b, breaker_tiers, cost_bps=10.0)
        logger.info(f"{name}: bootstrapping Sharpe CI ({N_BOOTSTRAP} draws)...")
        boot = bootstrap_sharpe_ci(real_result.daily_returns, N_BOOTSTRAP, rng)
        logger.info(f"{name}: bootstrap Sharpe CI = [{boot['ci_2.5pct']:.3f}, {boot['ci_97.5pct']:.3f}], "
                    f"point={boot['point_estimate']:.3f}, includes_zero={boot['ci_includes_zero']}")

        logger.info(f"{name}: running permutation test ({N_PERMUTATIONS} shuffles)...")
        perm = permutation_test(outcomes, calibrated_proba, payoff.b, breaker_tiers, N_PERMUTATIONS, rng)
        logger.info(f"{name}: permutation p-value={perm['empirical_p_value']:.4f}, "
                    f"null Sharpe range [{perm['null_ci_2.5pct']:.3f}, {perm['null_ci_97.5pct']:.3f}]")

        results[name] = {
            "n_trades": real_result.n_trades,
            "n_days": len(real_result.daily_returns),
            "bootstrap_ci": boot,
            "permutation_test": perm,
        }

    with open(REPORTS_DIR / "pead_significance_report.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("wrote pead_significance_report.json")
    return results


if __name__ == "__main__":
    results = main()
    print(json.dumps(results, indent=2, default=str))
