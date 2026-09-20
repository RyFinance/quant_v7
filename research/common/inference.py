"""Inference helpers shared by the research scripts.

- `sharpe_ci`: circular-block bootstrap confidence interval for an annualised Sharpe ratio.
- `null_kind`: "Two Kinds of Nothing" (Tan, arXiv 2608.30490). A result whose interval excludes the
  smallest consequential effect is a bounded null (evidence of absence). One whose interval still
  contains that effect is vacuous (absence of evidence).
- `deflated_sharpe`: Bailey & López de Prado (2014) Deflated Sharpe Ratio. It gives the probability
  that the true Sharpe exceeds the maximum expected from N trials with the given dispersion
  (Gençay, arXiv 2608.27734, indexes N to a recorded trial ledger).
"""
from __future__ import annotations

import numpy as np
from scipy.stats import kurtosis, norm, skew

EULER_GAMMA = 0.5772156649015329


def annual_sharpe(x: np.ndarray, periods: int) -> float:
    x = np.asarray(x, dtype=float)
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(periods)) if sd > 0 else float("nan")


def sharpe_ci(x: np.ndarray, periods: int, block: int, draws: int = 5000, level: float = 0.95,
              seed: int = 20260918) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    n = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(draws, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)[:, :n] % n
    s = x[idx]
    sr = s.mean(axis=1) / s.std(axis=1, ddof=1) * np.sqrt(periods)
    a = (1 - level) / 2
    return float(np.quantile(sr, a)), float(np.quantile(sr, 1 - a))


def sharpe_ci_iid(sr_annual: float, years: float, level: float = 0.95) -> tuple[float, float]:
    """Lo (2002) iid approximation, for results where only the summary survives."""
    se = np.sqrt((1 + 0.5 * (sr_annual ** 2) / 252) / years)
    z = norm.ppf(0.5 + level / 2)
    return float(sr_annual - z * se), float(sr_annual + z * se)


def null_kind(ci: tuple[float, float], consequential: float) -> str:
    lo, hi = ci
    if lo > 0:
        return "positive (interval excludes 0)"
    if hi < consequential:
        return f"bounded null (rules out Sharpe >= {consequential})"
    return f"vacuous (cannot rule out Sharpe >= {consequential})"


def deflated_sharpe(x: np.ndarray, n_trials: int, trial_sharpe_var: float) -> float:
    """x: per-period returns. trial_sharpe_var: variance of per-period Sharpe ratios across trials."""
    x = np.asarray(x, dtype=float)
    T = len(x)
    sr = x.mean() / x.std(ddof=1)
    g3, g4 = skew(x), kurtosis(x, fisher=False)
    if n_trials <= 1:
        sr0 = 0.0
    else:
        sr0 = np.sqrt(trial_sharpe_var) * ((1 - EULER_GAMMA) * norm.ppf(1 - 1 / n_trials)
                                           + EULER_GAMMA * norm.ppf(1 - 1 / (n_trials * np.e)))
    denom = np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
    return float(norm.cdf((sr - sr0) * np.sqrt(T - 1) / denom))
