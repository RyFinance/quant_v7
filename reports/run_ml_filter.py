"""Phase 3 orchestration: Part C signals/labels/features (already cached at
data/labeled_features.parquet) -> Part D ML filter -> Part D4 validation.

Also runs Task "does cluster instability degrade the ML filter": trains the
same ensemble with and without the `market_ari_vs_prev` feature and compares
holdout AUC/Brier, plus segments holdout predictions by high- vs low-ARI
days and compares hit rate directly. Reported honestly either way -- this
script does not pick a winner to make the story cleaner.

Primary label: `label_cost_adjusted` (the economically meaningful one --
does the trade clear the cost this build actually charges). Fixed-threshold
label results are also computed for comparison, per signals/labeling.py's
documented reasoning.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import roc_auc_score, brier_score_loss

from ml.validation import split_time_disjoint_panel, check_class_completeness
from ml.baselines import build_logistic_regression, build_hist_gradient_boosting, evaluate_model_across_partitions, evaluate_majority_baseline
from ml.ensemble import fit_weighted_ensemble
from ml.calibration import select_and_fit_calibrator
from ml.metrics import classification_report_dict
from signals.features import FEATURE_COLUMNS, FEATURE_COLUMNS_WITH_STABILITY

REPORTS_DIR = Path(__file__).parent
PRIMARY_LABEL = "label_cost_adjusted"
SECONDARY_LABEL = "label_fixed_threshold"


def evaluate_ensemble(ensemble, calibrator, parts: dict[str, pd.DataFrame], label_col: str) -> dict[str, dict]:
    results = {}
    for name, part in parts.items():
        y_true = part[label_col].to_numpy()
        raw_proba = ensemble.predict_proba(part)
        calibrated_proba = calibrator.transform(raw_proba)
        y_pred = (calibrated_proba >= 0.5).astype(int)
        results[name] = classification_report_dict(y_true, y_pred, calibrated_proba)
        results[name]["raw_ensemble_brier"] = round(float(brier_score_loss(y_true, raw_proba)), 6)
    return results


def instability_ablation(df: pd.DataFrame, parts_no_stab, parts_with_stab) -> dict:
    """Train with vs without the market_ari_vs_prev feature; compare holdout
    performance both ways AND segment predictions by stability regime."""
    ensemble_no_stab = fit_weighted_ensemble(parts_no_stab, FEATURE_COLUMNS, PRIMARY_LABEL)
    cal_no_stab = select_and_fit_calibrator(ensemble_no_stab, parts_no_stab["validation"], PRIMARY_LABEL)

    ensemble_with_stab = fit_weighted_ensemble(parts_with_stab, FEATURE_COLUMNS_WITH_STABILITY, PRIMARY_LABEL)
    cal_with_stab = select_and_fit_calibrator(ensemble_with_stab, parts_with_stab["validation"], PRIMARY_LABEL)

    comparison = {}
    for holdout in ["holdout_a", "holdout_b", "holdout_c"]:
        part_a = parts_no_stab[holdout]
        part_b = parts_with_stab[holdout]
        y_a = part_a[PRIMARY_LABEL].to_numpy()
        proba_a = cal_no_stab.transform(ensemble_no_stab.predict_proba(part_a))
        y_b = part_b[PRIMARY_LABEL].to_numpy()
        proba_b = cal_with_stab.transform(ensemble_with_stab.predict_proba(part_b))
        comparison[holdout] = {
            "auc_without_stability_feature": round(float(roc_auc_score(y_a, proba_a)), 6),
            "auc_with_stability_feature": round(float(roc_auc_score(y_b, proba_b)), 6),
            "brier_without_stability_feature": round(float(brier_score_loss(y_a, proba_a)), 6),
            "brier_with_stability_feature": round(float(brier_score_loss(y_b, proba_b)), 6),
        }

    # segment: within holdout_a+b+c pooled (no-stability-feature model), do
    # predictions do better on high-market-ARI (stable) days vs low-ARI days?
    pooled = pd.concat([parts_no_stab[h] for h in ["holdout_a", "holdout_b", "holdout_c"]])
    pooled_proba = cal_no_stab.transform(ensemble_no_stab.predict_proba(pooled))
    pooled = pooled.assign(pred_proba=pooled_proba)
    median_ari = pooled["market_ari_vs_prev"].median()
    high_stab = pooled[pooled["market_ari_vs_prev"] >= median_ari]
    low_stab = pooled[pooled["market_ari_vs_prev"] < median_ari]

    segment_report = {
        "median_market_ari_split": float(median_ari),
        "high_stability_days": {
            "n": int(len(high_stab)),
            "auc": round(float(roc_auc_score(high_stab[PRIMARY_LABEL], high_stab["pred_proba"])), 6),
            "brier": round(float(brier_score_loss(high_stab[PRIMARY_LABEL], high_stab["pred_proba"])), 6),
        },
        "low_stability_days": {
            "n": int(len(low_stab)),
            "auc": round(float(roc_auc_score(low_stab[PRIMARY_LABEL], low_stab["pred_proba"])), 6),
            "brier": round(float(brier_score_loss(low_stab[PRIMARY_LABEL], low_stab["pred_proba"])), 6),
        },
    }

    return {"feature_ablation_by_holdout": comparison, "stability_segment_analysis": segment_report}


def main():
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "labeled_features.parquet")
    logger.info(f"loaded {len(df)} labeled feature rows")

    parts, partitions = split_time_disjoint_panel(df, holding_period=5)
    class_completeness_cost = check_class_completeness(parts, PRIMARY_LABEL)
    class_completeness_fixed = check_class_completeness(parts, SECONDARY_LABEL)

    logger.info("evaluating D1 baselines (majority, logistic regression, gradient boosting)...")
    majority = evaluate_majority_baseline(parts, PRIMARY_LABEL)
    lr = evaluate_model_across_partitions(build_logistic_regression(), parts, FEATURE_COLUMNS, PRIMARY_LABEL)
    gb = evaluate_model_across_partitions(build_hist_gradient_boosting(), parts, FEATURE_COLUMNS, PRIMARY_LABEL)

    logger.info("fitting D2 ensemble + D3 calibration...")
    ensemble = fit_weighted_ensemble(parts, FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    ensemble_results = evaluate_ensemble(ensemble, calibrator, parts, PRIMARY_LABEL)

    logger.info("secondary label (fixed threshold) ensemble for comparison...")
    ensemble_fixed = fit_weighted_ensemble(parts, FEATURE_COLUMNS, SECONDARY_LABEL)
    calibrator_fixed = select_and_fit_calibrator(ensemble_fixed, parts["validation"], SECONDARY_LABEL)
    ensemble_results_fixed = evaluate_ensemble(ensemble_fixed, calibrator_fixed, parts, SECONDARY_LABEL)

    logger.info("cluster-instability ablation (Task 21)...")
    parts_with_stab, _ = split_time_disjoint_panel(df, holding_period=5)  # same split, just keeps the stability col
    ablation = instability_ablation(df, parts, parts_with_stab)

    beats_majority = {}
    for holdout in ["holdout_a", "holdout_b", "holdout_c"]:
        beats_majority[holdout] = {
            "ensemble_accuracy": ensemble_results[holdout]["accuracy"],
            "majority_accuracy": majority[holdout]["accuracy"],
            "ensemble_beats_majority": ensemble_results[holdout]["accuracy"] > majority[holdout]["accuracy"],
            "ensemble_auc": ensemble_results[holdout].get("roc_auc"),
        }

    summary = {
        "primary_label": PRIMARY_LABEL,
        "partitions": [p.__dict__ for p in partitions],
        "class_completeness": {PRIMARY_LABEL: class_completeness_cost, SECONDARY_LABEL: class_completeness_fixed},
        "ensemble_weights": ensemble.weights,
        "calibration_method": calibrator.method,
        "d1_baselines": {"majority": majority, "logistic_regression": lr, "gradient_boosting_hgb": gb},
        "d2_d3_ensemble_cost_adjusted_label": ensemble_results,
        "d2_d3_ensemble_fixed_threshold_label": ensemble_results_fixed,
        "beats_majority_baseline_check": beats_majority,
        "all_holdouts_beat_majority": all(v["ensemble_beats_majority"] for v in beats_majority.values()),
        "cluster_instability_ablation": ablation,
    }

    with open(REPORTS_DIR / "phase3_ml_filter_report.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("wrote phase3_ml_filter_report.json")
    return summary


if __name__ == "__main__":
    summary = main()
    print(json.dumps(summary, indent=2, default=str))
