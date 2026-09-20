"""Frozen three-hypothesis FX pilot. Read-only market data, no execution API."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/fx_session_20260918'
OUT = ROOT / 'reports/fx_session_20260918'
SPEC_PATH = ROOT / 'research/fx_session_spec_20260918.json'
SYMBOLS = ['EURUSD', 'GBPUSD', 'USDJPY']


def usd_pnl_fraction(symbol, entry, exit_, side):
    """Fixed base-currency units, entry exposure measured in USD."""
    if not (entry > 0 and exit_ > 0):
        raise ValueError('nonpositive FX price')
    return side * (1 - entry / exit_ if symbol == 'USDJPY' else exit_ / entry - 1)


def trade_cost(symbol, entry, exit_, notional, costs):
    exit_notional = notional if symbol == 'USDJPY' else notional * exit_ / entry
    return sum(n * costs['spread_slippage_bps_per_side'] / 1e4
               + max(costs['minimum_commission_usd_per_order'],
                     n * costs['commission_bps_per_side'] / 1e4)
               for n in [notional, exit_notional])


def load_data():
    spec = json.loads(SPEC_PATH.read_text())
    registered = json.loads((OUT / 'registration.json').read_text())
    assert hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest() == registered['spec_sha256']
    manifest = json.loads((DATA / 'manifest.json').read_text())
    for item in manifest['files']:
        assert hashlib.sha256((ROOT / item['file']).read_bytes()).hexdigest() == item['sha256']
    frames, audit = {}, {}
    for s in SYMBOLS:
        d = pd.read_parquet(DATA / f'{s}_1h.parquet')
        d['ts'] = pd.to_datetime(d.ts, utc=True)
        d = d.set_index('ts').sort_index()
        if d.index.has_duplicates or d.index.max() >= pd.Timestamp('2018-01-01', tz='UTC'):
            raise ValueError('duplicates or reserved dates')
        if not np.isfinite(d[['open', 'high', 'low', 'close']]).all().all():
            raise ValueError('nonfinite prices')
        if not ((d.low <= d[['open', 'close']].min(axis=1)) &
                (d.high >= d[['open', 'close']].max(axis=1)) & (d.low > 0)).all():
            raise ValueError('invalid OHLC')
        frames[s] = d
        audit[s] = {'rows': len(d), 'first': str(d.index.min()), 'last': str(d.index.max())}
    small = pd.read_parquet(DATA / 'EURUSD_timestamp_check_5m.parquet')
    small['ts'] = pd.to_datetime(small.ts, utc=True)
    small = small.set_index('ts').sort_index()
    hourly = small.resample('1h', label='left', closed='left').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    original = frames['EURUSD'].reindex(hourly.index)[hourly.columns]
    max_diff = float((original - hourly).abs().max().max())
    audit['bar_timestamp_check'] = {'max_ohlc_difference_1h_vs_5m': max_diff,
                                    'tested_hours': len(hourly),
                                    'interpretation': 'empirical bar-start consistency, not bid/ask verification'}
    if max_diff > 1e-8:
        raise ValueError(f'bar-start aggregation inconsistent: {max_diff}')
    (OUT / 'data_audit.json').write_text(json.dumps(audit, indent=2))
    return spec, frames


def local_session(d, zone, calendar):
    d = d.copy()
    local = d.index.tz_convert(zone)
    d['day'] = local.tz_localize(None).normalize()
    d['hour'] = local.hour
    # Weekday hours used here never fall in the DST repeated-hour interval.
    op = d.pivot(index='day', columns='hour', values='open').reindex(calendar)
    cp = d.pivot(index='day', columns='hour', values='close').reindex(calendar)
    signal_return = cp[7] / op[0] - 1
    complete_signal = op.reindex(columns=range(8)).notna().all(axis=1) & cp.reindex(columns=range(8)).notna().all(axis=1)
    signal_return = signal_return.where(complete_signal)
    scale = signal_return.rolling(60, min_periods=40).std().shift(1)
    z = signal_return / scale
    return op, z


def generate_orders(frames, name):
    calendar = pd.bdate_range('2009-10-01', '2017-12-29')
    zone = 'America/New_York' if name == 'new_york_continuation' else 'Europe/London'
    orders = []
    missing_signals = 0
    unfilled = []
    for s, d in frames.items():
        op, z = local_session(d, zone, calendar)
        for date in calendar[calendar >= '2010-01-01']:
            # Known FX market holidays, excluded ex ante, not by price outcome.
            if (date.month, date.day) in [(1, 1), (12, 25)]:
                continue
            if name == 'london_fix_reversal':
                usd_long = 1 if s == 'USDJPY' else -1
                legs = [(14, 16, usd_long), (16, 18, -usd_long)]
            else:
                signal = z.loc[date]
                if not np.isfinite(signal):
                    missing_signals += 1
                    continue
                if abs(signal) < 1:
                    continue
                side = np.sign(signal) * (-1 if name == 'london_reversal' else 1)
                legs = [(9, 13, side)]
            for entry_hour, exit_hour, side in legs:
                ep, xp = op.loc[date, entry_hour], op.loc[date, exit_hour]
                if not np.isfinite(ep):
                    unfilled.append({'symbol': s, 'date': str(date.date()), 'entry_hour': entry_hour})
                    continue
                if not np.isfinite(xp):
                    raise ValueError(f'{name}: missing scheduled fill {s} {date.date()} {entry_hour}/{exit_hour}')
                orders.append({'date': date, 'symbol': s, 'side': int(side),
                               'entry': float(ep), 'exit': float(xp),
                               'entry_time': str(pd.Timestamp(date).tz_localize(zone) + pd.Timedelta(hours=entry_hour)),
                               'exit_time': str(pd.Timestamp(date).tz_localize(zone) + pd.Timedelta(hours=exit_hour)),
                               'gross_fraction': usd_pnl_fraction(s, ep, xp, side)})
    (OUT / f'{name}_unfilled.json').write_text(json.dumps(unfilled, indent=2))
    return pd.DataFrame(orders), missing_signals


def simulate(orders, costs, capital=100000):
    nav = capital
    rows, fills = [], []
    grouped = {d: x for d, x in orders.groupby('date')}
    for date in pd.bdate_range('2010-01-01', '2017-12-29'):
        before = nav
        pnl = fees = gross = 0.0
        by_pair = {s: 0.0 for s in SYMBOLS}
        for o in grouped.get(date, pd.DataFrame()).itertuples():
            n = before / 3
            fee = trade_cost(o.symbol, o.entry, o.exit, n, costs)
            gain = n * o.gross_fraction
            pnl += gain
            fees += fee
            gross += n
            by_pair[o.symbol] += gain - fee
            fills.append({**o._asdict(), 'notional_usd': n, 'gross_pnl_usd': gain, 'cost_usd': fee})
        nav += pnl - fees
        if nav <= 0:
            raise ValueError(f'insolvent on {date.date()}; fees and losses exhausted capital')
        rows.append({'date': date, 'nav': nav, 'return': nav / before - 1,
                     'gross_return': pnl / before, 'cost_return': fees / before,
                     'traded_entry_notional_ratio': gross / before,
                     **{s: by_pair[s] / before for s in SYMBOLS}})
    return pd.DataFrame(rows).set_index('date'), pd.DataFrame(fills)


def stats(d):
    r = d['return']
    nav = (1 + r).cumprod()
    drawdown = nav / nav.cummax().clip(lower=1) - 1
    return {'days': len(r), 'ann_mean': float(r.mean() * 252),
            'return_vol_ratio': float(r.mean() / r.std(ddof=1) * np.sqrt(252)),
            'cagr': float(nav.iloc[-1] ** (252 / len(r)) - 1),
            'ann_vol': float(r.std(ddof=1) * np.sqrt(252)),
            'max_daily_drawdown': float(drawdown.min()),
            'ann_cost_drag': float(d.cost_return.mean() * 252),
            'gross_return_vol_ratio': float(d.gross_return.mean() / d.gross_return.std(ddof=1) * np.sqrt(252)),
            'pair_ann_contribution': {s: float(d[s].mean() * 252) for s in SYMBOLS}}


def bootstrap(r, block, samples=5000):
    a = r.to_numpy()
    rng = np.random.default_rng(20260918)
    estimates = []
    ratios = []
    for _ in range(samples):
        idx = (rng.integers(len(a), size=int(np.ceil(len(a) / block)))[:, None] + np.arange(block)) % len(a)
        x = a[idx.ravel()[:len(a)]]
        estimates.append(x.mean())
        ratios.append(x.mean() / x.std(ddof=1) * np.sqrt(252))
    p = (1 + np.sum(np.asarray(estimates) - a.mean() >= a.mean())) / (samples + 1)
    return {'ann_mean_ci95': (np.quantile(estimates, [.025, .975]) * 252).tolist(),
            'ratio_ci95': np.quantile(ratios, [.025, .975]).tolist(),
            'one_sided_null_p': float(p), 'three_candidate_bonferroni_p': float(min(1, p * 3))}


def main():
    spec, frames = load_data()
    result, paths = {}, {}
    for name in spec['candidates']:
        try:
            orders, missing = generate_orders(frames, name)
        except ValueError as e:
            result[name] = {'invalid': str(e)}
            print(str(e), flush=True)
            continue
        result[name] = {'orders': len(orders), 'missing_signal_days_pairs': missing}
        for level, costs in spec['costs'].items():
            try:
                daily, fills = simulate(orders, costs, spec['initial_nav_usd'])
            except ValueError as e:
                result[name][level] = {'invalid': str(e)}
                continue
            paths[name, level] = daily
            daily.to_csv(OUT / f'{name}_{level}_daily.csv')
            fills.to_parquet(OUT / f'{name}_{level}_fills.parquet', index=False)
            result[name][level] = {'development': stats(daily.loc['2010':'2013']),
                                   'validation': stats(daily.loc['2014':'2017'])}
    valid = [n for n in result if 'invalid' not in result[n] and 'invalid' not in result[n]['base']]
    selected = max(valid, key=lambda n: result[n]['base']['development']['return_vol_ratio']) if valid else None
    if selected:
        (OUT / 'selection.json').write_text(json.dumps({'selected': selected, 'basis': 'development only'}, indent=2))
        r = result[selected]
        validation = paths[selected, 'base'].loc['2014':'2017', 'return']
        r['validation_uncertainty_20d'] = bootstrap(validation, 20)
        r['validation_uncertainty_63d'] = bootstrap(validation, 63)
        gate = (r['base']['development']['return_vol_ratio'] >= .5
                and r['base']['validation']['return_vol_ratio'] >= .75
                and 'invalid' not in r['stress_2x'] and r['stress_2x']['validation']['ann_mean'] > 0
                and min(r['base']['validation']['pair_ann_contribution'].values()) > 0
                and r['validation_uncertainty_20d']['three_candidate_bonferroni_p'] < .05)
    else:
        gate = False
    result['decision'] = {'selected': selected, 'passes_pilot_gate': bool(gate),
                          'later_data_evaluated': False, 'live_trading_changed': False}
    result['code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT / 'results.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
