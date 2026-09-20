"""Four preregistered ETF convergence screens; no trading side effects."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

from backtest.research import simulate_weights
from research.higher_sharpe import cash_rates
from research.fx_session_screen import bootstrap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/etf_convergence_20260918'
SPEC = ROOT / 'research/etf_convergence_spec_20260918.json'


def target_weights(close):
    a, b = np.log(close.iloc[:, 0]), np.log(close.iloc[:, 1])
    ma, mb = a.rolling(252).mean(), b.rolling(252).mean()
    va, vb = a.rolling(252).var(), b.rolling(252).var()
    cov = a.rolling(252).cov(b)
    beta = cov / vb
    sd = np.sqrt((va - cov**2 / vb).clip(lower=0))
    z = (a - ma - beta * (b - mb)) / sd
    t = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    held, age, entry_sign = False, 0, 0
    for i in range(len(close)):
        if held:
            age += 1
            if (not np.isfinite(z.iloc[i]) or not .25 <= beta.iloc[i] <= 4
                    or abs(z.iloc[i]) <= .5 or np.sign(z.iloc[i]) != entry_sign or age >= 20):
                t.iloc[i] = 0
                held = False
        elif np.isfinite(z.iloc[i]) and .25 <= beta.iloc[i] <= 4 and abs(z.iloc[i]) >= 2:
            entry_sign = np.sign(z.iloc[i])
            w = -entry_sign / (1 + beta.iloc[i])
            t.iloc[i] = [w, -w * beta.iloc[i]]
            held, age = True, 0
        else:
            t.iloc[i] = 0
    return t


def metrics(r, rf):
    ex = r - rf.reindex(r.index)
    if ex.isna().any():
        raise ValueError('missing risk-free data')
    nav = (1 + r).cumprod()
    return {'excess_sharpe': float(ex.mean() / ex.std(ddof=1) * np.sqrt(252)),
            'ann_excess_mean': float(ex.mean() * 252),
            'cagr': float(nav.iloc[-1] ** (252 / len(r)) - 1),
            'vol': float(r.std(ddof=1) * np.sqrt(252)),
            'max_dd': float((nav / nav.cummax().clip(lower=1) - 1).min())}


def main():
    spec = json.loads(SPEC.read_text())
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == json.loads((OUT/'registration.json').read_text())['spec_sha256']
    symbols = sorted({s for pair in spec['pairs'] for s in pair})
    panels, hashes = {}, {}
    for s in symbols:
        p = ROOT / f'data/multiasset/etf/{s}.parquet'
        hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        d = pd.read_parquet(p).set_index('date').sort_index()
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        if d.index.has_duplicates:
            raise ValueError('duplicate prices')
        panels[s] = d.loc[:'2017-12-31']
    dates = panels['SPY'].index
    rf = cash_rates().reindex(dates)
    hashes['reports/higher_sharpe/inputs/french_daily.zip'] = hashlib.sha256((ROOT/'reports/higher_sharpe/inputs/french_daily.zip').read_bytes()).hexdigest()
    (OUT/'input_hashes.json').write_text(json.dumps(hashes, indent=2))
    result, paths = {}, {}
    for pair in spec['pairs']:
        name = '_'.join(pair)
        opens = pd.DataFrame({s: panels[s].open for s in pair}).reindex(dates)
        closes = pd.DataFrame({s: panels[s].close for s in pair}).reindex(dates)
        targets = target_weights(closes)
        result[name] = {}
        for label, costs in [('base', spec['base_costs']), ('stress', spec['stress_costs'])]:
            frame = simulate_weights(opens, closes, targets, '2008-01-01', '2017-12-31',
                                     gross_cap=1, position_cap=1,
                                     cost_bps=costs['round_trip_bps'], borrow_rate=costs['annual_short_borrow'],
                                     cash_returns=rf)
            frame.to_csv(OUT/f'{name}_{label}.csv')
            paths[name, label] = frame
            result[name][label] = {period: metrics(frame.loc[a:b, 'return'], rf)
                                  for period, (a, b) in [('development', spec['development']), ('validation', spec['validation'])]}
            result[name][label]['annual_one_way_turnover'] = float(frame.turnover.mean() * 252)
    selected = max(result, key=lambda n: result[n]['base']['development']['excess_sharpe'])
    (OUT/'selection.json').write_text(json.dumps({'selected': selected, 'basis': 'development excess Sharpe only'}, indent=2))
    for label in ['base', 'stress']:
        # Equal initial capital, buy-and-hold sleeve allocation: no hidden daily
        # rebalancing at the composite level or unpaid reallocations.
        nav = pd.concat([paths[n, label].nav for n in result], axis=1).mean(axis=1)
        r = nav.pct_change(); r.iloc[0] = nav.iloc[0] - 1
        pd.DataFrame({'nav': nav, 'return': r}).to_csv(OUT/f'fixed_blend_{label}.csv')
        paths['fixed_blend', label] = r
    result['fixed_blend'] = {label: {period: metrics(paths['fixed_blend', label].loc[a:b], rf)
                                     for period, (a, b) in [('development', spec['development']), ('validation', spec['validation'])]}
                              for label in ['base', 'stress']}
    for block in [20, 63]:
        ex = paths[selected, 'base']['return'].loc['2014':'2017'] - rf
        ci = bootstrap(ex.dropna(), block)
        ci.pop('three_candidate_bonferroni_p')
        ci['four_candidate_bonferroni_p'] = min(1, 4 * ci['one_sided_null_p'])
        result[selected][f'uncertainty_{block}d'] = ci
    s = result[selected]
    gate = (s['base']['development']['excess_sharpe'] >= .5 and s['base']['validation']['excess_sharpe'] >= .75
            and s['stress']['validation']['ann_excess_mean'] > 0 and s['uncertainty_20d']['four_candidate_bonferroni_p'] < .05)
    result['decision'] = {'selected': selected, 'passes_pilot_gate': bool(gate), 'later_data_evaluated': False}
    result['code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'results.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    for n, x in result.items():
        if isinstance(x, dict) and 'base' in x:
            print(n, 'dev', x['base']['development']['excess_sharpe'], 'validation', x['base']['validation'], 'stress', x['stress']['validation']['excess_sharpe'])
    print(result['decision'])


if __name__ == '__main__':
    main()
