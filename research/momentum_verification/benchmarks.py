"""Measure the return_search stock-momentum candidate against investable benchmarks.

Three questions, all answered with outside data:
  A. universe bias   - equal-weight of the cached (survivor) universe vs RSP, the real equal-weight S&P 500
  B. reality check   - the candidate vs MTUM and SPMO, real momentum funds with point-in-time membership
  C. attribution     - FF5 + UMD regression of the candidate's daily excess return, Newey-West errors
No parameter of the frozen rule is touched here.
"""
from __future__ import annotations
import json, zipfile, io
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / 'reports/momentum_verification_20260919/inputs'
OUT = ROOT / 'reports/momentum_verification_20260919'
SRC = ROOT / 'reports/return_search_20260919'
WINDOWS = {
    'selection 2019..2025-06': ('2019-01-01', '2025-06-30'),
    'evaluation 2025-07..2026-09': ('2025-07-01', '2026-09-17'),
    'continuous 2019..2026': ('2019-01-01', '2026-09-17'),
    'extended 2008..2026': ('2008-01-01', '2026-09-17'),
}


def rf_daily() -> pd.Series:
    """The same cash rate the engine used: prior observable 13-week bill, per elapsed day."""
    d = pd.read_parquet(ROOT / 'data/multiasset/rates/IRX.parquet')
    d.index = pd.to_datetime(d['date']).dt.tz_localize(None).dt.normalize()
    return (d['close'].sort_index() / 100)


def etf_returns(symbol: str) -> pd.Series:
    d = pd.read_parquet(IN / f'{symbol}.parquet')
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    return d['Close'].sort_index().pct_change().dropna()


def nav_returns(path: Path) -> pd.Series:
    d = pd.read_csv(path, parse_dates=['date']).set_index('date')
    return d['return']


def stats(r: pd.Series, rf: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 60:
        return {}
    rate = rf.reindex(rf.index.union(r.index)).ffill().reindex(r.index)
    elapsed = pd.Series(r.index, index=r.index).diff().dt.days.fillna(1)
    ex = r - rate.shift().fillna(0) * elapsed / 365.25
    w = (1 + r).cumprod()
    peak = np.maximum.accumulate(np.r_[1.0, w.to_numpy()])[1:]
    years = len(r) / 252
    return {'cagr': float(w.iloc[-1] ** (1 / years) - 1), 'total': float(w.iloc[-1] - 1),
            'sharpe': float(ex.mean() / ex.std() * np.sqrt(252)),
            'vol': float(r.std() * np.sqrt(252)),
            'max_dd': float(np.min(w.to_numpy() / peak - 1)), 'days': len(r)}


def survivor_equal_weight(start: str, end: str) -> pd.Series:
    """Monthly-rebalanced equal weight of the cached universe, using the engine's own eligibility.

    Same filter as the frozen rule (252 sessions of history, ADV > $20m, top 200 by ADV),
    so the only difference from the momentum book is that it does not select on past return.
    """
    frames = {}
    for p in sorted((ROOT / 'data/multiasset/stocks').glob('*.parquet')):
        d = pd.read_parquet(p)
        d.index = pd.to_datetime(d['date']).dt.tz_localize(None).dt.normalize()
        frames[p.stem] = d.sort_index()
    dates = pd.read_parquet(ROOT / 'data/multiasset/etf/SPY.parquet')
    dates.index = pd.to_datetime(dates['date']).dt.tz_localize(None).dt.normalize()
    dates = dates.sort_index().loc['2007':].index
    close = pd.DataFrame({s: d['close'] for s, d in frames.items()}).reindex(dates).astype(float)
    vol = pd.DataFrame({s: d['volume'] for s, d in frames.items()}).reindex(dates).astype(float)
    adv = (close * vol).rolling(63).mean()
    eligible = close.shift(252).notna() & close.gt(0) & adv.gt(20e6) & adv.rank(axis=1, ascending=False, method='first').le(200)
    month = pd.Series(dates.to_period('M'), index=dates)
    rebalance = month.ne(month.shift())
    r = close.pct_change(fill_method=None)
    out = []
    held = None
    for date in dates:
        if rebalance.loc[date]:
            names = eligible.loc[date]
            held = list(names.index[names])
        if held and date >= pd.Timestamp(start):
            out.append((date, float(r.loc[date, held].mean())))
    s = pd.Series(dict(out)).loc[start:end]
    return s


def ff_factors() -> pd.DataFrame:
    def load(name, skip):
        with zipfile.ZipFile(IN / name) as z:
            raw = z.read(z.namelist()[0]).decode('latin-1')
        rows = [l for l in raw.splitlines() if l[:8].strip().isdigit() and len(l[:8].strip()) == 8]
        df = pd.read_csv(io.StringIO('\n'.join(rows)), header=None)
        df.index = pd.to_datetime(df[0].astype(str), format='%Y%m%d')
        return df.drop(columns=[0])
    five = load('F-F_Research_Data_5_Factors_2x3_daily_CSV.zip', 3)
    five.columns = ['MktRF', 'SMB', 'HML', 'RMW', 'CMA', 'RF']
    mom = load('F-F_Momentum_Factor_daily_CSV.zip', 13)
    mom.columns = ['UMD']
    return pd.concat([five, mom], axis=1).dropna() / 100


def ols_hac(y: np.ndarray, X: np.ndarray, lags: int = 10):
    n, k = X.shape
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = (X[L:] * resid[L:, None]).T @ (X[:-L] * resid[:-L, None])
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    return beta, se, beta / se


def main():
    OUT.mkdir(exist_ok=True)
    rf = rf_daily()
    series = {
        'candidate stocks__momentum (2019..2026)': nav_returns(SRC / 'diagnostics/stocks__momentum_continuous_base.csv'),
        'candidate stocks__momentum (2008..2026)': nav_returns(SRC / 'diagnostics/stocks__momentum_2008_base.csv'),
        'RSP  equal-weight S&P 500 (real)': etf_returns('RSP'),
        'MTUM iShares momentum (real)': etf_returns('MTUM'),
        'SPMO Invesco S&P momentum (real)': etf_returns('SPMO'),
        'SPY': etf_returns('SPY'),
    }
    print('computing survivor-universe equal weight...', flush=True)
    sew = survivor_equal_weight('2008-01-01', '2026-09-17')
    series['survivor-universe equal weight (ours)'] = sew

    table = {}
    for label, (a, b) in WINDOWS.items():
        table[label] = {}
        for name, s in series.items():
            st = stats(s.loc[a:b], rf)
            if st:
                table[label][name] = st
    (OUT / 'benchmarks.json').write_text(json.dumps(table, indent=2))

    for label in WINDOWS:
        print(f'\n=== {label} ===')
        print(f'{"series":44s} {"CAGR":>8s} {"Sharpe":>7s} {"vol":>7s} {"maxDD":>8s} {"days":>6s}')
        for name, st in table[label].items():
            print(f'{name:44s} {st["cagr"]*100:7.2f}% {st["sharpe"]:7.2f} {st["vol"]*100:6.1f}% {st["max_dd"]*100:7.2f}% {st["days"]:6d}')

    # C. attribution
    ff = ff_factors()
    print('\n=== FF5 + UMD attribution, Newey-West(10) ===')
    attribution = {}
    for name, key in [('2019..2026', 'candidate stocks__momentum (2019..2026)'),
                      ('2008..2026', 'candidate stocks__momentum (2008..2026)')]:
        r = series[key]
        j = ff.reindex(r.index).dropna()
        y = (r.reindex(j.index) - j['RF']).to_numpy()
        X = np.column_stack([np.ones(len(j))] + [j[c].to_numpy() for c in ['MktRF', 'SMB', 'HML', 'RMW', 'CMA', 'UMD']])
        beta, se, t = ols_hac(y, X)
        names = ['alpha', 'MktRF', 'SMB', 'HML', 'RMW', 'CMA', 'UMD']
        attribution[name] = {n: {'beta': float(b), 'se': float(s), 't': float(tt)} for n, b, s, tt in zip(names, beta, se, t)}
        attribution[name]['alpha']['annual'] = float(beta[0] * 252)
        attribution[name]['n_days'] = len(j)
        print(f'\n{name}  (n={len(j)})')
        print(f'  annual alpha {beta[0]*252*100:6.2f}%   t = {t[0]:5.2f}')
        for n, b, tt in list(zip(names, beta, t))[1:]:
            print(f'  {n:6s} {b:7.3f}  t = {tt:6.2f}')
    (OUT / 'attribution.json').write_text(json.dumps(attribution, indent=2))


if __name__ == '__main__':
    main()
