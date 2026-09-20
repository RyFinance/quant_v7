"""Residual momentum scores (Blitz, Huij & Martens 2011) for the momentum lab.

Batched rolling factor regressions: at each monthly decision date one design matrix is built from
the trailing 756 sessions and every stock is solved simultaneously with masked normal equations,
so missing observations are excluded rather than filled.

Windows (session positions relative to the decision date t at position i):
  estimation  i-755 .. i          756 sessions ending at the decision date (all data known at t)
  scoring     i-251 .. i-21       the 12-1 span, exactly the daily returns whose product is the
                                  baseline's close.shift(21)/close.shift(252) - 1
"""
from __future__ import annotations
import numpy as np
import pandas as pd

EST = 756          # trailing sessions in the factor regression
SKIP = 21          # last month skipped
LOOKBACK = 252     # 12-month lookback


def _prep(lab):
    """Daily excess returns (T x N), factor frame aligned to the panel index, and validity masks."""
    ret = lab.close.pct_change(fill_method=None)
    f = lab.factors.reindex(lab.dates)
    rf = f['RF']
    ex = ret.sub(rf, axis=0)
    ok_f = f['MktRF'].notna().to_numpy()              # factor row present on this session
    finite = np.isfinite(ret.to_numpy())              # stock has a return on this session
    Y = np.where(np.isfinite(ex.to_numpy()), ex.to_numpy(), 0.0)
    return ret, f, Y, finite, ok_f


def residual_scores(lab, factors=('MktRF',), standardise=False, verbose=False, fill=True):
    """Score = sum of regression residuals over the 12-1 window (optionally / their sd).

    A stock is eligible at a date only if it has a return on every factor-available session in both
    the estimation window and the scoring window. Gaps are never filled.
    """
    ret, f, Y, finite, ok_f = _prep(lab)
    F = f[list(factors)].to_numpy()
    F = np.where(np.isfinite(F), F, 0.0)
    T, N = Y.shape
    p = len(factors) + 1
    dates = lab.dates
    dec = np.flatnonzero(lab.decision['M'].to_numpy() & (dates >= '2011-01-01'))
    out = np.full((T, N), np.nan)
    for i in dec:
        if i < EST - 1:
            continue
        e0, e1 = i - EST + 1, i + 1                    # estimation rows [e0, e1)
        s0, s1 = i - LOOKBACK + 1, i - SKIP + 1        # scoring rows [s0, s1)
        okf = ok_f[e0:e1]
        X = np.column_stack([np.ones(e1 - e0), F[e0:e1]])
        X = X * okf[:, None]                           # zero out factor-missing rows
        V = (finite[e0:e1] & okf[:, None]).astype(float)   # (EST, N) valid observations
        need_est = okf.sum()
        sl = slice(s0 - e0, s1 - e0)
        need_sc = okf[sl].sum()
        elig = (V.sum(0) == need_est) & (V[sl].sum(0) == need_sc)
        if not elig.any():
            continue
        j = np.flatnonzero(elig)
        Yw = Y[e0:e1][:, j] * V[:, j]
        A = (X[:, :, None] * X[:, None, :]).reshape(e1 - e0, p * p)
        XtX = (A.T @ V[:, j]).T.reshape(-1, p, p)      # (n_elig, p, p)
        Xty = (X.T @ Yw).T[:, :, None]                 # (n_elig, p, 1)
        beta = np.linalg.solve(XtX, Xty)[:, :, 0]      # (n_elig, p)
        R = (Y[s0:s1][:, j] - X[sl] @ beta.T) * V[sl][:, j]
        n = V[sl][:, j].sum(0)
        score = R.sum(0)
        if standardise:
            mu = score / n
            sd = np.sqrt(((R - mu * V[sl][:, j]) ** 2).sum(0) / (n - 1))
            score = np.where(sd > 0, score / sd, np.nan)
        out[i, j] = score
        if verbose:
            print(f'  {dates[i].date()} eligible={len(j)} est_rows={int(need_est)} sc_rows={int(need_sc)}')
    s = pd.DataFrame(out, index=dates, columns=lab.close.columns)
    return s.ffill() if fill else s


def risk_adjusted_raw(lab):
    """R4 control: the baseline's raw 12-1 return divided by trailing 252-session daily vol."""
    raw = lab.close.shift(SKIP) / lab.close.shift(LOOKBACK) - 1
    vol = lab.close.pct_change(fill_method=None).rolling(LOOKBACK).std()
    s = raw / vol.where(vol > 0)
    dec = lab.decision['M'].to_numpy() & (lab.dates >= '2011-01-01')
    v = np.where(dec[:, None], s.to_numpy(), np.nan)
    return pd.DataFrame(v, index=lab.dates, columns=s.columns).ffill()


def verify(lab, factors=('MktRF',), standardise=False, n_checks=6, seed=0):
    """Check the batched path against an obviously-correct per-stock loop on a few stock-months."""
    ret, f, Y, finite, ok_f = _prep(lab)
    fast = residual_scores(lab, factors=factors, standardise=standardise, fill=False)
    dates = lab.dates
    dec = np.flatnonzero(lab.decision['M'].to_numpy() & (dates >= '2011-01-01'))
    rng = np.random.default_rng(seed)
    cols = list(lab.close.columns)
    checks, tried = [], 0
    while len(checks) < n_checks and tried < 400:
        tried += 1
        i = int(rng.choice(dec))
        jname = cols[int(rng.integers(len(cols)))]
        v = fast.iloc[i][jname]
        if not np.isfinite(v) or not lab.decision['M'].iloc[i]:
            continue
        e0, e1 = i - EST + 1, i + 1
        s0, s1 = i - LOOKBACK + 1, i - SKIP + 1
        # slow, obviously correct: one stock, one date, explicit masking and lstsq
        yser = (ret[jname] - f['RF']).iloc[e0:e1]
        Xser = f[list(factors)].iloc[e0:e1]
        m = yser.notna() & Xser.notna().all(axis=1)
        Xs = np.column_stack([np.ones(int(m.sum())), Xser[m].to_numpy()])
        b = np.linalg.lstsq(Xs, yser[m].to_numpy(), rcond=None)[0]
        ysc = (ret[jname] - f['RF']).iloc[s0:s1]
        Xsc = f[list(factors)].iloc[s0:s1]
        msc = ysc.notna() & Xsc.notna().all(axis=1)
        resid = ysc[msc].to_numpy() - np.column_stack(
            [np.ones(int(msc.sum())), Xsc[msc].to_numpy()]) @ b
        slow = resid.sum() / (resid.std(ddof=1) if standardise else 1.0)
        checks.append((str(dates[i].date()), jname, float(v), float(slow), abs(v - slow)))
    return checks
