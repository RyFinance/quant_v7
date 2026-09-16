"""Shared classification metrics for Part D. One function so every model
(baseline, ensemble, calibrated ensemble) is scored identically and
comparably across partitions."""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


def classification_report_dict(y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray | None = None) -> dict[str, Any]:
    y_true = np.asarray(y_true)
    n_classes_present = len(np.unique(y_true))

    report: dict[str, Any] = {
        "n": int(len(y_true)),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 6),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 6),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 6),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 6),
        "positive_rate_true": round(float(y_true.mean()), 6),
        "positive_rate_pred": round(float(np.asarray(y_pred).mean()), 6),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist(),
    }
    if y_proba is not None and n_classes_present == 2:
        report["roc_auc"] = round(float(roc_auc_score(y_true, y_proba)), 6)
        report["brier_score"] = round(float(brier_score_loss(y_true, y_proba)), 6)
        eps = 1e-15
        clipped = np.clip(y_proba, eps, 1 - eps)
        report["log_loss"] = round(float(log_loss(y_true, clipped)), 6)
    return report
