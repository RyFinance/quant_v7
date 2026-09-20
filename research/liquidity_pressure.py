"""Purged annual walk-forward learning of five-day residual price pressure."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from backtest.research import simulate_weights
from research.higher_sharpe import cash_rates
from research.etf_convergence_screen import metrics
from research.fx_session_screen import bootstrap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/liquidity_pressure_20260918'
SPEC = ROOT / 'research/liquidity_pressure_spec_20260918.json'


def load():
    spec = json.loads(SPEC.read_text())
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == json.loads((OUT/'registration.json').read_text())['spec_sha256']
    frames, hashes = {}, {}
    paths = sorted((ROOT/'data/multiasset/stocks').glob('*.parquet')) + [ROOT/'data/multiasset/etf/SPY.parquet']
    for p in paths:
        hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        d = pd.read_parquet(p).set_index('date').sort_index()
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        if d.index.has_duplicates:
            raise ValueError(f'duplicate dates {p}')
        frames[p.stem] = d.loc[:'2025-06-27']
    dates = frames['SPY'].index
    panels = {field: pd.DataFrame({s: d[field] for s, d in frames.items()}).reindex(dates)
              for field in ['open', 'close', 'volume']}
    (OUT/'input_hashes.json').write_text(json.dumps(hashes, indent=2))
    return spec, panels


def build_features(panels):
    c, o, v = (panels[k] for k in ['close', 'open', 'volume'])
    r = c.pct_change(fill_method=None)
    mr = r.SPY
    beta = r.rolling(126, min_periods=100).cov(mr).div(mr.rolling(126, min_periods=100).var(), axis=0).clip(0, 3)
    beta['SPY'] = 1
    residual = r - beta.shift().mul(mr, axis=0)
    intraday = c / o - 1
    overnight = o / c.shift() - 1
    ir = intraday - beta.shift().mul(intraday.SPY, axis=0)
    nr = overnight - beta.shift().mul(overnight.SPY, axis=0)
    vol20 = r.rolling(20).std()
    resvol = residual.rolling(20).std()
    mom = c.shift(21) / c.shift(252) - 1
    relvol = v / v.rolling(20).mean()
    names = c.columns
    market5 = pd.DataFrame(np.repeat(mr.rolling(5).sum().to_numpy()[:, None], len(names), axis=1), index=c.index, columns=names)
    marketvol = pd.DataFrame(np.repeat(mr.rolling(20).std().to_numpy()[:, None], len(names), axis=1), index=c.index, columns=names)
    fields = [residual, residual.rolling(5).sum(), residual.rolling(21).sum(), mom,
              ir, nr, relvol, vol20, vol20 / r.rolling(126).std(), c / c.rolling(200).mean() - 1,
              market5, marketvol]
    x = np.stack([f.to_numpy(dtype=np.float32) for f in fields], axis=2)
    adv = (c * v).rolling(63).mean()
    eligible = c.shift(252).notna() & c.notna() & (adv > 20e6)
    eligible['SPY'] = False
    eligible &= adv.where(eligible).rank(axis=1, method='first', ascending=False) <= 300
    eligible &= np.isfinite(x).all(axis=2)
    future = o.shift(-6) / o.shift(-1) - 1
    label = future - beta.mul(future.SPY, axis=0)
    return x, label, eligible, beta, dict(residual=residual, resvol=resvol, mom=mom,
                                        relvol=relvol, overnight=nr, vol20=vol20)


def walk_forward(x, label, eligible, dates):
    y = label.to_numpy(dtype=np.float32)
    e = eligible.to_numpy()
    outputs = {n: np.full(y.shape, np.nan, dtype=np.float32) for n in ['ridge', 'gradient_boost']}
    audit = []
    day_index = np.arange(len(dates))
    for year in range(2017, 2026):
        cutoff = dates.searchsorted(pd.Timestamp(f'{year}-01-01'))
        train_dates = (dates >= '2010-01-01') & (day_index + 6 < cutoff) & (day_index % 2 == 0)
        test_dates = (dates.year == year)
        train_mask = train_dates[:, None] & e & np.isfinite(y)
        test_mask = test_dates[:, None] & e
        tx, ty, vx = x[train_mask], np.clip(y[train_mask], -.2, .2), x[test_mask]
        row = {'year': year, 'training_samples': len(ty), 'prediction_samples': len(vx),
               'last_training_signal': str(dates[np.where(train_dates)[0][-1]].date()),
               'last_training_label_end': str(dates[np.where(train_dates)[0][-1] + 6].date()),
               'first_prediction_date': str(dates[test_dates][0].date())}
        assert row['last_training_label_end'] < row['first_prediction_date']
        models = {'ridge': make_pipeline(StandardScaler(), Ridge(alpha=1000)),
                  'gradient_boost': HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=15,
                     learning_rate=.05, min_samples_leaf=200, l2_regularization=10,
                     early_stopping=False, random_state=20260918)}
        for name, model in models.items():
            model.fit(tx, ty)
            outputs[name][test_mask] = model.predict(vx)
            print(f'{year} {name}: trained {len(ty):,}, predicted {len(vx):,}', flush=True)
        audit.append(row)
        (OUT/'training_audit.json').write_text(json.dumps(audit, indent=2))
    return {n: pd.DataFrame(a, index=dates, columns=label.columns) for n, a in outputs.items()}


def cohort_targets(score, eligible, beta, long_only=False, thresholds=True):
    cohort = pd.DataFrame(0., index=score.index, columns=score.columns)
    for date in score.index:
        s = score.loc[date].where(eligible.loc[date]).dropna()
        if not len(s):
            continue
        if thresholds:
            s = s - s.mean()
            longs, shorts = s[s > .001].nlargest(10), s[s < -.0016].nsmallest(10)
        else:
            longs, shorts = s[s > 0].nlargest(10), s[s < 0].nsmallest(10)
        cohort.loc[date, longs.index] = .01
        if not long_only:
            cohort.loc[date, shorts.index] = -.01
    target = cohort.rolling(5, min_periods=1).sum()
    target['SPY'] = -(target * beta.fillna(0)).sum(axis=1)
    gross = target.abs().sum(axis=1)
    return target.div(gross.clip(lower=1), axis=0)


def construct_targets(predictions, eligible, beta, rule):
    targets = {n: cohort_targets(s, eligible, beta) for n, s in predictions.items()}
    z1 = rule['residual'] / rule['resvol']
    shock = eligible & (z1.abs() >= 1.5) & (rule['relvol'] >= 1.5) & (rule['overnight'].abs() <= .5 * rule['vol20'])
    targets['liquidity_shock'] = cohort_targets(-z1, shock, beta, thresholds=False)
    z5 = rule['residual'].rolling(5).sum() / (rule['resvol'] * np.sqrt(5))
    pullback = eligible & (z5 <= -1) & (rule['mom'] > 0)
    targets['trend_pullback'] = cohort_targets(-z5, pullback, beta, long_only=True, thresholds=False)
    return targets


def period_stats(frame, rf, a, b):
    d = frame.loc[a:b]
    m = metrics(d['return'], rf)
    m.update(average_gross=float(d.gross.mean()), annual_one_way_turnover=float(d.turnover.mean() * 252),
             annual_borrow_drag=float(d.borrow.mean() * 252))
    return m


def main():
    spec, p = load()
    x, y, eligible, beta, rules = build_features(p)
    cache = OUT/'predictions'
    cache.mkdir(exist_ok=True)
    if all((cache/f'{n}.parquet').exists() for n in ['ridge', 'gradient_boost']):
        predictions = {n: pd.read_parquet(cache/f'{n}.parquet') for n in ['ridge', 'gradient_boost']}
    else:
        predictions = walk_forward(x, y, eligible, p['close'].index)
        for n, f in predictions.items():
            f.to_parquet(cache/f'{n}.parquet')
    targets = construct_targets(predictions, eligible, beta, rules)
    rf = cash_rates().reindex(p['close'].index)
    cap = pd.Series(.05, index=p['close'].columns); cap['SPY'] = .60
    result, paths = {}, {}
    for name, target in targets.items():
        result[name] = {}
        target.to_parquet(OUT/f'{name}_targets.parquet')
        for label, cost, borrow in [('base', 10, .03), ('stress', 25, .10)]:
            frame = simulate_weights(p['open'], p['close'], target, '2017-01-01', '2025-06-27',
                                     gross_cap=1, position_cap=cap, cost_bps=cost, borrow_rate=borrow,
                                     cash_returns=rf)
            paths[name, label] = frame
            frame.to_csv(OUT/f'{name}_{label}.csv')
            result[name][label] = {'selection': period_stats(frame, rf, '2017', '2020'),
                                    'evaluation': period_stats(frame, rf, '2021', '2025-06-27')}
        print(name, 'selection', result[name]['base']['selection']['excess_sharpe'], flush=True)
    selected = max(result, key=lambda n: result[n]['base']['selection']['excess_sharpe'])
    (OUT/'selection.json').write_text(json.dumps({'name': selected, 'selection_basis': '2017-2020 excess Sharpe only'}, indent=2))
    original = list(result)
    result['fixed_blend'] = {}
    for label in ['base', 'stress']:
        nav = pd.concat([paths[n, label].nav for n in original], axis=1).mean(axis=1)
        ret = nav.pct_change(); ret.iloc[0] = nav.iloc[0] - 1
        f = pd.DataFrame({'nav': nav, 'return': ret})
        f.to_csv(OUT/f'fixed_blend_{label}.csv')
        paths['fixed_blend', label] = f
        result['fixed_blend'][label] = {period: metrics(f.loc[a:b, 'return'], rf)
             for period, a, b in [('selection', '2017', '2020'), ('evaluation', '2021', '2025-06-27')]}
    for n in result:
        f = paths[n, 'base']
        result[n]['yearly'] = {str(year): metrics(group['return'], rf)
                               for year, group in f.groupby(f.index.year)}
    ex = paths[selected, 'base'].loc['2021':, 'return'] - rf
    ci = bootstrap(ex.dropna(), 20); ci.pop('three_candidate_bonferroni_p')
    ci['five_portfolio_bonferroni_p'] = min(1, 5 * ci['one_sided_null_p'])
    r = result[selected]
    meets = r['base']['evaluation']['excess_sharpe'] >= 2 and r['base']['evaluation']['cagr'] > .1
    gate = (meets and r['stress']['evaluation']['ann_excess_mean'] > 0
            and all(r['yearly'][str(yr)]['ann_excess_mean'] > 0 for yr in range(2021, 2025))
            and ci['five_portfolio_bonferroni_p'] < .05)
    result['decision'] = {'selected': selected, 'numerical_target_met': bool(meets),
                          'research_gate_met': bool(gate), 'selected_uncertainty': ci,
                          'live_configuration_changed': False}
    result['code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'results.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    for n in original + ['fixed_blend']:
        print(n, 'EVALUATION', result[n]['base']['evaluation'], 'STRESS', result[n]['stress']['evaluation'], flush=True)
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
