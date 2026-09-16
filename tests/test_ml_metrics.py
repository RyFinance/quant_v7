"""Tests for ml/metrics.py. Hand-constructed prediction arrays (SYNTHETIC --
these are exact-answer sanity checks on the metric math itself, not model
outputs, so a known-ground-truth constructed case is the right tool here,
same rationale as Phase 2's test_cluster_count.py)."""
import numpy as np

from ml.metrics import classification_report_dict


def test_perfect_predictions():
    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([0, 0, 1, 1])
    y_proba = np.array([0.1, 0.05, 0.9, 0.95])
    report = classification_report_dict(y_true, y_pred, y_proba)
    assert report["accuracy"] == 1.0
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["roc_auc"] == 1.0
    assert report["brier_score"] < 0.01


def test_worst_case_predictions():
    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([1, 1, 0, 0])
    report = classification_report_dict(y_true, y_pred, y_proba=None)
    assert report["accuracy"] == 0.0
    assert "roc_auc" not in report  # no probabilities passed


def test_confusion_matrix_shape_and_counts():
    y_true = np.array([0, 1, 0, 1, 1])
    y_pred = np.array([0, 1, 1, 1, 0])
    report = classification_report_dict(y_true, y_pred)
    cm = np.array(report["confusion_matrix"])
    assert cm.sum() == 5
    assert cm.shape == (2, 2)
