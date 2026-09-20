"""Reconstruct point-in-time S&P 500 membership and re-run the frozen momentum rule on it.

Arm A  cache universe      - what the frozen candidate actually traded (today's 503 members).
Arm B  members-at-the-date - the same rule restricted to names already in the index on the
                             decision date. The A-B gap is the 'admitted later' component of
                             survivorship bias. Names removed from the index before today are
                             absent from the price cache entirely; their share is reported as
                             uncovered, not silently dropped.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / 'reports/momentum_verification_20260919/inputs'
OUT = ROOT / 'reports/momentum_verification_20260919'
TODAY = pd.Timestamp('2026-09-19')


def membership() -> dict[pd.Timestamp, set[str]]:
    """Walk the dated changes ledger backwards from today's constituents."""
    current = set(pd.read_pickle(IN / 'constituents.pkl')['Symbol'].str.replace('.', '-', regex=False))
    ch = pd.read_pickle(IN / 'changes.pkl')
    ch.columns = ['_'.join(c) if isinstance(c, tuple) else c for c in ch.columns]
    ch['date'] = pd.to_datetime(ch.iloc[:, 0], errors='coerce', format='mixed')
    ch = ch.dropna(subset=['date']).sort_values('date', ascending=False)
    snapshots = {TODAY: set(current)}
    members = set(current)
    for _, row in ch.iterrows():
        added = str(row['Added_Ticker']).replace('.', '-') if pd.notna(row['Added_Ticker']) else None
        removed = str(row['Removed_Ticker']).replace('.', '-') if pd.notna(row['Removed_Ticker']) else None
        if added and added in members:
            members.discard(added)
        if removed:
            members.add(removed)
        snapshots[row['date']] = set(members)
    return dict(sorted(snapshots.items()))


def members_on(snapshots, date) -> set[str]:
    """Membership in force on `date` = the snapshot taken at the latest change on or before it."""
    keys = [k for k in snapshots if k <= date]
    return snapshots[max(keys)] if keys else snapshots[min(snapshots)]


def load_panel(end='2026-09-17'):
    frames = {}
    for p in sorted((ROOT / 'data/multiasset/stocks').glob('*.parquet')):
        d = pd.read_parquet(p)
        d.index = pd.to_datetime(d['date']).dt.tz_localize(None).dt.normalize()
        frames[p.stem] = d.sort_index().loc[:end]
    spy = pd.read_parquet(ROOT / 'data/multiasset/etf/SPY.parquet')
    spy.index = pd.to_datetime(spy['date']).dt.tz_localize(None).dt.normalize()
    dates = spy.sort_index().loc['2007':end].index
    return {k: pd.DataFrame({s: d[k] for s, d in frames.items()}).reindex(dates).astype(float)
            for k in ['open', 'close', 'volume']}, dates


def build_targets(p, dates, universe_on=None, slots=20):
    close, volume = p['close'], p['volume']
    adv = (close * volume).rolling(63).mean()
    score = close.shift(21) / close.shift(252) - 1
    base = close.shift(252).notna() & close.gt(0) & adv.notna()
    month = pd.Series(dates.to_period('M'), index=dates)
    decision = month.ne(month.shift())
    targets = pd.DataFrame(np.nan, index=dates, columns=close.columns)
    coverage = []
    for date in dates[decision]:
        ok = base.loc[date].copy()
        if universe_on is not None:
            allowed = universe_on(date)
            n_members = len(allowed)
            ok &= close.columns.isin(allowed)
            coverage.append({'date': str(date.date()), 'members': n_members,
                             'priced_members': int(ok.sum()),
                             'uncovered': n_members - int((close.columns.isin(allowed) & close.loc[date].notna()).sum())})
        a = adv.loc[date].where(ok)
        ok &= a.gt(20e6) & a.rank(ascending=False, method='first').le(200)
        s = score.loc[date].where(ok).replace([np.inf, -np.inf], np.nan).dropna()
        s = s[s > 0].nlargest(slots)
        targets.loc[date] = 0.0
        if len(s):
            targets.loc[date, s.index] = 1 / slots
    return targets, pd.DataFrame(coverage)


def main():
    import research.return_search.run as rs
    snapshots = membership()
    sizes = pd.Series({d: len(s) for d, s in snapshots.items()})
    print('membership snapshots', len(snapshots), 'index size min/median/max',
          sizes.min(), int(sizes.median()), sizes.max(), flush=True)
    print('changes per year:')
    per_year = pd.Series(list(snapshots.keys())).dt.year.value_counts().sort_index()
    print(per_year.loc[2005:].to_string(), flush=True)

    p, dates = load_panel()
    rf = rs.cash_rates(dates, '2026-09-17')
    results = {}
    for arm, uni in [('A_cache_universe', None),
                     ('B_point_in_time_members', lambda d: members_on(snapshots, d))]:
        t, cov = build_targets(p, dates, uni)
        t.to_parquet(OUT / f'{arm}_targets.parquet')
        if len(cov):
            cov.to_csv(OUT / 'membership_coverage.csv', index=False)
        results[arm] = {}
        for start, label in [('2019-01-01', '2019..2026'), ('2008-01-01', '2008..2026')]:
            f = rs.execute(p, t, rf, 'stocks', stress=False, start=start)
            f.to_csv(OUT / f'{arm}_{label}.csv')
            results[arm][label] = rs.stats(f, rf, 252)
            st = results[arm][label]
            print(f'{arm:26s} {label}  CAGR {st["cagr"]*100:6.2f}%  Sharpe {st["excess_sharpe"]:.2f}  '
                  f'maxDD {st["max_dd"]*100:7.2f}%  turnover {st["annual_turnover"]:.1f}', flush=True)
    (OUT / 'membership_arms.json').write_text(json.dumps(results, indent=2))

    cov = pd.read_csv(OUT / 'membership_coverage.csv', parse_dates=['date'])
    print('\npoint-in-time coverage (members we can price):')
    for y, g in cov.groupby(cov.date.dt.year):
        print(f'  {y}  members {g.members.mean():5.0f}   priced {g.priced_members.mean():5.0f}   '
              f'uncovered {100*(1-g.priced_members.mean()/g.members.mean()):5.1f}%')


if __name__ == '__main__':
    main()
