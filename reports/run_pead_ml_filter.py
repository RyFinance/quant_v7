"""PEAD ML filter -- same D1-D4 rigor as reports/run_ml_filter.py, reusing
the identical ml/ package (baselines, ensemble, calibration, validation).
Only the data source and feature list change (earnings/features.py's
PEAD_FEATURE_COLUMNS instead of signals/features.py's FEATURE_COLUMNS).

SAMPLE SIZE CAVEAT (real, not a bug): earnings events are quarterly, so
this dataset has ~2,700 total labeled events vs. the mean-reversion
signal's ~123,000 -- each holdout here has only ~320-360 rows instead of
~16,000+. Every metric below is correspondingly noisier; a single-holdout
AUC swing of a few points is far less informative here than in the daily
signal's much larger samples. Reported as-is, not smoothed over.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from loguru import logger

from ml.validation import split_time_disjoint_panel, check_class_completeness
from ml.baselines import build_logistic_regression, build_hist_gradient_boosting, evaluate_model_across_partitions, evaluate_majority_baseline
from ml.ensemble import fit_weighted_ensemble
from ml.calibration import select_and_fit_calibrator
from ml.metrics import classification_report_dict
from earnings.features import PEAD_FEATURE_COLUMNS

REPORTS_DIR = Path(__file__).parent
PRIMARY_LABEL = "label_cost_adjusted"
SECONDARY_LABEL = "label_fixed_threshold"


def evaluate_ensemble(ensemble, calibrator, parts, label_col):
    results = {}
    for name, part in parts.items():
        y_true = part[label_col].to_numpy()
        raw_proba = ensemble.predict_proba(part)
        calibrated_proba = calibrator.transform(raw_proba)
        y_pred = (calibrated_proba >= 0.5).astype(int)
        results[name] = classification_report_dict(y_true, y_pred, calibrated_proba)
    return results


def main():
    df = pd.read_parquet(REPORTS_DIR.parent / "data" / "pead_labeled_features.parquet")
    logger.info(f"loaded {len(df)} labeled PEAD events")

    parts, partitions = split_time_disjoint_panel(df, holding_period=20, min_rows_per_partition=100)
    class_completeness = {lbl: check_class_completeness(parts, lbl) for lbl in [PRIMARY_LABEL, SECONDARY_LABEL]}

    majority = evaluate_majority_baseline(parts, PRIMARY_LABEL)
    lr = evaluate_model_across_partitions(build_logistic_regression(), parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    gb = evaluate_model_across_partitions(build_hist_gradient_boosting(), parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)

    ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    ensemble_results = evaluate_ensemble(ensemble, calibrator, parts, PRIMARY_LABEL)

    beats_majority = {}
    for holdout in ["holdout_a", "holdout_b", "holdout_c"]:
        beats_majority[holdout] = {
            "ensemble_accuracy": ensemble_results[holdout]["accuracy"],
            "majority_accuracy": majority[holdout]["accuracy"],
            "ensemble_beats_majority": ensemble_results[holdout]["accuracy"] > majority[holdout]["accuracy"],
            "ensemble_auc": ensemble_results[holdout].get("roc_auc"),
            "n_rows": ensemble_results[holdout]["n"],
        }

    summary = {
        "primary_label": PRIMARY_LABEL,
        "n_total_events": len(df),
        "partitions": [p.__dict__ for p in partitions],
        "class_completeness": class_completeness,
        "ensemble_weights": ensemble.weights,
        "calibration_method": calibrator.method,
        "d1_baselines": {"majority": majority, "logistic_regression": lr, "gradient_boosting_hgb": gb},
        "d2_d3_ensemble": ensemble_results,
        "beats_majority_baseline_check": beats_majority,
        "all_holdouts_beat_majority": all(v["ensemble_beats_majority"] for v in beats_majority.values()),
    }
    with open(REPORTS_DIR / "pead_ml_filter_report.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("wrote pead_ml_filter_report.json")
    return summary


if __name__ == "__main__":
    summary = main()
    print(json.dumps(summary, indent=2, default=str))
