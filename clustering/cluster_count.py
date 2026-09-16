"""Optimal cluster count selection (Task 10).

Two methods, both operating on the eigenvalues of a correlation matrix:

1. `explained_variance_k` (default): standard PCA-style cumulative
   explained-variance threshold (90% default). Since a correlation matrix's
   trace equals N (all-ones diagonal) and its trace also equals the sum of
   its eigenvalues, "cumulative eigenvalue sum / N" is exactly the fraction
   of total variance explained by the top-k eigenvectors. We use this k as
   a proxy for cluster count: the number of directions needed to explain the
   configured variance threshold. This is an interpretive choice (explained
   variance is normally a PCA dimensionality heuristic, not a cluster-count
   heuristic) -- flagged here explicitly since the spec asked for exactly
   this method's threshold semantics rather than the more common eigengap
   heuristic on a graph Laplacian.

2. `marchenko_pastur_k` (alternative): random matrix theory. For an N x T
   returns panel of iid noise, correlation-matrix eigenvalues asymptotically
   fall in [(1-sqrt(N/T))^2, (1+sqrt(N/T))^2]. Eigenvalues above that upper
   bound are taken as "signal" (non-noise) factors/clusters; count of those
   is the MP cluster-count estimate. Requires T (the lookback window length
   used to build the correlation matrix) in addition to the matrix itself.
"""
from __future__ import annotations

import numpy as np


def explained_variance_k(corr_matrix: np.ndarray, threshold: float = 0.90) -> tuple[int, np.ndarray]:
    eigvals = np.linalg.eigvalsh(corr_matrix)[::-1]  # descending
    eigvals = np.clip(eigvals, 0, None)  # guard tiny negative numerical noise
    n = corr_matrix.shape[0]
    cumulative = np.cumsum(eigvals) / n
    k = int(np.searchsorted(cumulative, threshold) + 1)
    k = max(1, min(k, n))
    return k, eigvals


def marchenko_pastur_k(corr_matrix: np.ndarray, n_obs: int) -> tuple[int, float]:
    n = corr_matrix.shape[0]
    q = n / n_obs
    lambda_max = (1 + np.sqrt(q)) ** 2
    eigvals = np.linalg.eigvalsh(corr_matrix)
    k = int(np.sum(eigvals > lambda_max))
    k = max(1, k)
    return k, lambda_max
