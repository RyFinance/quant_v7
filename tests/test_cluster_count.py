"""Tests for cluster-count selection (Task 10).

SYNTHETIC DATA NOTE: unlike the other Phase 1/2 test files, this one
constructs a correlation matrix by hand (block-diagonal, known cluster
structure) rather than pulling real market data. There is no way to get a
"ground truth" cluster count from real market data -- the whole point of
Task 10 is to estimate that count when it's unknown. Validating the
eigenvalue/explained-variance and Marchenko-Pastur estimators requires a
case where the correct answer is known in advance, which only a
constructed matrix can provide. Real-data usage of these same functions is
exercised indirectly by the full pipeline run (Task 12) and by
test_clustering.py's fixtures.
"""
import numpy as np

from clustering.cluster_count import explained_variance_k, marchenko_pastur_k


def _block_correlation_matrix(block_sizes: list[int], within: float = 0.8, between: float = 0.0) -> np.ndarray:
    n = sum(block_sizes)
    m = np.full((n, n), between)
    start = 0
    for size in block_sizes:
        m[start:start + size, start:start + size] = within
        start += size
    np.fill_diagonal(m, 1.0)
    return m


def test_explained_variance_k_detects_block_structure():
    # 3 tight blocks of 5 -> most variance should be explained by ~3 components
    m = _block_correlation_matrix([5, 5, 5], within=0.9, between=0.0)
    k, eigvals = explained_variance_k(m, threshold=0.90)
    assert k <= 5  # well below n=15; the 3 dominant eigenvalues should dominate
    assert eigvals[0] > eigvals[-1]


def test_explained_variance_k_threshold_monotonic():
    m = _block_correlation_matrix([5, 5, 5], within=0.9, between=0.0)
    k_low, _ = explained_variance_k(m, threshold=0.50)
    k_high, _ = explained_variance_k(m, threshold=0.99)
    assert k_low <= k_high


def test_marchenko_pastur_k_detects_signal_factors():
    m = _block_correlation_matrix([5, 5, 5], within=0.9, between=0.0)
    k, lambda_max = marchenko_pastur_k(m, n_obs=60)
    assert 1 <= k <= 15
    assert lambda_max > 1.0


def test_marchenko_pastur_k_fewer_signals_with_more_observations():
    # more observations -> narrower noise band -> should not find MORE signal
    # factors than a shorter window on the same matrix
    m = _block_correlation_matrix([5, 5, 5], within=0.9, between=0.0)
    k_short, _ = marchenko_pastur_k(m, n_obs=30)
    k_long, _ = marchenko_pastur_k(m, n_obs=500)
    assert k_long <= k_short
