"""Standalone diagnostic; never modifies trading code or cached inputs.

Hypothesis fixed before computation: strictly pre-announcement 5/20-day
residual momentum predicts 20-day post-reaction residual returns. Discovery
ends 2020; 2021-23 validation and 2024+ retrospective confirmation. These
historical periods have already been used elsewhere: not virgin holdouts.
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports' / 'edge_timing_probe'


def prior_close_index(timestamp, dates):
    """Conservative: exclude announcement calendar date, even for AMC."""
    return dates.searchsorted(pd.Timestamp(timestamp).normalize(), side='left') - 1


def main():
    OUT.mkdir(exist_ok=True)
    df = pd.read_parquet(ROOT / 'data/pead_labeled_features_expanded.parquet')
    residual = pd.read_parquet(ROOT / 'data/residual_returns_wide_expanded.parquet').sort_index()
    assert residual.index.is_unique
    assert not df.duplicated(['ticker', 'date']).any()
    dates = residual.index
    prior = np.array([prior_close_index(t, dates) for t in df.earnings_date_raw])
    reaction = dates.get_indexer(df.date)
    columns = residual.columns.get_indexer(df.ticker)
    assert (columns >= 0).all() and (reaction >= 0).all() and (prior >= 0).all()
    checks = {}
    for window in [5, 20]:
        values = residual.rolling(window, min_periods=window).sum().to_numpy()
        old = df[f'pre_earnings_return_{window}d'].to_numpy()
        reproduced = values[reaction, columns]
        df[f'strict_pre_{window}d'] = values[prior, columns]
        checks[f'{window}d'] = {
            'cached_matches_including_reaction_day': bool(np.allclose(old, reproduced, equal_nan=True)),
            'mean_abs_change_bps': float(np.nanmean(np.abs(old - df[f'strict_pre_{window}d'])) * 10000),
        }
    df['period'] = np.select([df.date.dt.year <= 2020, df.date.dt.year <= 2023],
                             ['discovery', 'validation'], default='confirmation')
    # Purge events within 45 calendar days of split boundaries (20 trading days).
    for boundary in [pd.Timestamp('2021-01-01'), pd.Timestamp('2024-01-01')]:
        df = df[~((df.date < boundary) & (df.date >= boundary - pd.Timedelta(days=45)))]
    rows, edges_out = [], {}
    for feature in ['pre_earnings_return_5d', 'pre_earnings_return_20d', 'strict_pre_5d', 'strict_pre_20d']:
        train = df.loc[df.period == 'discovery', feature].dropna()
        edges = np.quantile(train, np.linspace(0, 1, 11))
        edges[0], edges[-1] = -np.inf, np.inf
        edges_out[feature] = edges[1:-1].tolist()
        decile = pd.cut(df[feature], bins=edges, labels=False, include_lowest=True)
        for period in ['discovery', 'validation', 'confirmation']:
            sub = df[df.period == period].copy()
            sub['decile'] = decile.loc[sub.index]
            for bucket, group in sub.groupby('decile'):
                rows.append({'feature': feature, 'period': period, 'decile': int(bucket) + 1,
                             'n': len(group), 'mean_forward_bps': group.forward_return.mean() * 10000,
                             'median_forward_bps': group.forward_return.median() * 10000})
    table = pd.DataFrame(rows)
    table.to_csv(OUT / 'deciles.csv', index=False)
    spread_rows = []
    for (feature, period), group in table.groupby(['feature', 'period']):
        lo, hi = group.set_index('decile').loc[[1, 10]].to_dict('records')
        spread = (hi['mean_forward_bps'] - lo['mean_forward_bps']) / 2
        spread_rows.append({'feature': feature, 'period': period, 'n_low': lo['n'], 'n_high': hi['n'],
                            'half_long_high_short_low_bps': spread,
                            'net_10bps': spread - 10, 'net_25bps': spread - 25, 'net_50bps': spread - 50})
    spreads = pd.DataFrame(spread_rows)
    spreads.to_csv(OUT / 'spreads.csv', index=False)
    summary = {'timing_checks': checks, 'events_after_purge': len(df),
               'date_range': [str(df.date.min()), str(df.date.max())], 'train_decile_edges': edges_out,
               'limitations': ['Current S&P500 survivor universe, not point-in-time membership.',
                              'Summed fitted residuals are diagnostic labels, not executable portfolio returns.',
                              'Cached pre features include reaction close, unavailable at reaction open.',
                              'Strict pre excludes entire announcement calendar day conservatively.',
                              '10/25/50bps are assumed total gross-notional costs; no explicit borrow/hedge modeling.',
                              'No independence assumed for overlapping events; no iid t-stat or annualized Sharpe.',
                              'Four feature comparisons; unadjusted retrospective diagnostics, not a confirmed edge.']}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary['timing_checks'], indent=2))
    print(spreads.round(2).to_string(index=False))
    print('Results:', OUT)


if __name__ == '__main__':
    main()
