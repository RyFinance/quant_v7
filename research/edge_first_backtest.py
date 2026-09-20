"""First end-to-end portfolio backtest of the predeclared PEAD edge.

Fixed BEFORE any simulation (specification.json is written first):
  - Arms: (1) pead_long_only: long iff SUE > 0; (2) all_events_long_control:
    long every event regardless of sign; (3) pead_long_short: long SUE>0,
    short SUE<0. Arms 1 vs 2 isolates the sign signal from "long after
    earnings in a bull market".
  - Entry next session open after reaction-day close; hold 20 sessions
    (inclusive); exit at close. $5,000 slots on $10,000 (fixed notional,
    no compounding), max 12 concurrent, priority |SUE| desc then ticker.
  - Costs 10 bps round trip (5/side); stress 25 bps; shorts accrue 3% p.a.
  - Metrics: arithmetic daily mean, rf=0, sqrt(252) (house convention).
  - Verdict rule: edge requires pead_long_only net Sharpe > control net
    Sharpe over confirmation AND quarterly-block bootstrap CI of the daily
    mean difference excluding zero over the full sample.
Event study is NOT a capital-constrained live simulation; no deployment.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/edge_first_backtest'
EQUITY0, SLOT, MAX_POS, HOLD = 10_000.0, 5_000.0, 12, 20
COST_LEVELS = {'net_10bps': 10.0, 'net_25bps': 25.0}
BORROW_PA = 0.03
ARMS = {
    'pead_long_only': lambda s: 1 if s > 0 else 0,
    'all_events_long_control': lambda s: 1,
    'pead_long_short': lambda s: 1 if s > 0 else (-1 if s < 0 else 0),
    # Self-check-requested arms: loosen the filter from sign-only to magnitude.
    'pead_large_sue_long': lambda s: 1 if s >= 1 else 0,
    'pead_abs_sue_long': lambda s: 1 if abs(s) >= 1 else 0,
}
PERIODS = {'discovery': ('2015-01-01', '2020-12-31'), 'validation': ('2021-01-01', '2023-12-31'),
           'confirmation': ('2024-01-01', '2026-12-31')}
LIMITATIONS = [
    'Fixed $ slots, no compounding; capital never re-sizes with equity.',
    'Current S&P 500 constituents (survivorship/selection bias); Yahoo cache not vendor-verified.',
    'Capacity 12 x $5k ignores market impact; real fills unobserved.',
    'Positions carried across split boundaries; subperiod metrics include them.',
    'No dividends on longs, no locate/haircut beyond flat 3% borrow, cash yields zero.',
    'Stale marks: missing closes ffilled up to 10 sessions; returns treated as 0 while stale.',
    'Three arms x two cost levels reported; no multiple-testing adjustment.',
    'Confirmation period was previously studied by this repository; not a virgin holdout.',
]


def load_panel(tickers, calendar):
    opens = np.full((len(calendar), len(tickers)), np.nan)
    closes = np.full_like(opens, np.nan)
    for j, t in enumerate(tickers):
        d = pd.read_parquet(ROOT / 'data/raw' / f'{t}.parquet').set_index('timestamp').sort_index()
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        d = d.reindex(calendar)
        opens[:, j] = d.open.to_numpy()
        closes[:, j] = d.close.to_numpy()
    ff = pd.DataFrame(closes).ffill(limit=10).to_numpy()
    return opens, closes, ff


def simulate(side_fn, opens, ff, col, events, cost_bps):
    side_cost = cost_bps / 2 / 1e4
    daily = np.zeros(len(opens))
    pending = {}
    for e in events.itertuples():
        s = side_fn(e.signal)
        if s == 0:
            continue
        pending.setdefault(e.entry_i, []).append((-abs(e.signal), e.ticker, s))
    book, n_trades, skipped, stale = {}, 0, 0, 0
    for i in range(len(opens)):
        for _, t, s in sorted(pending.get(i, [])):
            if t in book or len(book) >= MAX_POS:
                continue
            j = col[t]
            op, cl = opens[i, j], ff[i, j]
            if not (np.isfinite(op) and op > 0 and np.isfinite(cl)):
                skipped += 1
                continue
            book[t] = (i, i + HOLD - 1, s, op)
            daily[i] -= SLOT * side_cost
            n_trades += 1
        for t, (ei, xi, s, ep) in list(book.items()):
            j = col[t]
            if i == ei:
                ret = ff[i, j] / ep - 1
            elif np.isfinite(ff[i - 1, j]) and np.isfinite(ff[i, j]) and ff[i - 1, j] > 0:
                ret = ff[i, j] / ff[i - 1, j] - 1
            else:
                ret, stale = 0.0, stale + 1
            daily[i] += s * SLOT * ret
            if s < 0:
                daily[i] -= SLOT * BORROW_PA / 252
            if i == xi:
                daily[i] -= SLOT * side_cost
                del book[t]
    return daily, n_trades, skipped, stale


def metrics(daily, index, lo, hi):
    m = (index >= lo) & (index <= hi)
    r = daily[m]
    equity = EQUITY0 + r.cumsum()
    peak = np.maximum.accumulate(equity)
    sharpe = r.mean() / r.std(ddof=1) * np.sqrt(252) if r.std(ddof=1) > 0 else 0.0
    cagr = (equity[-1] / EQUITY0) ** (252 / len(r)) - 1 if len(r) else np.nan
    return {'cagr': cagr, 'ann_vol': r.std(ddof=1) * np.sqrt(252), 'sharpe': sharpe,
            'max_drawdown': float(((equity - peak) / EQUITY0).min()),
            'total_pnl': float(r.sum()), 'total_return': equity[-1] / EQUITY0 - 1}


def main():
    OUT.mkdir(exist_ok=True)
    events = pd.read_parquet(ROOT / 'reports/edge_executable_probe/events.parquet')
    spy = pd.read_parquet(ROOT / 'data/raw_legacy/SPY.parquet').set_index('timestamp').sort_index()
    spy.index = pd.to_datetime(spy.index).tz_localize(None).normalize()
    calendar = spy.index
    events['entry_i'] = calendar.get_indexer(events.entry_date)
    assert (events.entry_i >= 0).all() and (events.entry_i + HOLD <= len(calendar)).all()
    tickers = sorted(events.ticker.unique())
    col = {t: j for j, t in enumerate(tickers)}
    spec = {'arms': {k: f.__doc__ or 'predeclared side rule' for k, f in ARMS.items()},
            'sizing': {'equity0': EQUITY0, 'slot': SLOT, 'max_positions': MAX_POS,
                       'hold_sessions': HOLD, 'priority': 'abs(SUE) desc, then ticker'},
            'costs': {'round_trip_bps': COST_LEVELS, 'short_borrow_pa': BORROW_PA},
            'periods': {k: list(v) for k, v in PERIODS.items()},
            'verdict_rule': 'pead_long_only net Sharpe > control net Sharpe on confirmation AND '
                            'quarter-block bootstrap CI of full-sample daily mean difference excludes 0',
            'limitations': LIMITATIONS,
            'input_sha256': {
                'reports/edge_executable_probe/events.parquet':
                    hashlib.sha256((ROOT / 'reports/edge_executable_probe/events.parquet').read_bytes()).hexdigest(),
                'data/raw_legacy/SPY.parquet': hashlib.sha256((ROOT / 'data/raw_legacy/SPY.parquet').read_bytes()).hexdigest()}}
    (OUT / 'specification.json').write_text(json.dumps(spec, indent=2))

    opens, closes, ff = load_panel(tickers, calendar)
    spy_ret = pd.DataFrame({'spy': spy.close.pct_change().fillna(0).to_numpy()}, index=calendar)
    results, daily_by_arm = {}, {}
    for cost_name, cost_bps in COST_LEVELS.items():
        for arm, fn in ARMS.items():
            global side_cost
            side_cost = cost_bps / 2 / 1e4
            daily, n_trades, skipped, stale = simulate(fn, opens, ff, col, events, cost_bps)
            daily_by_arm[(arm, cost_name)] = daily
            results[f'{arm}__{cost_name}'] = {'n_trades': n_trades, 'skipped_no_fill': skipped,
                                              'stale_marks': stale,
                                              **{p: metrics(daily, calendar, *r) for p, r in PERIODS.items()},
                                              'full': metrics(daily, calendar, calendar.min(), calendar.max())}
    spy_m = {'full': metrics(spy_ret.spy.to_numpy(), calendar, calendar.min(), calendar.max()),
             **{p: metrics(spy_ret.spy.to_numpy(), calendar, *r) for p, r in PERIODS.items()}}
    results['spy_buy_hold_gross'] = spy_m

    diff = daily_by_arm[('pead_long_only', 'net_10bps')] - daily_by_arm[('all_events_long_control', 'net_10bps')]
    q = pd.Series(calendar.to_period('Q').astype(str), index=range(len(calendar)))
    blocks = pd.Series(diff).groupby(q.values).agg(['sum', 'count'])
    rng = np.random.default_rng(17092026)
    boots = []
    for _ in range(2000):
        s = blocks.iloc[rng.integers(len(blocks), size=len(blocks))].sum()
        boots.append(s['sum'] / s['count'])
    ci = np.quantile(boots, [.025, .975]) * 252  # dollars per year (daily series is $ PnL)
    results['paired_pead_minus_control'] = {
        'units': 'dollars per year on $10k equity',
        'annualized_mean_diff_dollars': float(diff.mean() * 252),
        'boot95_annualized_dollars': [float(ci[0]), float(ci[1])],
        'excludes_zero': bool(ci[0] > 0 or ci[1] < 0)}
    daily = pd.DataFrame({'pead_long_only': daily_by_arm[('pead_long_only', 'net_10bps')],
                          'all_events_long_control': daily_by_arm[('all_events_long_control', 'net_10bps')],
                          'pead_long_short': daily_by_arm[('pead_long_short', 'net_10bps')],
                          'pead_large_sue_long': daily_by_arm[('pead_large_sue_long', 'net_10bps')],
                          'pead_abs_sue_long': daily_by_arm[('pead_abs_sue_long', 'net_10bps')],
                          'pead_long_only_25bps': daily_by_arm[('pead_long_only', 'net_25bps')],
                          'spy': spy_ret.spy.to_numpy()}, index=calendar)
    daily.to_csv(OUT / 'daily_returns.csv')
    results['verdict'] = {
        'confirmation_net10_sharpe': results['pead_long_only__net_10bps']['confirmation']['sharpe'],
        'control_confirmation_net10_sharpe': results['all_events_long_control__net_10bps']['confirmation']['sharpe'],
        'edge_confirmed_by_predeclared_rule': bool(
            results['pead_long_only__net_10bps']['confirmation']['sharpe']
            > results['all_events_long_control__net_10bps']['confirmation']['sharpe']
            and results['paired_pead_minus_control']['excludes_zero']),
        'large_sue_confirmation_net10_sharpe': results['pead_large_sue_long__net_10bps']['confirmation']['sharpe'],
        'abs_sue_confirmation_net10_sharpe': results['pead_abs_sue_long__net_10bps']['confirmation']['sharpe']}
    (OUT / 'results.json').write_text(json.dumps(results, indent=2, default=float))
    for arm in ARMS:
        for cost in COST_LEVELS:
            k = f'{arm}__{cost}'
            r = results[k]
            print(f"{k:38s} full Sharpe {r['full']['sharpe']:5.2f}  CAGR {r['full']['cagr']:6.1%}  "
                  f"conf Sharpe {r['confirmation']['sharpe']:5.2f}  trades {r['n_trades']}")
    print('paired annualized diff $:', round(results['paired_pead_minus_control']['annualized_mean_diff_dollars'], 1),
          'CI $:', [round(x, 1) for x in results['paired_pead_minus_control']['boot95_annualized_dollars']])
    print('VERDICT:', results['verdict']['edge_confirmed_by_predeclared_rule'])


if __name__ == '__main__':
    main()
