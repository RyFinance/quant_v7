"""Window-by-window comparison of the biased and de-biased arms against buyable funds."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import research.momentum_verification.benchmarks as bm

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports/momentum_verification_20260919'
WINDOWS = {
    'selection 2019..2025-06': ('2019-01-01', '2025-06-30'),
    'evaluation 2025-07..2026-09': ('2025-07-01', '2026-09-17'),
    'continuous 2019..2026': ('2019-01-01', '2026-09-17'),
    'extended 2008..2026': ('2008-01-01', '2026-09-17'),
}


def main():
    rf = bm.rf_daily()
    ff = bm.ff_factors()
    series = {
        'A  frozen rule, cache universe': bm.nav_returns(OUT / 'A_cache_universe_2008..2026.csv'),
        'B  same rule, index members only': bm.nav_returns(OUT / 'B_point_in_time_members_2008..2026.csv'),
        'survivor-universe equal weight': bm.survivor_equal_weight('2008-01-01', '2026-09-17'),
        'SPMO  real momentum fund': bm.etf_returns('SPMO'),
        'MTUM  real momentum fund': bm.etf_returns('MTUM'),
        'RSP   real equal-weight S&P': bm.etf_returns('RSP'),
        'SPY': bm.etf_returns('SPY'),
    }
    # the 2019-start arms are separately funded runs; prefer them inside their own window
    series_2019 = dict(series)
    series_2019['A  frozen rule, cache universe'] = bm.nav_returns(OUT / 'A_cache_universe_2019..2026.csv')
    series_2019['B  same rule, index members only'] = bm.nav_returns(OUT / 'B_point_in_time_members_2019..2026.csv')

    table = {}
    for label, (a, b) in WINDOWS.items():
        src = series if label.startswith('extended') else series_2019
        table[label] = {n: st for n, s in src.items() if (st := bm.stats(s.loc[a:b], rf))}
        print(f'\n=== {label} ===')
        print(f'{"series":36s} {"CAGR":>8s} {"Sharpe":>7s} {"vol":>7s} {"maxDD":>8s}')
        for n, st in table[label].items():
            print(f'{n:36s} {st["cagr"]*100:7.2f}% {st["sharpe"]:7.2f} {st["vol"]*100:6.1f}% {st["max_dd"]*100:7.2f}%')
    (OUT / 'final_table.json').write_text(json.dumps(table, indent=2))

    print('\n=== FF5 + UMD alpha, Newey-West(10), 2019-01-01..2026-09-17 ===')
    print(f'{"series":36s} {"alpha/yr":>9s} {"t":>6s} {"mkt":>6s} {"UMD":>6s}')
    attribution = {}
    for n, s in series_2019.items():
        r = s.loc['2019-01-01':'2026-09-17']
        j = ff.reindex(r.index).dropna()
        if len(j) < 250:
            continue
        y = (r.reindex(j.index) - j['RF']).to_numpy()
        X = np.column_stack([np.ones(len(j))] + [j[c].to_numpy() for c in ['MktRF', 'SMB', 'HML', 'RMW', 'CMA', 'UMD']])
        beta, se, t = bm.ols_hac(y, X)
        attribution[n] = {'alpha_annual': float(beta[0] * 252), 't': float(t[0]),
                          'mkt': float(beta[1]), 'umd': float(beta[6]), 'n': len(j)}
        print(f'{n:36s} {beta[0]*252*100:8.2f}% {t[0]:6.2f} {beta[1]:6.2f} {beta[6]:6.2f}')
    (OUT / 'final_attribution.json').write_text(json.dumps(attribution, indent=2))


if __name__ == '__main__':
    main()
