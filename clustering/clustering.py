"""Graph clustering (Task 9): standard spectral clustering (default, fast)
plus SPONGE-sym signed-graph clustering (advanced alternative from the
reference research) for comparison.

Spectral clustering treats the correlation matrix as an unsigned affinity
graph (|correlation| as edge weight) via sklearn's precomputed-affinity
path. This is the standard, fast approach but it throws away the sign of
the relationship -- two names with strong *negative* residual correlation
(a classic pairs-trade candidate) look identical to two names with strong
*positive* correlation under an absolute-value affinity.

SPONGE-sym (Cucuringu, Davies, Glielmo & Tyagi, 2019, "SPONGE: A
Generalized Eigenproblem for Clustering Signed Networks") uses the sign
directly: it looks for a partition that is densely connected by *positive*
edges within clusters and densely connected by *negative* edges *between*
clusters, via a generalized eigenproblem on the symmetric-normalized signed
Laplacians. Implemented here from the paper's formulas (no existing
signed-clustering library dependency was already in this environment):

    A = A+ - A-,  A+, A- >= 0 elementwise
    D+ = diag(A+ @ 1), D- = diag(A- @ 1)
    Lsym+ = I - D+^-1/2 A+ D+^-1/2
    Lsym- = I - D-^-1/2 A- D-^-1/2
    solve (Lsym+ + tau- I) v = lambda (Lsym- + tau+ I) v  for smallest-lambda eigenvectors
    k-means on the row-normalized top-k eigenvector embedding
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import eigh
from sklearn.cluster import KMeans, SpectralClustering


@dataclass
class ClusterResult:
    labels: np.ndarray  # length-n array, cluster id per ticker (order matches `tickers`)
    tickers: list[str]
    k: int
    method: str


def spectral_cluster(corr_matrix: np.ndarray, tickers: list[str], k: int, random_state: int = 42) -> ClusterResult:
    affinity = np.abs(corr_matrix)
    np.fill_diagonal(affinity, 0)
    model = SpectralClustering(
        n_clusters=k, affinity="precomputed", assign_labels="kmeans",
        random_state=random_state,
    )
    labels = model.fit_predict(affinity)
    return ClusterResult(labels=labels, tickers=tickers, k=k, method="spectral")


def _sym_normalized_laplacian(adj: np.ndarray) -> np.ndarray:
    deg = adj.sum(axis=1)
    with np.errstate(divide="ignore"):
        d_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
    d_inv_sqrt_mat = np.diag(d_inv_sqrt)
    n = adj.shape[0]
    return np.eye(n) - d_inv_sqrt_mat @ adj @ d_inv_sqrt_mat


def sponge_sym_cluster(
    corr_matrix: np.ndarray,
    tickers: list[str],
    k: int,
    tau_pos: float = 1.0,
    tau_neg: float = 1.0,
    random_state: int = 42,
) -> ClusterResult:
    a = corr_matrix.copy()
    np.fill_diagonal(a, 0)
    a_pos = np.maximum(a, 0)
    a_neg = np.maximum(-a, 0)
    n = a.shape[0]

    lsym_pos = _sym_normalized_laplacian(a_pos)
    lsym_neg = _sym_normalized_laplacian(a_neg)

    lhs = lsym_pos + tau_neg * np.eye(n)
    rhs = lsym_neg + tau_pos * np.eye(n)

    # generalized symmetric eigenproblem: lhs v = lambda rhs v, rhs is SPD by construction (tau > 0)
    eigvals, eigvecs = eigh(lhs, rhs)
    embedding = eigvecs[:, :k]  # smallest-k eigenvalues (eigh returns ascending order)

    row_norms = np.linalg.norm(embedding, axis=1, keepdims=True)
    row_norms[row_norms == 0] = 1.0
    embedding_normed = embedding / row_norms

    labels = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit_predict(embedding_normed)
    return ClusterResult(labels=labels, tickers=tickers, k=k, method="sponge_sym")
