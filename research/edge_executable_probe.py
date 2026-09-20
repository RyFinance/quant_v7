"""Controlled earnings-feature comparison and next-open execution diagnostic.

Predeclared direction: fade high vs low returns. 20-session holding period.
No production changes. Labels use raw adjusted price ratios, not fitted residuals.
This is an event study, NOT a capital-constrained portfolio backtest.
"""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/edge_executable_probe'
FEATURES = ['cached_5', 'prior_5', 'cached_20', 'prior_20', 'raw_reaction', 'raw_prior_20']


def load_price(path):
    d = pd.read_parquet(path).set_index('timestamp').sort_index()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    assert d.index.is_unique
    return d


def spread_stats(g, rng):
    """Fade low/high deciles, half notional each. Calendar-quarter block CI.

    Resampling event quarters respects contemporaneous clustering approximately;
    not overlapping cross-quarter trades or all serial dependence.
    """
    z = g[g.bucket.isin([0, 9])].copy()
    lo, hi = z[z.bucket == 0], z[z.bucket == 9]
    if lo.empty or hi.empty:
        return {'n_low': len(lo), 'n_high': len(hi)}
    gross = (lo.raw_forward.mean() - hi.raw_forward.mean()) / 2
    excess = (lo.spy_excess.mean() - hi.spy_excess.mean()) / 2
    # 3% p.a. borrow on half short notional, using actual calendar holding days.
    borrow = .5 * .03 * hi.hold_days.mean() / 365
    z['q'] = z.date.dt.to_period('Q').astype(str)
    blocks = z.groupby(['q', 'bucket']).raw_forward.agg(['sum', 'count']).unstack(fill_value=0)
    blocks = blocks.reindex(columns=pd.MultiIndex.from_product([['sum', 'count'], [0, 9]]), fill_value=0)
    arr = blocks.to_numpy()
    boot = []
    for _ in range(2000):
        sample = arr[rng.integers(len(arr), size=len(arr))].sum(axis=0)
        if sample[2] and sample[3]:
            boot.append((sample[0] / sample[2] - sample[1] / sample[3]) / 2)
    ci = np.quantile(boot, [.025, .975]) if boot else [np.nan, np.nan]
    return {'n_low': len(lo), 'n_high': len(hi), 'quarters': len(blocks),
            'raw_gross_bps': gross * 10000, 'spy_excess_gross_bps': excess * 10000,
            'borrow_bps': borrow * 10000,
            **{f'net_{cost}bps': gross * 10000 - borrow * 10000 - cost for cost in [10, 25, 50]},
            'gross_ci_low_bps': ci[0] * 10000, 'gross_ci_high_bps': ci[1] * 10000,
            'residual_gross_bps': (lo.forward_return.mean() - hi.forward_return.mean()) * 5000}


def main():
    OUT.mkdir(exist_ok=True)
    spec = {'features': FEATURES, 'direction': 'long bottom decile, short top decile, half each',
            'cutoffs': 'Training <=2020; validation 2021-23; confirmation 2024+',
            'holding': 'Next session open to close of twentieth held session',
            'cost_bps_roundtrip': [10, 25, 50], 'annual_short_borrow': .03,
            'fit_thresholds': 'Training deciles only; no later-period tuning',
            'multiplicity': 'Six feature comparisons, three periods; CIs unadjusted descriptive only',
            'status': 'Historical windows were studied before; none is a virgin holdout'}
    (OUT / 'specification.json').write_text(json.dumps(spec, indent=2))
    f = pd.read_parquet(ROOT / 'data/pead_labeled_features_expanded.parquet')
    r = pd.read_parquet(ROOT / 'data/residual_returns_wide_expanded.parquet').sort_index()
    assert r.index.is_unique and not f.duplicated(['date', 'ticker']).any()
    i, j = r.index.get_indexer(f.date), r.columns.get_indexer(f.ticker)
    assert (i > 0).all() and (j >= 0).all()
    for w in [5, 20]:
        a = r.rolling(w).sum().to_numpy()
        f[f'cached_{w}'] = f[f'pre_earnings_return_{w}d']
        f[f'prior_{w}'] = a[i - 1, j]
        assert np.allclose(f[f'cached_{w}'], a[i, j], equal_nan=True)
    spy = load_price(ROOT / 'data/raw_legacy/SPY.parquet')
    calendar = spy.index
    frames, skipped, hashes = [], {}, {}
    for ticker, group in f.groupby('ticker'):
        path = ROOT / 'data/raw' / f'{ticker}.parquet'
        if not path.exists():
            skipped[ticker] = 'missing file'
            continue
        hashes[ticker] = hashlib.sha256(path.read_bytes()).hexdigest()
        p = load_price(path).reindex(calendar)
        k = calendar.get_indexer(group.date)
        valid = (k >= 21) & (k + 20 < len(calendar))
        g, k = group.loc[valid].copy(), k[valid]
        g['entry_date'] = calendar[k + 1]
        g['exit_date'] = calendar[k + 20]
        g['hold_days'] = (g.exit_date - g.entry_date).dt.days
        op, cl = p.open.to_numpy(), p.close.to_numpy()
        g['raw_reaction'] = cl[k] / cl[k - 1] - 1
        g['raw_prior_20'] = cl[k - 1] / cl[k - 21] - 1
        g['raw_forward'] = cl[k + 20] / op[k + 1] - 1
        market = spy.close.to_numpy()[k + 20] / spy.open.to_numpy()[k + 1] - 1
        g['spy_excess'] = g.raw_forward - market
        assert (g.entry_date > g.date).all() and (g.exit_date >= g.entry_date).all()
        frames.append(g)
    d = pd.concat(frames, ignore_index=True)
    before = len(d)
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES + ['raw_forward', 'spy_excess'])
    assert (d.raw_forward >= -1).all()
    d['period'] = np.select([d.date.dt.year <= 2020, d.date.dt.year <= 2023],
                            ['discovery', 'validation'], default='confirmation')
    for boundary in [pd.Timestamp('2021-01-01'), pd.Timestamp('2024-01-01')]:
        d = d[~((d.date < boundary) & (d.exit_date >= boundary))]
    d.to_parquet(OUT / 'events.parquet', index=False)
    rng = np.random.default_rng(17092026)
    rows, yearly, deciles, edges = [], [], [], {}
    for feature in FEATURES:
        bins = np.quantile(d.loc[d.period == 'discovery', feature], np.linspace(0, 1, 11))
        bins[0], bins[-1] = -np.inf, np.inf
        edges[feature] = bins[1:-1].tolist()
        x = d.copy()
        x['bucket'] = pd.cut(x[feature], bins, labels=False, include_lowest=True)
        for period, g in x.groupby('period'):
            rows.append({'feature': feature, 'period': period, **spread_stats(g, rng)})
            for bucket, v in g.groupby('bucket'):
                deciles.append({'feature': feature, 'period': period, 'decile': int(bucket) + 1,
                                'n': len(v), 'raw_mean_bps': v.raw_forward.mean() * 10000,
                                'residual_mean_bps': v.forward_return.mean() * 10000})
        for year, g in x.groupby(x.date.dt.year):
            yearly.append({'feature': feature, 'year': int(year), **spread_stats(g, rng)})
    results = pd.DataFrame(rows)
    results.to_csv(OUT / 'spreads.csv', index=False)
    pd.DataFrame(yearly).to_csv(OUT / 'yearly.csv', index=False)
    pd.DataFrame(deciles).to_csv(OUT / 'deciles.csv', index=False)
    summary = {'events': len(d), 'missing_or_nonfinite_removed': before - len(d),
               'dates': [str(d.date.min()), str(d.date.max())], 'skipped': skipped,
               'thresholds': edges, 'price_hashes': hashes,
               'limitations': ['Current constituents: survivorship and selection bias.',
                              'Yahoo cache not independently verified; EPS estimates not point-in-time vintaged.',
                              'Event averages are not portfolio returns; event dates need not balance exposure.',
                              'No locate availability, impact, taxes, cash yield or dividends on shorts separately modeled.',
                              'Quarter bootstrap is approximate with few confirmation quarters and no multiple-testing adjustment.',
                              'Fixed trading costs and borrow assumptions; no real fills observed.',
                              'Raw forward prices may differ from earlier residual-cache vintage.',
                              'Prior session excludes reaction day but intraday earnings may still contaminate announcement-day interpretation.']}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(results.round(2).to_string(index=False))
    print('Events:', len(d), 'date range:', summary['dates'])
    print('Saved:', OUT)


if __name__ == '__main__':
    main()
